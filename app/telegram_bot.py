import os
import logging
import threading
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from . import db
from . import goals
from .core import procesar_mensaje

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
# Silenciamos los logs de cada ping de salud, para no ensuciar la consola
logging.getLogger("werkzeug").setLevel(logging.WARNING)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
MY_CHAT_ID = os.environ.get("MY_TELEGRAM_CHAT_ID")  # vacio la primera vez, ver instrucciones abajo
TZ = ZoneInfo("America/Bogota")


# --- Mini-servidor ---
# Render (y similares) solo ofrecen nivel gratuito a servicios que escuchan
# un puerto HTTP ("Web Service"), no a los Background Workers, abrimos un puerto
# minimo para calificar como Web Service y evitar el costo del Worker.
salud_app = Flask(__name__)


@salud_app.route("/")
@salud_app.route("/health")
def salud():
    return "Bot de finanzas corriendo ✅", 200


def iniciar_servidor_de_salud():
    puerto = int(os.environ.get("PORT", 10000))
    salud_app.run(host="0.0.0.0", port=puerto)


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    texto = update.message.text or ""

    # Primera vez: si aun no configuraste tu chat_id, te lo mostramos para que
    # lo copies en .env. Esto evita que cualquier persona use tu bot.
    if not MY_CHAT_ID:
        await update.message.reply_text(
            f"Tu chat_id es: {chat_id}\n\n"
            "Copialo en tu archivo .env como MY_TELEGRAM_CHAT_ID y reinicia "
            "el bot para que solo tu puedas usarlo."
        )
        return

    if chat_id != MY_CHAT_ID:
        return

    try:
        respuesta = procesar_mensaje(texto)
    except Exception:
        logger.exception("Error procesando mensaje")
        respuesta = "Tuve un error procesando tu mensaje, intenta de nuevo."

    await update.message.reply_text(respuesta)


async def _job_resumen_semanal(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=MY_CHAT_ID, text=goals.resumen_semanal())
        logger.info("Resumen semanal enviado")
    except Exception:
        logger.exception("Error enviando resumen semanal")


async def _job_alerta_presupuesto(context: ContextTypes.DEFAULT_TYPE):
    try:
        texto = goals.resumen_mensual_con_proyeccion()
        if "⚠️" in texto:
            await context.bot.send_message(chat_id=MY_CHAT_ID, text=f"Alerta de presupuesto:\n{texto}")
            logger.info("Alerta de proyeccion mensual enviada")
    except Exception:
        logger.exception("Error calculando proyeccion mensual")


def main():
    if not BOT_TOKEN:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en tu archivo .env")

    db.init_db()

    # Arrancamos el mini-servidor de salud en un hilo aparte, en paralelo al bot.
    # daemon=True para que este hilo no impida que el programa cierre normalmente.
    hilo_salud = threading.Thread(target=iniciar_servidor_de_salud, daemon=True)
    hilo_salud.start()
    logger.info(f"Servidor de salud escuchando en el puerto {os.environ.get('PORT', 10000)}")

    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    if MY_CHAT_ID:
        # Resumen semanal: domingos a las 8:00 PM (hora Bogota). weekday 6 = domingo.
        telegram_app.job_queue.run_daily(
            _job_resumen_semanal, time=time(20, 0, tzinfo=TZ), days=(6,), name="resumen_semanal"
        )
        # Alerta de presupuesto: todos los dias a las 9:00 AM (solo avisa si hay riesgo)
        telegram_app.job_queue.run_daily(
            _job_alerta_presupuesto, time=time(9, 0, tzinfo=TZ), name="alerta_presupuesto"
        )
        logger.info("Cron jobs activados (resumen semanal: domingos 8pm, alertas: diario 9am)")
    else:
        logger.info("MY_TELEGRAM_CHAT_ID no configurado. Escribele al bot para obtener tu chat_id.")

    logger.info("Bot de Telegram corriendo (polling)...")
    telegram_app.run_polling()


if __name__ == "__main__":
    main()
