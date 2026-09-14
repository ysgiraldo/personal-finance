import json
import os
import re
from datetime import datetime
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Usamos Haiku porque la tarea (clasificar monto/categoria/tipo) es simple
# y no necesita el modelo mas potente/caro.
MODELO = "claude-haiku-4-5-20251001"

# Plantilla del prompt: {fecha_hoy} se rellena en cada llamada con la fecha
# real del momento, para que el modelo pueda calcular fechas relativas
# ("ayer", "el lunes pasado", "hace 3 dias") correctamente.
SYSTEM_PROMPT_TEMPLATE = """Eres un asistente que extrae datos financieros de mensajes de texto en español coloquial (Colombia).

Hoy es {fecha_hoy} ({dia_semana}).

Dado un mensaje, responde SOLO con un JSON valido (sin markdown, sin backticks, sin texto adicional) con esta forma exacta:

{{
  "tipo": "gasto" | "ingreso" | "ahorro" | "retiro_ahorro",
  "monto": <numero, sin puntos ni comas, ej. 25000>,
  "categoria": "<ver reglas abajo>",
  "descripcion": "<breve descripcion de 3-6 palabras>",
  "fecha": "<YYYY-MM-DD, ver reglas de fecha abajo>",
  "es_gasto_fijo": true | false,
  "nombre_gasto_fijo": "<solo si es_gasto_fijo es true, ver reglas abajo>",
  "medio_pago": "efectivo" | "tarjeta_credito" | "tarjeta_debito" | "transferencia" | null
}}

Reglas de "tipo":
- "gasto": la persona gasto, pago o compro algo. "categoria" es el tipo de
  gasto (ej: comida, transporte, servicios, ocio, salud, vivienda, otros).
- "ingreso": la persona recibio plata (sueldo, pago, regalo). "categoria" es
  el origen (ej: sueldo, freelance, regalo, otros).
- "ahorro": la persona esta APARTANDO/GUARDANDO plata hacia un fondo. En este
  caso "categoria" es el FONDO o destino del ahorro (ej: carro, estudio,
  emergencia, vivienda). Si no menciona un fondo especifico, usa "general".
- "retiro_ahorro": la persona esta SACANDO o USANDO plata que tenia ahorrada
  en un fondo (ej: "saque 200 mil del ahorro del carro", "use parte de mi
  fondo de emergencia"). "categoria" es el fondo del que se saca la plata,
  con las mismas reglas que en "ahorro".

Reglas de "fecha" (MUY IMPORTANTE):
- Si el mensaje menciona CUANDO paso el movimiento (ej: "ayer", "anteayer",
  "el lunes pasado", "hace 3 dias", "el 5 de septiembre", "el 5/09"),
  calcula la fecha real correspondiente usando la fecha de hoy que te di
  arriba, y devuelvela en formato YYYY-MM-DD.
- Si el mensaje NO menciona ninguna fecha ni momento pasado, usa la fecha de
  hoy tal cual te la di arriba.
- Nunca inventes una fecha futura a menos que el mensaje lo diga
  explicitamente.

Reglas de "es_gasto_fijo" y "nombre_gasto_fijo" (solo aplican cuando tipo es "gasto"):
- "es_gasto_fijo" es true SOLO si el mensaje deja explicito que es un gasto
  recurrente/mensual/fijo (ej: usa palabras como "fijo", "cada mes",
  "mensual", "recurrente", "todos los meses"). Si el mensaje no lo menciona,
  es_gasto_fijo debe ser false.
- Si es_gasto_fijo es true, "nombre_gasto_fijo" es una sola palabra corta que
  identifique este gasto recurrente (ej: "arriendo", "netflix", "gimnasio").
  Si es_gasto_fijo es false, omite este campo o dejalo como cadena vacia.

Otras reglas:
- Si no hay categoria clara para gasto/ingreso, usa "otros".
- El monto SIEMPRE debe ser un numero (no texto), interpretando "25 mil" como 25000, "2 millones" como 2000000, etc.
- "medio_pago": solo lo llenas si el mensaje lo menciona explicitamente
  (ej: "con tarjeta", "en efectivo", "le hice transferencia", "con la debito").
  Si no dice nada sobre el medio de pago, usa null. Los unicos valores
  validos son: "efectivo", "tarjeta_credito", "tarjeta_debito",
  "transferencia", o null. No inventes un medio de pago si no se menciono.
- Si el mensaje no tiene sentido financiero o no trae un monto, responde con {{"error": "no_entendido"}}."""

_DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def _system_prompt_actual():
    ahora = datetime.now()
    return SYSTEM_PROMPT_TEMPLATE.format(
        fecha_hoy=ahora.strftime("%Y-%m-%d"),
        dia_semana=_DIAS_SEMANA[ahora.weekday()],
    )


def _fecha_valida(valor):
    return bool(valor) and re.match(r"^\d{4}-\d{2}-\d{2}$", str(valor))


def interpretar_mensaje(texto):
    respuesta = client.messages.create(
        model=MODELO,
        max_tokens=300,
        system=_system_prompt_actual(),
        messages=[{"role": "user", "content": texto}],
    )

    bloque_texto = next((b.text for b in respuesta.content if b.type == "text"), None)
    if bloque_texto is None:
        raise ValueError("El modelo no devolvio texto")

    # A veces el modelo envuelve el JSON en un bloque de markdown
    # (```json ... ```) a pesar de las instrucciones. Lo limpiamos antes de parsear.
    texto_limpio = bloque_texto.strip()
    texto_limpio = re.sub(r"^```(?:json)?\s*", "", texto_limpio)
    texto_limpio = re.sub(r"\s*```$", "", texto_limpio)

    try:
        datos = json.loads(texto_limpio.strip())
    except json.JSONDecodeError as err:
        raise ValueError(f"No se pudo parsear la respuesta del modelo: {bloque_texto}") from err

    if "error" in datos:
        return None  # el mensaje no se pudo interpretar como movimiento financiero

    fecha = datos.get("fecha")
    if not _fecha_valida(fecha):
        fecha = datetime.now().strftime("%Y-%m-%d")  # respaldo si el modelo no dio una fecha valida

    return {
        "tipo": datos["tipo"],
        "monto": float(datos["monto"]),
        "categoria": str(datos["categoria"]).lower(),
        "descripcion": datos.get("descripcion", ""),
        "fecha": fecha,
        "es_gasto_fijo": bool(datos.get("es_gasto_fijo", False)),
        "nombre_gasto_fijo": str(datos.get("nombre_gasto_fijo") or "").lower().strip(),
        "medio_pago": datos.get("medio_pago") or None,
    }
