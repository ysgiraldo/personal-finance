import calendar
from datetime import datetime, timedelta

from . import analisis
from . import db
from .utils import ahora, formato_pesos, DIAS_SEMANA


def dias_en_el_mes(fecha=None):
    fecha = fecha or ahora()
    return calendar.monthrange(fecha.year, fecha.month)[1]


def dias_restantes_del_mes(fecha=None):
    fecha = fecha or ahora()
    return dias_en_el_mes(fecha) - fecha.day + 1


def progreso_categoria(categoria):
    """Devuelve el progreso de gasto de una categoria con presupuesto definido,
    o None si esa categoria no tiene presupuesto configurado."""
    meta = db.obtener_meta(categoria)
    if not meta or meta["tipo"] != "presupuesto" or not meta["limite_mensual"]:
        return None

    transacciones = db.transacciones_del_mes(categoria, "gasto")
    total_gastado = sum(t["monto"] for t in transacciones)
    porcentaje = (total_gastado / meta["limite_mensual"]) * 100

    return {
        "categoria": categoria,
        "total_gastado": total_gastado,
        "limite": meta["limite_mensual"],
        "porcentaje": porcentaje,
        "restante": meta["limite_mensual"] - total_gastado,
    }


def mensaje_progreso_categoria(categoria):
    progreso = progreso_categoria(categoria)
    if not progreso:
        return None

    return (
        f"Llevas {formato_pesos(progreso['total_gastado'])} de "
        f"{formato_pesos(progreso['limite'])} en {categoria} este mes "
        f"({progreso['porcentaje']:.0f}%)."
    )


def proyeccion_categoria(categoria, ctx=None):
    """Proyecta el cierre de mes para una categoria segun el ritmo actual de gasto
    (lo fijo se cuenta una sola vez; solo lo variable sigue el ritmo diario)."""
    progreso = progreso_categoria(categoria)
    if not progreso:
        return None

    ctx = ctx or analisis.cargar_contexto()
    proyeccion_cierre = analisis.proyeccion_cierre_mes(ctx, categoria)

    return {
        **progreso,
        "proyeccion_cierre": proyeccion_cierre,
        "se_superaria": proyeccion_cierre > progreso["limite"],
    }


def progreso_fondo(nombre):
    """Progreso de un fondo de ahorro especifico: cuanto se ha acumulado en
    total (historico, no solo el mes actual) frente a su meta (si tiene)."""
    fondo = db.obtener_fondo(nombre)
    if not fondo:
        return None

    ahorrado = db.total_ahorrado_fondo(nombre)

    resultado = {
        "nombre": nombre,
        "ahorrado": ahorrado,
        "objetivo": fondo["monto_objetivo"],
        "fecha_objetivo": fondo["fecha_objetivo"],
    }

    if fondo["monto_objetivo"]:
        resultado["porcentaje"] = (ahorrado / fondo["monto_objetivo"]) * 100

    return resultado


def mensaje_progreso_fondo(nombre):
    progreso = progreso_fondo(nombre)
    if not progreso:
        return None

    if progreso["objetivo"]:
        texto = (
            f"Fondo '{nombre}': {formato_pesos(progreso['ahorrado'])} de "
            f"{formato_pesos(progreso['objetivo'])} ({progreso['porcentaje']:.0f}%)"
        )
        if progreso["fecha_objetivo"]:
            texto += f", meta para el {progreso['fecha_objetivo']}"
        return texto + "."

    return f"Fondo '{nombre}': {formato_pesos(progreso['ahorrado'])} ahorrado (sin meta definida)."


def resumen_fondos_ahorro():
    fondos = db.obtener_todos_los_fondos()

    if not fondos:
        return 'Aun no has definido fondos de ahorro. Escribe "definir fondo <nombre> <monto_meta opcional> <fecha opcional>" para empezar.'

    lineas = []
    total_ahorrado_general = 0
    for f in fondos:
        ahorrado = db.total_ahorrado_fondo(f["nombre"])
        total_ahorrado_general += ahorrado

        if f["monto_objetivo"]:
            porcentaje = (ahorrado / f["monto_objetivo"]) * 100
            linea = f"- {f['nombre']}: {formato_pesos(ahorrado)} de {formato_pesos(f['monto_objetivo'])} ({porcentaje:.0f}%)"
            if f["fecha_objetivo"]:
                linea += f" — meta {f['fecha_objetivo']}"
        else:
            linea = f"- {f['nombre']}: {formato_pesos(ahorrado)} (sin meta definida)"

        lineas.append(linea)

    return (
        "Fondos de ahorro:\n"
        + "\n".join(lineas)
        + f"\n\nTotal ahorrado en todos los fondos: {formato_pesos(total_ahorrado_general)}"
    )


