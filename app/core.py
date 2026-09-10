import re
from datetime import datetime

from . import db
from . import goals
from .llm import interpretar_mensaje


def hoy_iso():
    return datetime.now().strftime("%Y-%m-%d")


def procesar_mensaje(texto):
    """Procesa el texto de un mensaje y devuelve la respuesta para el usuario.
    Es independiente del canal (Telegram, SMS, etc.) para poder reusarse
    desde cualquier integración."""
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