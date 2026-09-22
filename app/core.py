import re
from datetime import timedelta

from . import campos
from . import db
from . import goals
from .llm import interpretar_mensaje
from .utils import ahora, hoy_iso, sin_tildes

# --- Edicion de transacciones ---
# "editar <id|ultimo> <campo> <valor> [<campo> <valor> ...]"
# Ej: editar 24 medio efectivo | editar 24 monto 30.000 categoria comida
_RE_EDITAR = re.compile(
    r"^(?:editar|modificar|cambiar|corregir|actualizar)\s+#?(\d+|[uú]ltim[oa])\b\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_CAMPO = re.compile(
    r"\b(monto|valor|precio|categoria|categoría|fecha|descripcion|descripción|detalle|tipo|medio_pago|medio)\b",
    re.IGNORECASE,
)
_ALIAS_CAMPOS = {
    "monto": "monto", "valor": "monto", "precio": "monto",
    "categoria": "categoria", "fecha": "fecha",
    "descripcion": "descripcion", "detalle": "descripcion",
    "tipo": "tipo", "medio": "medio_pago", "medio_pago": "medio_pago",
}
_ETIQUETAS_CAMPOS = {
    "monto": "monto", "categoria": "categoria", "fecha": "fecha",
    "descripcion": "descripcion", "tipo": "tipo", "medio_pago": "medio de pago",
}

AYUDA_EDITAR = (
    "Para editar escribe: editar <id> <campo> <valor>\n"
    "Campos: monto, categoria, fecha, descripcion, tipo, medio\n"
    "Ejemplos:\n"
    "  editar 24 medio efectivo\n"
    "  editar 24 monto 30000 categoria comida\n"
    "  editar ultimo fecha ayer\n"
    "(la descripcion va al final). Usa 'listar' para ver los ids."
)


def _parsear_cambios(resto):
    """'monto 30.000 categoria comida' -> ({'monto': 30000.0, 'categoria': 'comida'}, [])
    Devuelve (cambios, errores). No toca la base de datos."""
    marcas = list(_RE_CAMPO.finditer(resto))
    if not marcas or resto[:marcas[0].start()].strip():
        return {}, ["No entendi que campo quieres cambiar."]

    cambios, errores = {}, []
    for i, marca in enumerate(marcas):
        campo = _ALIAS_CAMPOS[sin_tildes(marca.group(1).lower())]
        # La descripcion es texto libre: se lleva TODO lo que sigue (puede contener
        # palabras como "tipo" sin que las confundamos con un campo).
        fin = len(resto) if campo == "descripcion" or i + 1 == len(marcas) else marcas[i + 1].start()
        valor = resto[marca.end():fin].strip()

        if not valor:
            errores.append(f"Falta el valor de {_ETIQUETAS_CAMPOS[campo]}.")
        elif campo == "monto":
            monto = campos.parse_monto(valor)
            if monto is None:
                errores.append(f"'{valor}' no es un monto valido.")
            else:
                cambios["monto"] = monto
        elif campo == "fecha":
            fecha = campos.parse_fecha(valor)
            if fecha is None:
                errores.append(f"'{valor}' no es una fecha valida (usa AAAA-MM-DD, DD/MM, hoy o ayer).")
            else:
                cambios["fecha"] = fecha
        elif campo == "tipo":
            tipo = campos.parse_tipo(valor)
            if tipo is None:
                errores.append(f"'{valor}' no es un tipo valido (gasto, ingreso, ahorro, retiro_ahorro).")
            else:
                cambios["tipo"] = tipo
        elif campo == "medio_pago":
            valido, medio = campos.parse_medio(valor)
            if not valido:
                errores.append(f"'{valor}' no es un medio de pago valido "
                               "(efectivo, credito, debito, transferencia o ninguno).")
            else:
                cambios["medio_pago"] = medio  # None = quitar el medio de pago
        elif campo == "categoria":
            cambios["categoria"] = campos.normalizar_categoria(valor)
        else:  # descripcion
            cambios["descripcion"] = valor[:120]

        if campo == "descripcion":
            break

    return cambios, errores


def _valor_legible(campo, valor):
    if valor is None or valor == "":
        return "Sin especificar" if campo == "medio_pago" else "(vacio)"
    if campo == "monto":
        return goals.formato_pesos(valor)
    if campo == "medio_pago":
        return goals.NOMBRES_MEDIO_PAGO.get(valor, valor)
    return str(valor)


def _aplicar_edicion(id_transaccion, cambios):
    """Modifica una transaccion EXISTENTE (nunca crea una nueva) y explica que cambio."""
    resultado = db.actualizar_transaccion(id_transaccion, cambios)
    if resultado is None:
        return f"No encontre ninguna transaccion con id #{id_transaccion}. Escribe 'listar' para ver los ids."

    antes, despues = resultado
    lineas = []
    for campo in cambios:
        if antes.get(campo) != despues.get(campo):
            lineas.append(
                f"- {_ETIQUETAS_CAMPOS[campo]}: {_valor_legible(campo, antes.get(campo))}"
                f" -> {_valor_legible(campo, despues.get(campo))}"
            )
    if not lineas:
        return f"La transaccion #{id_transaccion} ya tenia esos valores, no cambie nada."

    respuesta = f"Transaccion #{id_transaccion} actualizada:\n" + "\n".join(lineas)
    if despues["tipo"] == "gasto":
        for progreso in (goals.mensaje_progreso_categoria(despues["categoria"]), goals.mensaje_progreso_general()):
            if progreso:
                respuesta += f"\n{progreso}"
    return respuesta


