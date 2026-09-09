import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from twilio.rest import Client as TwilioClient

from . import goals

_scheduler = None


def _twilio_client():
    return TwilioClient(
        os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN")
    )


def _enviar_sms(texto):
    _twilio_client().messages.create(
        body=texto,
        from_=os.environ.get("TWILIO_PHONE_NUMBER"),
        to=os.environ.get("MY_PHONE_NUMBER"),
    )


def _job_resumen_semanal():
    try:
        _enviar_sms(goals.resumen_semanal())
        print("Resumen semanal enviado")
    except Exception as err:
        print(f"Error enviando resumen semanal: {err}")


def _job_alerta_presupuesto():
    try:
        texto = goals.resumen_mensual_con_proyeccion()
        if "⚠️" in texto:
            _enviar_sms(f"Alerta de presupuesto:\n{texto}")
            print("Alerta de proyeccion mensual enviada")
    except Exception as err:
        print(f"Error calculando proyeccion mensual: {err}")


def iniciar_scheduler():
    """Arranca los cron jobs en segundo plano. Se llama una sola vez al
    iniciar el servidor (ver app/server.py)."""
    global _scheduler
    if _scheduler is not None:
        return  # ya estaba iniciado, evita duplicar los jobs

    _scheduler = BackgroundScheduler(timezone="America/Bogota")

    # Resumen semanal: todos los domingos a las 8:00 PM
    _scheduler.add_job(_job_resumen_semanal, CronTrigger(day_of_week="sun", hour=20, minute=0))

    # Alerta de presupuesto: todos los dias a las 9:00 AM (solo avisa si hay riesgo)
    _scheduler.add_job(_job_alerta_presupuesto, CronTrigger(hour=9, minute=0))

    _scheduler.start()
    print("Cron jobs activados (resumen semanal: domingos 8pm, alertas: diario 9am)")