def resumen_semanal():
    transacciones = db.transacciones_de_la_semana()

    totales = {"gasto": 0, "ingreso": 0, "ahorro": 0, "retiro_ahorro": 0}
    por_categoria = {}

    for t in transacciones:
        totales[t["tipo"]] = totales.get(t["tipo"], 0) + t["monto"]
        if t["tipo"] == "gasto":
            por_categoria[t["categoria"]] = por_categoria.get(t["categoria"], 0) + t["monto"]

    texto = (
        f"Resumen semanal:\n"
        f"Gastos: {formato_pesos(totales['gasto'])}\n"
        f"Ingresos: {formato_pesos(totales['ingreso'])}\n"
        f"Ahorro: {formato_pesos(totales['ahorro'])}"
    )

    if totales["retiro_ahorro"] > 0:
        texto += f"\nRetiros de ahorro: {formato_pesos(totales['retiro_ahorro'])}"

    if por_categoria:
        categoria_top = max(por_categoria.items(), key=lambda item: item[1])
        texto += f"\nTu categoria con mas gasto fue {categoria_top[0]} ({formato_pesos(categoria_top[1])})."

    return texto


def resumen_mensual_con_proyeccion():
    metas = [m for m in db.obtener_todas_las_metas() if m["tipo"] == "presupuesto"]

    if not metas:
        return 'Aun no has definido presupuestos por categoria. Escribe "definir presupuesto <categoria> <monto>" para empezar.'

    ctx = analisis.cargar_contexto()
    lineas = []
    for m in metas:
        proyeccion = proyeccion_categoria(m["categoria"], ctx)
        if not proyeccion:  # presupuesto en 0: no hay nada que proyectar
            continue
        alerta = "⚠️ te vas a pasar" if proyeccion["se_superaria"] else "✅ vas bien"
        lineas.append(
            f"{m['categoria']}: {formato_pesos(proyeccion['total_gastado'])}/"
            f"{formato_pesos(proyeccion['limite'])} "
            f"(proyeccion: {formato_pesos(proyeccion['proyeccion_cierre'])}) {alerta}"
        )

    return "Proyeccion de cierre de mes:\n" + "\n".join(lineas)


# --- Presupuesto general (tope total del mes, sin importar la categoria) ---

def progreso_general(ctx=None):
    meta = db.obtener_presupuesto_general()
    if not meta or not meta["limite_mensual"]:
        return None

    total_gastado = sum(t["monto"] for t in db.transacciones_del_mes(None, "gasto"))
    porcentaje = (total_gastado / meta["limite_mensual"]) * 100

    ctx = ctx or analisis.cargar_contexto()
    proyeccion_cierre = analisis.proyeccion_cierre_mes(ctx)

    return {
        "total_gastado": total_gastado,
        "limite": meta["limite_mensual"],
        "porcentaje": porcentaje,
        "proyeccion_cierre": proyeccion_cierre,
        "se_superaria": proyeccion_cierre > meta["limite_mensual"],
    }


def mensaje_progreso_general():
    progreso = progreso_general()
    if not progreso:
        return None

    return (
        f"Presupuesto general: {formato_pesos(progreso['total_gastado'])} de "
        f"{formato_pesos(progreso['limite'])} este mes ({progreso['porcentaje']:.0f}%)."
    )


# --- Ingresos y gastos fijos ---

def total_ingresos_mes():
    return sum(t["monto"] for t in db.transacciones_del_mes(None, "ingreso"))


