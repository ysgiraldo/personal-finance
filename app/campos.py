"""Validacion y normalizacion de los campos de una transaccion.

La usan tanto los comandos manuales ("editar 5 monto 30.000") como la
interpretacion con IA, para que ambos caminos apliquen EXACTAMENTE las mismas
reglas y nunca se guarde un dato invalido.
"""
import re
from datetime import datetime, timedelta

from .utils import ahora, sin_tildes

TIPOS_VALIDOS = ("gasto", "ingreso", "ahorro", "retiro_ahorro")
MEDIOS_VALIDOS = ("efectivo", "tarjeta_credito", "tarjeta_debito", "transferencia")

_MULTIPLICADORES = {"k": 1_000, "mil": 1_000, "m": 1_000_000, "millon": 1_000_000, "millones": 1_000_000}


def parse_monto(valor):
    """'30000', '30.000', '$30.000', '30 mil', '30k', '2,5 millones' -> float.
    Devuelve None si no es un monto valido (o si es <= 0)."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        monto = float(valor)
    else:
        texto = sin_tildes(str(valor).strip().lower()).replace("$", "").replace("pesos", "").strip()
        coincidencia = re.match(r"^(\d[\d.,]*)\s*(k|mil|millon|millones|m)?$", texto)
        if not coincidencia:
            return None
        numero, sufijo = coincidencia.groups()
        try:
            if sufijo:  # "2,5 millones": aqui la coma es decimal
                monto = float(numero.replace(",", ".")) * _MULTIPLICADORES[sufijo]
            else:       # "30.000" / "1,500,000": los separadores son de miles
                monto = float(re.sub(r"[.,]", "", numero))
        except ValueError:
            return None
    return monto if 0 < monto < 1e12 else None


def parse_fecha(valor, hoy=None):
    """'2026-09-18', '18/09/2026', '18/09', 'hoy', 'ayer', 'anteayer' -> 'YYYY-MM-DD'.
    Devuelve None si no es una fecha real (ej. 2026-02-31)."""
    hoy = hoy or ahora()
    texto = sin_tildes(str(valor).strip().lower())
    relativas = {"hoy": 0, "ayer": 1, "anteayer": 2, "antier": 2}
    if texto in relativas:
        return (hoy - timedelta(days=relativas[texto])).strftime("%Y-%m-%d")

    corta = re.match(r"^(\d{1,2})/(\d{1,2})$", texto)  # 18/09 -> este año
    if corta:
        texto = f"{corta.group(1)}/{corta.group(2)}/{hoy.year}"

    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_tipo(valor):
    texto = sin_tildes(str(valor).strip().lower()).replace(" ", "_")
    if texto == "retiro":
        texto = "retiro_ahorro"
    return texto if texto in TIPOS_VALIDOS else None


def parse_medio(valor):
    """Devuelve (es_valido, medio). (True, None) significa 'quitar el medio de pago'."""
    texto = sin_tildes(str(valor).strip().lower())
    if any(p in texto for p in ("ningun", "quitar", "nada", "sin ")):
        return True, None
    if "credito" in texto:
        return True, "tarjeta_credito"
    if "debito" in texto:
        return True, "tarjeta_debito"
    if "efectivo" in texto:
        return True, "efectivo"
    if "transfer" in texto:
        return True, "transferencia"
    return False, None


def normalizar_categoria(valor):
    texto = re.sub(r"\s+", "_", str(valor).strip().lower())[:40]
    return texto or None


def limpiar_cambios(crudo):
    """Filtra y valida un dict de cambios propuesto por la IA. Descarta lo invalido.
    (La IA no puede BORRAR el medio de pago: eso solo se hace con el comando manual.)"""
    limpios = {}
    if not isinstance(crudo, dict):
        return limpios

    if crudo.get("monto") is not None:
        monto = parse_monto(crudo["monto"])
        if monto:
            limpios["monto"] = monto
    if crudo.get("fecha"):
        fecha = parse_fecha(crudo["fecha"])
        if fecha:
            limpios["fecha"] = fecha
    if crudo.get("categoria"):
        categoria = normalizar_categoria(crudo["categoria"])
        if categoria:
            limpios["categoria"] = categoria
    if crudo.get("descripcion"):
        descripcion = str(crudo["descripcion"]).strip()[:120]
        if descripcion:
            limpios["descripcion"] = descripcion
    if crudo.get("tipo"):
        tipo = parse_tipo(crudo["tipo"])
        if tipo:
            limpios["tipo"] = tipo
    if crudo.get("medio_pago"):
        valido, medio = parse_medio(crudo["medio_pago"])
        if valido and medio:
            limpios["medio_pago"] = medio
    return limpios
