import os
import re
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

from . import db
from . import goals
from .llm import interpretar_mensaje
from .scheduler import iniciar_scheduler

app = Flask(__name__)
db.init_db()
iniciar_scheduler()  # arranca los cron jobs de resumenes automaticos

MY_PHONE_NUMBER = os.environ.get("MY_PHONE_NUMBER")


def hoy_iso():
    return datetime.now().strftime("%Y-%m-%d")


def procesar_mensaje(texto):
    """Procesa el texto de un mensaje y devuelve la respuesta para el usuario.
    Separado del webhook para poder reusarlo en el endpoint de prueba local
    sin necesidad de tener Twilio configurado."""
    texto_limpio = texto.strip().lower()

    # Comandos especiales antes de mandar al LLM
    if texto_limpio in ("resumen semanal", "como voy", "cómo voy"):
        return goals.resumen_semanal()

    if texto_limpio in ("resumen mensual", "proyeccion", "proyección"):
        return goals.resumen_mensual_con_proyeccion()

    match_presupuesto = re.match(r"^definir presupuesto (\w+) (\d+)", texto_limpio)
    if match_presupuesto:
        categoria, monto = match_presupuesto.groups()
        db.definir_presupuesto(categoria, float(monto))
        return f"Presupuesto definido: {goals.formato_pesos(float(monto))} para {categoria}."

    match_meta_ahorro = re.match(r"^definir ahorro (\d+) (\d{4}-\d{2}-\d{2})", texto_limpio)
    if match_meta_ahorro:
        monto, fecha = match_meta_ahorro.groups()
        db.definir_meta_ahorro(float(monto), fecha)
        return f"Meta de ahorro definida: {goals.formato_pesos(float(monto))} para el {fecha}."

    # Si no es un comando conocido, lo interpretamos como un movimiento financiero
    datos = interpretar_mensaje(texto)

    if datos is None:
        return 'No entendi ese mensaje como un movimiento financiero. Prueba algo como "gaste 25000 en almuerzo".'

    db.agregar_transaccion(
        fecha=hoy_iso(),
        tipo=datos["tipo"],
        monto=datos["monto"],
        categoria=datos["categoria"],
        descripcion=datos["descripcion"],
    )

    respuesta = f"Registrado: {goals.formato_pesos(datos['monto'])} ({datos['tipo']}) en {datos['categoria']}."

    if datos["tipo"] == "gasto":
        progreso_texto = goals.mensaje_progreso_categoria(datos["categoria"])
        if progreso_texto:
            respuesta += f"\n{progreso_texto}"

    return respuesta


@app.route("/sms", methods=["POST"])
def sms_webhook():
    """Webhook real que Twilio llama cuando te llega un SMS."""
    remitente = request.form.get("From")
    texto = request.form.get("Body", "")

    twiml = MessagingResponse()

    # Seguridad basica: solo tu numero puede escribirle al bot
    if remitente != MY_PHONE_NUMBER:
        return str(twiml), 200, {"Content-Type": "text/xml"}

    try:
        respuesta = procesar_mensaje(texto)
        twiml.message(respuesta)
    except Exception as err:
        print(f"Error procesando mensaje: {err}")
        twiml.message("Tuve un error procesando tu mensaje, intenta de nuevo.")

    return str(twiml), 200, {"Content-Type": "text/xml"}


@app.route("/test", methods=["POST"])
def test_endpoint():
    """Endpoint de prueba local: deja probar la logica SIN Twilio configurado.
    Uso: POST /test  { "texto": "gaste 25000 en almuerzo" }"""
    texto = (request.get_json(silent=True) or {}).get("texto", "")
    try:
        respuesta = procesar_mensaje(texto)
        return jsonify({"respuesta": respuesta})
    except Exception as err:
        return jsonify({"error": str(err)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print(f"Servidor corriendo en http://localhost:{port}")
    print(f'Prueba local: POST http://localhost:{port}/test  {{"texto": "..."}}')
    app.run(host="0.0.0.0", port=port)
