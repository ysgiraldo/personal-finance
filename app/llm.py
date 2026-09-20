import json
import os
import re
from anthropic import Anthropic

from . import campos
from .utils import ahora, DIAS_SEMANA

# timeout y reintentos cortos: Lambda tiene un limite de tiempo y, si nos pasamos,
# Telegram reenvia el mensaje. Preferimos fallar rapido y avisar.
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), timeout=12.0, max_retries=1)

# Usamos Haiku porque la tarea (clasificar la intencion y extraer monto/categoria/tipo)
# es simple y no necesita el modelo mas potente/caro.
MODELO = "claude-haiku-4-5-20251001"

# Tokens que se reemplazan en cada llamada (no usamos .format porque el JSON
# de ejemplo esta lleno de llaves).
SYSTEM_PROMPT_TEMPLATE = """Eres el interprete de un bot de finanzas personales. Recibes mensajes en español coloquial (Colombia) y decides QUE quiere hacer la persona.

Hoy es <<FECHA>> (<<DIA>>).

Ultimas transacciones ya registradas (la primera es la mas reciente):
<<RECIENTES>>

Responde SOLO con un JSON valido (sin markdown, sin backticks, sin texto adicional). El campo "accion" define la forma del resto:

1) "registrar": la persona cuenta un movimiento NUEVO (gasto, ingreso, ahorro, retiro de ahorro).
{
  "accion": "registrar",
  "tipo": "gasto" | "ingreso" | "ahorro" | "retiro_ahorro",
  "monto": <numero, sin puntos ni comas, ej. 25000>,
  "categoria": "<ver reglas abajo>",
  "descripcion": "<breve descripcion de 3-6 palabras>",
  "fecha": "<YYYY-MM-DD, ver reglas de fecha abajo>",
  "es_gasto_fijo": true | false,
  "nombre_gasto_fijo": "<solo si es_gasto_fijo es true>",
  "medio_pago": "efectivo" | "tarjeta_credito" | "tarjeta_debito" | "transferencia" | null
}

2) "editar": la persona quiere CORREGIR o CAMBIAR una transaccion que YA esta registrada.
{
  "accion": "editar",
  "id": <numero de la transaccion, o null si no puedes saber cual>,
  "cambios": { <SOLO los campos que cambian: "monto", "categoria", "descripcion", "fecha", "tipo", "medio_pago"> }
}

3) "borrar": la persona quiere ELIMINAR una transaccion ya registrada.
{ "accion": "borrar", "id": <numero o null> }

4) "consulta": la persona hace una PREGUNTA, pide un analisis, un consejo o conversa sobre sus finanzas (ej: "¿cuanto he gastado en comida?", "¿puedo comprarme unos tenis de 300 mil?", "¿como ahorro mas?", "¿que es un CDT?"). No cuenta un movimiento nuevo.
{ "accion": "consulta" }

5) "no_entendido": el mensaje no tiene sentido financiero, o describe un movimiento pero no trae monto.
{ "accion": "no_entendido" }

COMO ELEGIR ENTRE "registrar" Y "editar" (MUY IMPORTANTE):
- Es "editar" cuando la persona corrige algo que YA registro: verbos como editar, cambiar, corregir, modificar, actualizar, arreglar; frases como "me equivoque", "en realidad fueron", "no fueron X sino Y", "ponle...", "cambiale..."; o cuando se refiere a una transaccion existente ("la ultima", "esa", "la de ayer", "el almuerzo", "la 12").
- NUNCA respondas "registrar" a un mensaje que corrige algo ya registrado: duplicaria la transaccion.
- Es "registrar" solo si describe un movimiento nuevo.

COMO ELEGIR EL "id" (para editar y borrar):
- "la ultima", "esa", "la anterior", "la que acabo de poner": usa el id de la PRIMERA de la lista.
- Si menciona descripcion, categoria, monto o fecha de una transaccion de la lista, usa el id de la que mejor coincide.
- Si hay varias posibles o ninguna coincide con seguridad, usa null. No adivines.

Ejemplos:
- "gaste 25 mil en almuerzo" -> registrar
- "el almuerzo de ayer fueron 30 mil, no 25" -> editar, id de la transaccion de almuerzo que coincide, cambios {"monto": 30000}
- "cambiale la categoria a transporte" -> editar, id de la primera de la lista, cambios {"categoria": "transporte"}
- "borra la de los 25 mil" -> borrar, id de la que tiene monto 25000
- "¿en que me gasto mas la plata?" -> consulta

Reglas de "tipo" (para registrar y editar):
- "gasto": la persona gasto, pago o compro algo. "categoria" es el tipo de gasto (ej: comida, transporte, servicios, ocio, salud, vivienda, otros).
- "ingreso": la persona recibio plata (sueldo, pago, regalo). "categoria" es el origen (ej: sueldo, freelance, regalo, otros).
- "ahorro": la persona esta APARTANDO/GUARDANDO plata hacia un fondo. "categoria" es el FONDO o destino del ahorro (ej: carro, estudio, emergencia, vivienda). Si no menciona un fondo especifico, usa "general".
- "retiro_ahorro": la persona esta SACANDO o USANDO plata que tenia ahorrada en un fondo. "categoria" es el fondo del que se saca la plata, con las mismas reglas que en "ahorro".

Reglas de "fecha" (MUY IMPORTANTE):
- Si el mensaje menciona CUANDO paso el movimiento (ej: "ayer", "anteayer", "el lunes pasado", "hace 3 dias", "el 5 de septiembre", "el 5/09"), calcula la fecha real usando la fecha de hoy que te di arriba, en formato YYYY-MM-DD.
- Si al REGISTRAR el mensaje no menciona ninguna fecha, usa la fecha de hoy tal cual.
- Nunca inventes una fecha futura a menos que el mensaje lo diga explicitamente.

Reglas de "es_gasto_fijo" y "nombre_gasto_fijo" (solo para registrar un gasto):
- "es_gasto_fijo" es true SOLO si el mensaje deja explicito que es un gasto recurrente/mensual/fijo (usa palabras como "fijo", "cada mes", "mensual", "recurrente", "todos los meses"). Si no lo menciona, es false.
- Si es true, "nombre_gasto_fijo" es una sola palabra corta que identifique ese gasto (ej: "arriendo", "netflix", "gimnasio"). Si es false, omite el campo.

Otras reglas:
- Si no hay categoria clara para gasto/ingreso, usa "otros".
- El monto SIEMPRE es un numero (no texto): "25 mil" es 25000, "2 millones" es 2000000.
- "medio_pago": solo lo llenas si el mensaje lo menciona explicitamente (ej: "con tarjeta de credito", "en efectivo", "le hice transferencia", "con la debito"). Si no dice nada, usa null.
- Al EDITAR incluye unicamente los campos que la persona quiere cambiar."""


