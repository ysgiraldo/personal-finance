import os
import json

from app import db
from app import goals
from app import telegram_api
from app.core import procesar_mensaje

MY_CHAT_ID = os.environ.get("MY_TELEGRAM_CHAT_ID")


def handler(event, context):
    """Punto de entrada unico de Lambda. Distingue dos tipos de invocacion:

    1. Webhook de Telegram (via API Gateway): event trae 'body' con el update.
    2. Job programado (via EventBridge Scheduler): event trae 'accion', ej.
       {"accion": "resumen_semanal"} o {"accion": "alerta_presupuesto"}.
    """
    if "accion" in event:
        return _manejar_job_programado(event["accion"])

    return _manejar_webhook_telegram(event)


def _manejar_webhook_telegram(event):
    try:
        cuerpo = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 200, "body": "ignorado (body invalido)"}

    mensaje = cuerpo.get("message")
    if not mensaje or "text" not in mensaje:
        # Respondemos 200 igual para que Telegram no reintente el envio.
        return {"statusCode": 200, "body": "ignorado (sin texto)"}

    chat_id = str(mensaje["chat"]["id"])
    texto = mensaje["text"]

    if not MY_CHAT_ID:
        telegram_api.enviar_mensaje(
            chat_id,
            f"Tu chat_id es: {chat_id}\n\n"
            "Configuralo como variable de entorno MY_TELEGRAM_CHAT_ID en tu "
            "funcion Lambda para que solo tu puedas usar el bot.",
        )
        return {"statusCode": 200, "body": "ok (mostrando chat_id)"}

    if chat_id != MY_CHAT_ID:
        print(f"Mensaje ignorado de chat_id={chat_id} (no coincide con MY_TELEGRAM_CHAT_ID)")
        return {"statusCode": 200, "body": "ignorado (chat_id no autorizado)"}

    try:
        respuesta = procesar_mensaje(texto)
    except Exception as err:
        print(f"Error procesando mensaje: {err}")
        respuesta = "Tuve un error procesando tu mensaje, intenta de nuevo."

    telegram_api.enviar_mensaje(chat_id, respuesta)
    return {"statusCode": 200, "body": "ok"}


def _manejar_job_programado(accion):
    if not MY_CHAT_ID:
        print("MY_TELEGRAM_CHAT_ID no configurado, no se puede enviar el job programado.")
        return {"statusCode": 200, "body": "sin chat_id configurado"}

    try:
        if accion == "resumen_semanal":
            telegram_api.enviar_mensaje(MY_CHAT_ID, goals.resumen_semanal())

        elif accion == "alerta_presupuesto":
            texto = goals.resumen_mensual_con_proyeccion()
            if "⚠️" in texto:
                telegram_api.enviar_mensaje(MY_CHAT_ID, f"Alerta de presupuesto:\n{texto}")

        else:
            print(f"Accion programada desconocida: {accion}")

    except Exception as err:
        print(f"Error ejecutando job programado '{accion}': {err}")

    return {"statusCode": 200, "body": "ok"}
