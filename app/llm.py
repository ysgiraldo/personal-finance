import json
import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Usamos Haiku porque la tarea (clasificar monto/categoria/tipo) es simple
# y no necesita el modelo mas potente/caro.
MODELO = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """Eres un asistente que extrae datos financieros de mensajes de texto en español coloquial (Colombia).

Dado un mensaje, responde SOLO con un JSON valido (sin markdown, sin backticks, sin texto adicional) con esta forma exacta:

{
  "tipo": "gasto" | "ingreso" | "ahorro",
  "monto": <numero, sin puntos ni comas, ej. 25000>,
  "categoria": "<una palabra o dos, ej: comida, transporte, servicios, ocio, salud, sueldo, otros>",
  "descripcion": "<breve descripcion de 3-6 palabras>"
}

Reglas:
- Si el mensaje habla de gastar, pagar, comprar -> tipo "gasto".
- Si el mensaje habla de recibir plata, sueldo, pago que le hicieron -> tipo "ingreso".
- Si el mensaje habla de ahorrar o apartar plata -> tipo "ahorro".
- Si no hay categoria clara, usa "otros".
- El monto SIEMPRE debe ser un numero (no texto), interpretando "25 mil" como 25000, "2 millones" como 2000000, etc.
- Si el mensaje no tiene sentido financiero o no trae un monto, responde con {"error": "no_entendido"}."""


def interpretar_mensaje(texto):
    respuesta = client.messages.create(
        model=MODELO,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": texto}],
    )

    bloque_texto = next((b.text for b in respuesta.content if b.type == "text"), None)
    if bloque_texto is None:
        raise ValueError("El modelo no devolvio texto")

    try:
        datos = json.loads(bloque_texto.strip())
    except json.JSONDecodeError as err:
        raise ValueError(f"No se pudo parsear la respuesta del modelo: {bloque_texto}") from err

    if "error" in datos:
        return None  # el mensaje no se pudo interpretar como movimiento financiero

    return {
        "tipo": datos["tipo"],
        "monto": float(datos["monto"]),
        "categoria": str(datos["categoria"]).lower(),
        "descripcion": datos.get("descripcion", ""),
    }