def procesar_mensaje(texto):
    """Procesa el texto de un mensaje y devuelve la respuesta para el usuario.
    Es independiente del canal (Telegram, SMS, etc.) para poder reusarse
    desde cualquier integración."""
    texto_original = texto.strip()
    texto_limpio = texto_original.lower()

    # --- Comandos de consulta general ---
    if texto_limpio in ("hoy", "gastos de hoy", "cuanto he gastado hoy", "cuánto he gastado hoy",
                        "cuanto llevo gastado hoy", "resumen del dia", "resumen del día"):
        return goals.resumen_dia()

    if texto_limpio in ("ayer", "gastos de ayer"):
        return goals.resumen_dia((ahora() - timedelta(days=1)).strftime("%Y-%m-%d"))

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

    # --- Editar una transaccion: cualquier campo, uno o varios a la vez ---
    # Todo mensaje que empiece con "editar <id>" se resuelve AQUI. Si algo esta mal
    # escrito se responde con ayuda, pero JAMAS se le pasa a la IA (que lo
    # registraria como una transaccion nueva y duplicada).
    match_editar = _RE_EDITAR.match(texto_original)
    if match_editar:
        referencia, resto = match_editar.groups()
        if referencia.isdigit():
            id_transaccion = int(referencia)
        else:  # "ultimo" / "ultima"
            recientes = db.ultimas_transacciones(1)
            if not recientes:
                return "No tienes transacciones para editar."
            id_transaccion = recientes[0]["id"]

        cambios, errores = _parsear_cambios(resto)
        if errores:
            return "\n".join(errores) + "\n\n" + AYUDA_EDITAR
        return _aplicar_edicion(id_transaccion, cambios)

    if re.match(r"^(?:editar|modificar|cambiar|corregir|actualizar)\s*$", texto_limpio):
        return AYUDA_EDITAR

    # Si no es un comando conocido, la IA decide que quiere la persona
    # (registrar un movimiento nuevo, editar uno existente, borrar, o preguntar).
    datos = interpretar_mensaje(texto_original, recientes=db.ultimas_transacciones(10))
    accion = datos["accion"]

    if accion == "editar":
        if datos["id"] is None:
            return (
                "No estoy seguro de cual transaccion quieres editar. "
                "Escribe 'listar' para ver los ids y luego 'editar <id> <campo> <valor>'.\n\n" + AYUDA_EDITAR
            )
        return _aplicar_edicion(datos["id"], datos["cambios"])

    if accion == "borrar":
        # Borrar es irreversible: la IA solo propone, la persona confirma con 'borrar <id>'.
        objetivo = db.obtener_transaccion(datos["id"]) if datos["id"] is not None else None
        if not objetivo:
            return "No estoy seguro de cual transaccion quieres borrar. Escribe 'listar' y luego 'borrar <id>'."
        return (
            f"Quieres borrar #{objetivo['id']} ({goals.formato_pesos(objetivo['monto'])} en "
            f"{objetivo['categoria']}, {objetivo['fecha']})? Escribe 'borrar {objetivo['id']}' para confirmar."
        )

    if accion == "consulta":
        from . import asistente
        try:
            return asistente.responder(texto_original)
        except Exception as err:
            print(f"Error del asistente: {err}")
            return (
                "No pude pensar bien la respuesta en este momento. Prueba de nuevo, o usa "
                "'hoy', 'resumen semanal', 'resumen mensual' o 'listar'."
            )

    if accion != "registrar":
        return 'No entendi ese mensaje como un movimiento financiero. Prueba algo como "gaste 25000 en almuerzo".'

    nuevo_id = db.agregar_transaccion(
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
        respuesta = f"Registrado #{nuevo_id}: retiro de {goals.formato_pesos(datos['monto'])} del fondo '{datos['categoria']}'{sufijo_fecha}."
    else:
        respuesta = f"Registrado #{nuevo_id}: {goals.formato_pesos(datos['monto'])} ({datos['tipo']}) en {datos['categoria']}{sufijo_fecha}."
        if datos.get("medio_pago"):
            respuesta += f" — {goals.NOMBRES_MEDIO_PAGO.get(datos['medio_pago'], datos['medio_pago'])}"

    if datos["tipo"] == "gasto":
        # Alertas inteligentes: solo avisan cuando ESTE gasto cruza un umbral
        # (80%/100% de un presupuesto, o un dia con gasto muy por encima de lo normal).
        # No se repiten en cada gasto, solo cuando algo realmente cambia.
        from . import analisis
        try:
            transaccion = db.obtener_transaccion(nuevo_id)
            alertas = analisis.alertas_por_gasto(analisis.cargar_contexto(), transaccion)
            if alertas:
                respuesta += "\n\n" + "\n".join(alertas)
        except Exception as err:
            print(f"No se pudieron calcular las alertas: {err}")

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