def resumen_gastos_fijos():
    fijos = db.obtener_gastos_fijos()

    if not fijos:
        return 'Aun no has definido gastos fijos. Escribe "definir gasto fijo <nombre> <monto>" para empezar.'

    total_fijos = sum(f["monto_mensual"] for f in fijos)
    lineas = [f"- {f['nombre']}: {formato_pesos(f['monto_mensual'])}" for f in fijos]

    texto = "Gastos fijos:\n" + "\n".join(lineas) + f"\nTotal: {formato_pesos(total_fijos)}"

    ingresos = total_ingresos_mes()
    if ingresos > 0:
        porcentaje = (total_fijos / ingresos) * 100
        texto += (
            f"\n\nEsto representa el {porcentaje:.0f}% de tus ingresos registrados "
            f"este mes ({formato_pesos(ingresos)})."
        )
    else:
        texto += "\n\n(Aun no has registrado ingresos este mes para calcular el porcentaje.)"

    return texto


# --- Balance por medio de pago (efectivo, tarjeta credito, debito, transferencia) ---

NOMBRES_MEDIO_PAGO = {
    "efectivo": "Efectivo",
    "tarjeta_credito": "Tarjeta de credito",
    "tarjeta_debito": "Tarjeta de debito",
    "transferencia": "Transferencia",
    None: "Sin especificar",
}


def balance_por_medio_pago():
    """Balance de gastos del mes actual agrupado por medio de pago."""
    transacciones = db.transacciones_del_mes(None, "gasto")

    if not transacciones:
        return "No tienes gastos registrados este mes todavia."

    totales = {}
    for t in transacciones:
        medio = t["medio_pago"] if "medio_pago" in t.keys() else None
        totales[medio] = totales.get(medio, 0) + t["monto"]

    total_general = sum(totales.values())

    lineas = []
    for medio, monto in sorted(totales.items(), key=lambda item: item[1], reverse=True):
        nombre = NOMBRES_MEDIO_PAGO.get(medio, medio)
        porcentaje = (monto / total_general) * 100
        lineas.append(f"- {nombre}: {formato_pesos(monto)} ({porcentaje:.0f}%)")

    texto = "Balance de gastos por medio de pago este mes:\n" + "\n".join(lineas)
    texto += f"\nTotal: {formato_pesos(total_general)}"

    if totales.get(None, 0) > 0:
        texto += "\n\n(Tip: si mencionas 'con tarjeta', 'en efectivo', etc. al registrar, se clasifica solo.)"

    return texto

# --- Listado de transacciones (para poder editar/borrar por id) ---

def listar_transacciones_texto(n=10):
    transacciones = db.ultimas_transacciones(n)

    if not transacciones:
        return "Todavia no tienes transacciones registradas."

    lineas = []
    for t in transacciones:
        linea = (
            f"#{t['id']} [{t['fecha']}] {t['tipo']}: {formato_pesos(t['monto'])} "
            f"en {t['categoria']} ({t['descripcion']})"
        )
        medio = t["medio_pago"] if "medio_pago" in t.keys() else None
        if medio:
            linea += f" — {NOMBRES_MEDIO_PAGO.get(medio, medio)}"
        lineas.append(linea)

    return f"Ultimas {len(transacciones)} transacciones:\n" + "\n".join(lineas)


def mensaje_registro_gastos_fijos(gastos_fijos_registrados):
    if not gastos_fijos_registrados:
        return "No hay gastos fijos pendientes de registrar este mes (o no tienes ninguno definido)."

    lineas = [f"- {g['nombre']}: {formato_pesos(g['monto_mensual'])}" for g in gastos_fijos_registrados]
    total = sum(g["monto_mensual"] for g in gastos_fijos_registrados)

    return (
        f"Registre {len(gastos_fijos_registrados)} gasto(s) fijo(s) de este mes:\n"
        + "\n".join(lineas)
        + f"\nTotal: {formato_pesos(total)}"
    )


# --- Resumen del dia ---

def _etiqueta_dia(fecha_iso, ctx):
    fecha = datetime.strptime(fecha_iso, "%Y-%m-%d")
    nombre = DIAS_SEMANA[fecha.weekday()]
    ayer = (ctx["hoy"] - timedelta(days=1)).strftime("%Y-%m-%d")
    if fecha_iso == ctx["hoy_iso"]:
        return f"Hoy ({nombre} {fecha_iso})"
    if fecha_iso == ayer:
        return f"Ayer ({nombre} {fecha_iso})"
    return f"{nombre} {fecha_iso}"


