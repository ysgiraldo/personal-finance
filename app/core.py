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
    texto_original = texto.strip()
    texto_limpio = texto_original.lower()

    # --- Comandos de consulta general ---
    if texto_limpio in ("resumen semanal", "como voy", "cómo voy"):
        return goals.resumen_semanal()

    if texto_limpio in ("resumen mensual", "proyeccion", "proyección"):
        return goals.resumen_mensual_con_proyeccion()

    if texto_limpio in ("gastos fijos", "listar gastos fijos"):
        return goals.resumen_gastos_fijos()

    if texto_limpio in ("fondos", "mis fondos", "fondos de ahorro"):
        return goals.resumen_fondos_ahorro()

    if texto_limpio in ("balance por medio de pago", "medios de pago", "medio de pago"):
        return goals.balance_por_medio_pago()

    match_listar = re.match(r"^(?:listar|ultimos|últimos)(?:\s+(\d+))?$", texto_limpio)
    if match_listar:
        n = int(match_listar.group(1)) if match_listar.group(1) else 10
        return goals.listar_transacciones_texto(n)

    # --- Gastos fijos: registrar manualmente los pendientes de este mes ---
    if texto_limpio in ("registrar gastos fijos", "registrar gasto fijo"):
        registrados = db.registrar_gastos_fijos_pendientes()
        return goals.mensaje_registro_gastos_fijos(registrados)

    # --- Definir presupuesto general (tope total del mes, todas las categorias) ---
    match_presupuesto_general = re.match(r"^definir presupuesto general (\d+)", texto_limpio)
    if match_presupuesto_general:
        monto = match_presupuesto_general.group(1)
        db.definir_presupuesto_general(float(monto))
        return f"Presupuesto general definido: {goals.formato_pesos(float(monto))} para todo el mes."

    # --- Definir presupuesto por categoria ---
    match_presupuesto = re.match(r"^definir presupuesto (\w+) (\d+)", texto_limpio)
    if match_presupuesto:
        categoria, monto = match_presupuesto.groups()
        db.definir_presupuesto(categoria, float(monto))
        return f"Presupuesto definido: {goals.formato_pesos(float(monto))} para {categoria}."

    # --- Fondos de ahorro (con nombre): definir, ver progreso, borrar ---
    match_definir_fondo = re.match(
        r"^definir fondo (\w+)(?:\s+(\d+))?(?:\s+(\d{4}-\d{2}-\d{2}))?$", texto_limpio
    )
    if match_definir_fondo:
        nombre, monto_objetivo, fecha_objetivo = match_definir_fondo.groups()
        db.definir_fondo(
            nombre,
            float(monto_objetivo) if monto_objetivo else None,
            fecha_objetivo,
        )
        detalle = ""
        if monto_objetivo:
            detalle = f" con meta de {goals.formato_pesos(float(monto_objetivo))}"
            if fecha_objetivo:
                detalle += f" para el {fecha_objetivo}"
        return f"Fondo '{nombre}' definido{detalle}."

    match_borrar_fondo = re.match(r"^borrar fondo (\w+)", texto_limpio)
    if match_borrar_fondo:
        nombre = match_borrar_fondo.group(1)
        if db.eliminar_fondo(nombre):
            return f"Fondo '{nombre}' eliminado (el historico de lo ahorrado se conserva en tus transacciones)."
        return f"No encontre ningun fondo llamado '{nombre}'."

    match_progreso_fondo = re.match(r"^fondo (\w+)$", texto_limpio)
    if match_progreso_fondo:
        nombre = match_progreso_fondo.group(1)
        mensaje = goals.mensaje_progreso_fondo(nombre)
        return mensaje or f"No encontre ningun fondo llamado '{nombre}'. Escribe 'fondos' para ver los que tienes."

    # --- Retirar/gastar plata de un fondo de ahorro (comando explicito) ---
    match_retiro = re.match(
        r"^(?:retirar|retire|sacar|saque) (\d+)(?:\s+(?:de|del)\s+(?:fondo\s+)?(\w+))?", texto_limpio
    )
    if match_retiro:
        monto, nombre_fondo = match_retiro.groups()
        nombre_fondo = nombre_fondo or "general"
        db.agregar_transaccion(
            fecha=hoy_iso(), tipo="retiro_ahorro", monto=float(monto),
            categoria=nombre_fondo, descripcion="retiro manual",
        )
        respuesta = f"Retiro registrado: {goals.formato_pesos(float(monto))} del fondo '{nombre_fondo}'."
        progreso_texto = goals.mensaje_progreso_fondo(nombre_fondo)
        if progreso_texto:
            respuesta += f"\n{progreso_texto}"
        return respuesta

    # --- Definir / borrar gasto fijo ---
    match_gasto_fijo = re.match(r"^definir gasto fijo (\w+) (\d+)(?:\s+(\w+))?", texto_limpio)
    if match_gasto_fijo:
        nombre, monto, categoria = match_gasto_fijo.groups()
        db.definir_gasto_fijo(nombre, float(monto), categoria or nombre)
        return (
            f"Gasto fijo definido: {nombre} = {goals.formato_pesos(float(monto))}/mes.\n"
            f"No se registra solo: escribe 'registrar gastos fijos' cuando quieras contarlo como gasto real de este mes."
        )

    match_borrar_fijo = re.match(r"^borrar gasto fijo (\w+)", texto_limpio)
    if match_borrar_fijo:
        nombre = match_borrar_fijo.group(1)
        if db.eliminar_gasto_fijo(nombre):
            return f"Gasto fijo '{nombre}' eliminado."
        return f"No encontre ningun gasto fijo llamado '{nombre}'."

    # --- Borrar una transaccion (por id, o la ultima) ---
    if texto_limpio in ("borrar ultimo", "borrar ultima", "borrar último", "borrar última"):
        recientes = db.ultimas_transacciones(1)
        if not recientes:
            return "No tienes transacciones para borrar."
        db.eliminar_transaccion(recientes[0]["id"])
        return f"Transaccion #{recientes[0]['id']} eliminada."

    match_borrar = re.match(r"^borrar (\d+)$", texto_limpio)
    if match_borrar:
        id_transaccion = int(match_borrar.group(1))
        if db.eliminar_transaccion(id_transaccion):
            return f"Transaccion #{id_transaccion} eliminada."
        return f"No encontre ninguna transaccion con id #{id_transaccion}. Escribe 'listar' para ver los ids."

    # --- Editar una transaccion (monto o categoria) ---
    match_editar_monto = re.match(r"^editar (\d+) monto (\d+)$", texto_limpio)
    if match_editar_monto:
        id_transaccion, nuevo_monto = match_editar_monto.groups()
        id_transaccion = int(id_transaccion)
        if db.editar_monto_transaccion(id_transaccion, float(nuevo_monto)):
            return f"Transaccion #{id_transaccion} actualizada a {goals.formato_pesos(float(nuevo_monto))}."
        return f"No encontre ninguna transaccion con id #{id_transaccion}. Escribe 'listar' para ver los ids."

    match_editar_categoria = re.match(r"^editar (\d+) categoria (\w+)$", texto_limpio)
    if match_editar_categoria:
        id_transaccion, nueva_categoria = match_editar_categoria.groups()
        id_transaccion = int(id_transaccion)
        if db.editar_categoria_transaccion(id_transaccion, nueva_categoria):
            return f"Transaccion #{id_transaccion} actualizada a categoria '{nueva_categoria}'."
        return f"No encontre ninguna transaccion con id #{id_transaccion}. Escribe 'listar' para ver los ids."

    match_editar_fecha = re.match(r"^editar (\d+) fecha (\d{4}-\d{2}-\d{2})$", texto_limpio)
    if match_editar_fecha:
        id_transaccion, nueva_fecha = match_editar_fecha.groups()
        id_transaccion = int(id_transaccion)
        if db.editar_fecha_transaccion(id_transaccion, nueva_fecha):
            return f"Transaccion #{id_transaccion} actualizada a la fecha {nueva_fecha}."
        return f"No encontre ninguna transaccion con id #{id_transaccion}. Escribe 'listar' para ver los ids."

    # Si no es un comando conocido, lo interpretamos como un movimiento financiero
    datos = interpretar_mensaje(texto_original)

    if datos is None:
        return 'No entendi ese mensaje como un movimiento financiero. Prueba algo como "gaste 25000 en almuerzo".'

    db.agregar_transaccion(
        fecha=datos["fecha"],
        tipo=datos["tipo"],
        monto=datos["monto"],
        categoria=datos["categoria"],
        descripcion=datos["descripcion"],
        medio_pago=datos.get("medio_pago"),
    )

    fecha_es_hoy = datos["fecha"] == hoy_iso()
    sufijo_fecha = "" if fecha_es_hoy else f" (el {datos['fecha']})"

    if datos["tipo"] == "retiro_ahorro":
        respuesta = f"Registrado: retiro de {goals.formato_pesos(datos['monto'])} del fondo '{datos['categoria']}'{sufijo_fecha}."
    else:
        respuesta = f"Registrado: {goals.formato_pesos(datos['monto'])} ({datos['tipo']}) en {datos['categoria']}{sufijo_fecha}."
        if datos.get("medio_pago"):
            respuesta += f" — {goals.NOMBRES_MEDIO_PAGO.get(datos['medio_pago'], datos['medio_pago'])}"

    if datos["tipo"] == "gasto":
        progreso_texto = goals.mensaje_progreso_categoria(datos["categoria"])
        if progreso_texto:
            respuesta += f"\n{progreso_texto}"

        progreso_general_texto = goals.mensaje_progreso_general()
        if progreso_general_texto:
            respuesta += f"\n{progreso_general_texto}"

        # Si el mensaje dejaba explicito que es un gasto fijo (ej. "pago fijo
        # cada mes"), lo guardamos como definicion de gasto fijo para el futuro.
        # NO se registra automaticamente en meses siguientes: solo cuando tu
        # pidas 'registrar gastos fijos'.
        if datos.get("es_gasto_fijo") and datos.get("nombre_gasto_fijo"):
            db.definir_gasto_fijo(datos["nombre_gasto_fijo"], datos["monto"], datos["categoria"])
            respuesta += (
                f"\nLo deje guardado como gasto fijo ('{datos['nombre_gasto_fijo']}') para el futuro. "
                f"El mes que viene escribe 'registrar gastos fijos' para volver a contarlo, no se hace solo."
            )

    if datos["tipo"] in ("ahorro", "retiro_ahorro"):
        progreso_fondo_texto = goals.mensaje_progreso_fondo(datos["categoria"])
        if progreso_fondo_texto:
            respuesta += f"\n{progreso_fondo_texto}"
        else:
            respuesta += (
                f"\n(No tienes un fondo '{datos['categoria']}' definido todavia. "
                f"Escribe 'definir fondo {datos['categoria']} <monto_meta>' si quieres hacerle seguimiento.)"
            )

    return respuesta
