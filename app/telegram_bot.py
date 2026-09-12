import os
import logging
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from . import db
from . import goals
from .core import procesar_mensaje

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
MY_CHAT_ID = os.environ.get("MY_TELEGRAM_CHAT_ID") 
TZ = ZoneInfo("America/Bogota")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    texto = update.message.text or ""

    if not MY_CHAT_ID:
        await update.message.reply_text(
            f"Tu chat_id es: {chat_id}\n\n"
            "Copialo en tu archivo .env como MY_TELEGRAM_CHAT_ID y reinicia "
            "el bot para que solo tu puedas usarlo."
        )
        return

    if chat_id != MY_CHAT_ID:
        logger.warning(f"Mensaje ignorado de chat_id={chat_id} (no coincide con MY_TELEGRAM_CHAT_ID configurado)")
        return  # ignoramos mensajes de cualquier otro chat

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
