import calendar
from datetime import datetime

from . import db


def formato_pesos(numero):
    return "$" + f"{round(numero):,}".replace(",", ".")


def dias_en_el_mes(fecha=None):
    fecha = fecha or datetime.now()
    return calendar.monthrange(fecha.year, fecha.month)[1]


def dias_restantes_del_mes(fecha=None):
    fecha = fecha or datetime.now()
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

    hoy = datetime.now()
    promedio_diario = progreso["total_gastado"] / hoy.day
    proyeccion_cierre = promedio_diario * dias_en_el_mes(hoy)

    return {
        **progreso,
        "proyeccion_cierre": proyeccion_cierre,
        "se_superaria": proyeccion_cierre > progreso["limite"],
    }


def progreso_meta_ahorro():
    """Version simple: suma el ahorro del mes actual contra el objetivo total.
    Una v2 podria guardar una fecha_inicio para calcular con precision si vas
    adelantado o atrasado segun el tiempo transcurrido."""
    meta = db.obtener_meta_ahorro()
    if not meta:
        return None

    ahorrado = sum(t["monto"] for t in db.transacciones_del_mes(None, "ahorro"))

    return {
        "ahorrado_este_mes": ahorrado,
        "objetivo": meta["monto_objetivo"],
        "fecha_objetivo": meta["fecha_objetivo"],
        "porcentaje_este_mes": (ahorrado / meta["monto_objetivo"]) * 100,
    }


def resumen_semanal():
    transacciones = db.transacciones_de_la_semana()

    totales = {"gasto": 0, "ingreso": 0, "ahorro": 0}
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