def _system_prompt_actual(recientes):
    ahora_local = ahora()
    return (
        SYSTEM_PROMPT_TEMPLATE
        .replace("<<FECHA>>", ahora_local.strftime("%Y-%m-%d"))
        .replace("<<DIA>>", DIAS_SEMANA[ahora_local.weekday()])
        .replace("<<RECIENTES>>", _formatear_recientes(recientes))
    )


def _formatear_recientes(recientes):
    if not recientes:
        return "(todavia no hay ninguna)"
    lineas = []
    for t in recientes:
        linea = f"#{t['id']} [{t['fecha']}] {t['tipo']} {int(t['monto'])} {t['categoria']}"
        if t.get("descripcion"):
            linea += f" ({t['descripcion']})"
        if t.get("medio_pago"):
            linea += f" - {t['medio_pago']}"
        lineas.append(linea)
    return "\n".join(lineas)


def _extraer_json(texto):
    """Saca el objeto JSON de la respuesta aunque venga envuelto en ```json o con texto alrededor."""
    coincidencia = re.search(r"\{.*\}", texto, re.DOTALL)
    if not coincidencia:
        raise ValueError(f"El modelo no devolvio JSON: {texto}")
    try:
        return json.loads(coincidencia.group(0))
    except json.JSONDecodeError as err:
        raise ValueError(f"No se pudo parsear la respuesta del modelo: {texto}") from err


def _id_o_none(valor):
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _normalizar_registro(datos):
    tipo = campos.parse_tipo(datos.get("tipo", ""))
    monto = campos.parse_monto(datos.get("monto"))
    if not tipo or not monto:
        return {"accion": "no_entendido"}

    fecha = campos.parse_fecha(datos.get("fecha") or "") or ahora().strftime("%Y-%m-%d")
    valido, medio_pago = campos.parse_medio(datos.get("medio_pago") or "ninguno")

    return {
        "accion": "registrar",
        "tipo": tipo,
        "monto": monto,
        "categoria": campos.normalizar_categoria(datos.get("categoria") or "") or "otros",
        "descripcion": str(datos.get("descripcion") or "").strip(),
        "fecha": fecha,
        "es_gasto_fijo": bool(datos.get("es_gasto_fijo", False)),
        "nombre_gasto_fijo": str(datos.get("nombre_gasto_fijo") or "").lower().strip(),
        "medio_pago": medio_pago if valido else None,
    }


def interpretar_mensaje(texto, recientes=None):
    """Clasifica un mensaje libre. Devuelve SIEMPRE un dict con la clave "accion":

      {"accion": "registrar", "tipo", "monto", "categoria", "descripcion", "fecha", ...}
      {"accion": "editar", "id": int|None, "cambios": {...}}
      {"accion": "borrar", "id": int|None}
      {"accion": "consulta"}
      {"accion": "no_entendido"}

    `recientes` son las ultimas transacciones (para que el modelo sepa a cual se
    refiere la persona cuando dice "la ultima" o "el almuerzo de ayer").
    """
    respuesta = client.messages.create(
        model=MODELO,
        max_tokens=300,
        system=_system_prompt_actual(recientes),
        messages=[{"role": "user", "content": texto}],
    )

    bloque_texto = next((b.text for b in respuesta.content if b.type == "text"), None)
    if bloque_texto is None:
        raise ValueError("El modelo no devolvio texto")

    datos = _extraer_json(bloque_texto)

    # Tolerancia: si el modelo olvida "accion", lo deducimos de la forma del JSON.
    accion = datos.get("accion")
    if not accion:
        accion = "no_entendido" if "error" in datos else "registrar"

    if accion == "registrar":
        return _normalizar_registro(datos)

    if accion == "editar":
        cambios = campos.limpiar_cambios(datos.get("cambios"))
        if not cambios:
            return {"accion": "no_entendido"}
        return {"accion": "editar", "id": _id_o_none(datos.get("id")), "cambios": cambios}

    if accion == "borrar":
        return {"accion": "borrar", "id": _id_o_none(datos.get("id"))}

    if accion == "consulta":
        return {"accion": "consulta"}

    return {"accion": "no_entendido"}
