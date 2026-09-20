"""Utilidades compartidas: hora local del usuario y formato de dinero.

Por que existe: AWS Lambda corre en UTC. Colombia es UTC-5, asi que con
datetime.now() a partir de las 7:00 PM hora Bogota el bot creia que ya era
"manana" (registraba con la fecha equivocada y el resumen del dia salia vacio).
Todo el codigo debe usar ahora() en vez de datetime.now().
"""
import os
import unicodedata
from datetime import datetime, timedelta, timezone

_NOMBRE_ZONA = os.environ.get("ZONA_HORARIA", "America/Bogota")

try:
    from zoneinfo import ZoneInfo

    _ZONA = ZoneInfo(_NOMBRE_ZONA)
except Exception:
    # Si el runtime no trae la base de datos de zonas horarias, usamos el
    # desfase fijo de Colombia (UTC-5, sin horario de verano).
    _ZONA = timezone(timedelta(hours=-5))

DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def ahora():
    """Fecha y hora actual en la zona del usuario, como datetime 'ingenuo'
    (sin tzinfo) para poder compararlo con el resto del codigo."""
    return datetime.now(_ZONA).replace(tzinfo=None)


def hoy_iso():
    return ahora().strftime("%Y-%m-%d")


def formato_pesos(numero):
    return "$" + f"{round(numero):,}".replace(",", ".")


def sin_tildes(texto):
    """'Categoría' -> 'Categoria'. Sirve para reconocer comandos sin importar
    si la persona escribio con o sin tildes (pero conservando la ñ como n)."""
    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn")