def resumen_dia(fecha_iso=None, ctx=None):
    """Cuanto se gasto en un dia (por defecto hoy), con contexto: comparacion
    contra tu promedio diario y cuanto puedes gastar por dia el resto del mes."""
    ctx = ctx or analisis.cargar_contexto()
    fecha_iso = fecha_iso or ctx["hoy_iso"]
    es_hoy = fecha_iso == ctx["hoy_iso"]

    del_dia = [t for t in ctx["todas"] if t["fecha"] == fecha_iso]
    encabezado = f"📅 {_etiqueta_dia(fecha_iso, ctx)}"
    if not del_dia:
        return encabezado + "\n" + ("Hoy no has registrado movimientos." if es_hoy
                                     else "No hay movimientos registrados ese dia.")

    gastos = [t for t in del_dia if t["tipo"] == "gasto"]
    total_gastos = sum(t["monto"] for t in gastos)

    lineas = [encabezado]
    if gastos:
        lineas.append(f"Gastos: {formato_pesos(total_gastos)} ({len(gastos)} movimiento(s))")
        for t in gastos[:15]:
            detalle = f" — {t['descripcion']}" if t.get("descripcion") else ""
            lineas.append(f"  #{t['id']} {t['categoria']} {formato_pesos(t['monto'])}{detalle}")
        if len(gastos) > 15:
            lineas.append(f"  ...y {len(gastos) - 15} mas")

        por_categoria = {}
        for t in gastos:
            por_categoria[t["categoria"]] = por_categoria.get(t["categoria"], 0) + t["monto"]
        if len(por_categoria) > 1:
            top = sorted(por_categoria.items(), key=lambda kv: kv[1], reverse=True)
            lineas.append("Por categoria: " + ", ".join(f"{c} {formato_pesos(m)}" for c, m in top))
    else:
        lineas.append("Gastos: $0")

    for tipo, etiqueta in (("ingreso", "Ingresos"), ("ahorro", "Ahorro"), ("retiro_ahorro", "Retiros de ahorro")):
        suma = analisis.total(del_dia, tipo)
        if suma > 0:
            lineas.append(f"{etiqueta}: {formato_pesos(suma)}")

    if es_hoy:
        lineas.append("")
        base = analisis.promedio_diario_variable(ctx)
        if gastos and base:
            variable_hoy = analisis.gasto_variable_del_dia(ctx, fecha_iso)
            lineas.append(
                f"Tu promedio diario (ultimos 30 dias, sin gastos fijos) es {formato_pesos(base)}; "
                f"hoy vas en {formato_pesos(variable_hoy)} ({variable_hoy / base * 100:.0f}%)."
            )

        gasto_mes = analisis.total(ctx["del_mes"], "gasto")
        lineas.append(f"En lo que va del mes: {formato_pesos(gasto_mes)} en gastos.")

        disponible = analisis.disponible_mes(ctx)
        if disponible:
            if disponible["libre"] >= 0:
                texto = (
                    f"Presupuesto general: te quedan {formato_pesos(disponible['libre'])} para "
                    f"{disponible['dias_restantes']} dias (~{formato_pesos(disponible['por_dia'])} por dia)"
                )
                if disponible["fijos_pendientes"] > 0:
                    texto += f", ya descontando {formato_pesos(disponible['fijos_pendientes'])} de gastos fijos por registrar"
                lineas.append(texto + ".")
            else:
                lineas.append(f"Ya superaste tu presupuesto general por {formato_pesos(-disponible['libre'])}.")

    return "\n".join(lineas)


def resumen_diario_noche():
    """Version para el aviso programado de la noche. Si no registraste nada,
    te lo recuerda (un bot de registro manual vale tanto como tu constancia)."""
    ctx = analisis.cargar_contexto()
    texto = resumen_dia(ctx=ctx)
    if not any(t["fecha"] == ctx["hoy_iso"] for t in ctx["todas"]):
        texto += '\n¿Se te quedo algo por contar? Escribeme, por ejemplo: "gaste 15000 en almuerzo".'
    return texto
