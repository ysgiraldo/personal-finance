import os
import json
import urllib.request
import urllib.error

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
_BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def enviar_mensaje(chat_id, texto):
    """Envia un mensaje de texto a un chat de Telegram. Usa solo la libreria
    estandar (urllib) para no tener que empaquetar dependencias extra en Lambda."""
    url = f"{_BASE_URL}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": texto}).encode("utf-8")
    peticion = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            return json.loads(respuesta.read())
    except urllib.error.HTTPError as err:
        cuerpo = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram respondio error {err.code}: {cuerpo}") from err


def configurar_webhook(url_publica):
    """Le dice a Telegram hacia donde debe mandar los mensajes entrantes.
    Se corre UNA SOLA VEZ (o cada vez que cambie la URL del API Gateway)."""
    url = f"{_BASE_URL}/setWebhook"
    payload = json.dumps({"url": url_publica}).encode("utf-8")
    peticion = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(peticion, timeout=10) as respuesta:
        return json.loads(respuesta.read())
