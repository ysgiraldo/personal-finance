import calendar

from . import db
from .utils import ahora


def formato_pesos(numero):
    return "$" + f"{round(numero):,}".replace(",", ".")


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
    if not meta or meta["tipo"] != "presupuesto":
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


def proyeccion_categoria(categoria):
    """Proyecta el cierre de mes para una categoria segun el ritmo actual de gasto."""
    progreso = progreso_categoria(categoria)
    if not progreso:
        return None

    hoy = ahora()
    promedio_diario = progreso["total_gastado"] / hoy.day
    proyeccion_cierre = promedio_diario * dias_en_el_mes(hoy)

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

    lineas = []
    for m in metas:
        proyeccion = proyeccion_categoria(m["categoria"])
        alerta = "⚠️ te vas a pasar" if proyeccion["se_superaria"] else "✅ vas bien"
        lineas.append(
            f"{m['categoria']}: {formato_pesos(proyeccion['total_gastado'])}/"
            f"{formato_pesos(proyeccion['limite'])} "
            f"(proyeccion: {formato_pesos(proyeccion['proyeccion_cierre'])}) {alerta}"
        )

    return "Proyeccion de cierre de mes:\n" + "\n".join(lineas)


# --- Presupuesto general (tope total del mes, sin importar la categoria) ---

def progreso_general():
    meta = db.obtener_presupuesto_general()
    if not meta:
        return None

    total_gastado = sum(t["monto"] for t in db.transacciones_del_mes(None, "gasto"))
    porcentaje = (total_gastado / meta["limite_mensual"]) * 100

    hoy = ahora()
    promedio_diario = total_gastado / hoy.day
    proyeccion_cierre = promedio_diario * dias_en_el_mes(hoy)

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
