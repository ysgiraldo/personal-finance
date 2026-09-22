"""Analisis financiero determinista (sin IA): metricas, proyecciones y alertas.

Todo se calcula en memoria a partir de UN solo snapshot (cargar_contexto), que
lee la tabla de DynamoDB una vez. Asi el bot no repite consultas y las mismas
cifras alimentan los avisos, el resumen del dia y el asistente conversacional.

Idea central: los gastos FIJOS (arriendo, suscripciones...) se pagan una vez al
mes, no "siguen un ritmo diario". Si se proyectan como si fueran gasto diario
(promedio x 30) se obtienen cierres de mes absurdos y falsas alarmas. Por eso
aqui se separa lo fijo de lo variable.
"""
import calendar
import math
from datetime import datetime, timedelta

from . import db
from .utils import ahora, formato_pesos as pesos

# --- Parametros de las reglas (ajustalos a tu gusto) ---
UMBRAL_AVISO = 0.8          # avisar al llegar al 80% de un presupuesto
MIN_DIA_PROYECCION = 7      # antes del dia 7 hay muy pocos datos para proyectar
FACTOR_DIA_ATIPICO = 2.0    # un dia "atipico" gasta mas de 2x el promedio diario
MIN_DIAS_HISTORIAL = 7      # dias de historial minimos para hablar de "promedio"
UMBRAL_VS_MES_PASADO = 1.25 # avisar si vas 25% por encima del mes pasado
MAX_ALERTAS = 5


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def _categoria_fijo(fijo):
    return (fijo.get("categoria") or fijo["nombre"]).lower()


def cargar_contexto(hoy=None):
    """Lee todo lo necesario de la base de datos y lo deja listo para calcular.
    `hoy` se puede pasar para pruebas."""
    hoy = hoy or ahora()
    mes = hoy.strftime("%Y-%m")
    mes_anterior = (hoy.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    todas = db.todas_las_transacciones()
    metas = db.obtener_todas_las_metas()
    fijos = db.obtener_gastos_fijos()

    nombres_fijos = set()
    for f in fijos:
        nombres_fijos.add(f["nombre"].lower())
        nombres_fijos.add(_categoria_fijo(f))

    return {
        "hoy": hoy,
        "hoy_iso": hoy.strftime("%Y-%m-%d"),
        "dia": hoy.day,
        "dias_mes": calendar.monthrange(hoy.year, hoy.month)[1],
        "mes": mes,
        "mes_anterior": mes_anterior,
        "todas": todas,
        "del_mes": [t for t in todas if t["fecha"].startswith(mes)],
        "del_mes_anterior": [t for t in todas if t["fecha"].startswith(mes_anterior)],
        "fijos": fijos,
        "presupuestos": {m["categoria"]: m["limite_mensual"] for m in metas if m["tipo"] == "presupuesto"},
        "presupuesto_general": next(
            (m["limite_mensual"] for m in metas if m["tipo"] == "presupuesto_general"), None),
        "fondos": db.obtener_todos_los_fondos(),
        "_nombres_fijos": nombres_fijos,
    }


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------

def dias_restantes(ctx):
    """Dias que quedan del mes contando hoy."""
    return ctx["dias_mes"] - ctx["dia"] + 1


def total(transacciones, tipo):
    return sum(t["monto"] for t in transacciones if t["tipo"] == tipo)


def es_fijo(t, ctx):
    """Un gasto es 'fijo' si su categoria coincide con un gasto fijo definido
    o si fue creado con 'registrar gastos fijos'."""
    return (
        (t.get("categoria") or "").lower() in ctx["_nombres_fijos"]
        or "(gasto fijo)" in (t.get("descripcion") or "")
    )


def gastos_del_mes(ctx, categoria=None):
    return [t for t in ctx["del_mes"]
            if t["tipo"] == "gasto" and (categoria is None or t["categoria"] == categoria)]


def gasto_variable_del_dia(ctx, fecha_iso):
    return sum(t["monto"] for t in ctx["todas"]
               if t["tipo"] == "gasto" and t["fecha"] == fecha_iso and not es_fijo(t, ctx))


def promedio_diario_variable(ctx, ventana=30):
    """Gasto variable diario promedio de los ultimos `ventana` dias SIN contar hoy.
    Devuelve None si aun no hay suficiente historial para que el numero sea confiable."""
    fechas = [t["fecha"] for t in ctx["todas"] if t["tipo"] == "gasto"]
    if not fechas:
        return None
    try:
        primera = datetime.strptime(min(fechas), "%Y-%m-%d")
    except ValueError:
        return None

    hoy = ctx["hoy"].replace(hour=0, minute=0, second=0, microsecond=0)
    inicio = max(hoy - timedelta(days=ventana), primera)
    dias = (hoy - inicio).days
    if dias < MIN_DIAS_HISTORIAL:
        return None

    desde, hasta = inicio.strftime("%Y-%m-%d"), ctx["hoy_iso"]
    suma = sum(t["monto"] for t in ctx["todas"]
               if t["tipo"] == "gasto" and desde <= t["fecha"] < hasta and not es_fijo(t, ctx))
    return suma / dias


def proyeccion_cierre_mes(ctx, categoria=None):
    """Cuanto se habria gastado al cerrar el mes (todas las categorias o una).

    fijo     -> se paga una vez: max(lo ya gastado en fijos, lo definido como fijo)
    variable -> sigue el ritmo actual: gastado / dias transcurridos x dias del mes
    """
    gastos = gastos_del_mes(ctx, categoria)
    fijo_gastado = sum(t["monto"] for t in gastos if es_fijo(t, ctx))
    variable = sum(t["monto"] for t in gastos if not es_fijo(t, ctx))
    fijo_esperado = sum(f["monto_mensual"] for f in ctx["fijos"]
                        if categoria is None or _categoria_fijo(f) == categoria)
    return max(fijo_gastado, fijo_esperado) + variable / ctx["dia"] * ctx["dias_mes"]


def fijos_pendientes(ctx):
    """Gastos fijos definidos que todavia no se han registrado este mes."""
    if "_fijos_pendientes" not in ctx:
        ctx["_fijos_pendientes"] = [
            f for f in ctx["fijos"]
            if not db.gasto_fijo_ya_registrado_este_mes(f["nombre"], ctx["mes"])
        ]
    return ctx["_fijos_pendientes"]


def disponible_mes(ctx):
    """Cuanto te queda libre del presupuesto general, descontando los gastos
    fijos que aun no has registrado. None si no hay presupuesto general."""
    limite = ctx["presupuesto_general"]
    if not limite:
        return None
    gastado = total(ctx["del_mes"], "gasto")
    pendientes = sum(f["monto_mensual"] for f in fijos_pendientes(ctx))
    libre = limite - gastado - pendientes
    dias = dias_restantes(ctx)
    return {
        "limite": limite, "gastado": gastado, "fijos_pendientes": pendientes,
        "libre": libre, "dias_restantes": dias, "por_dia": libre / dias,
    }


def ahorrado_en_fondo(ctx, nombre):
    ahorro = sum(t["monto"] for t in ctx["todas"] if t["tipo"] == "ahorro" and t["categoria"] == nombre)
    retiro = sum(t["monto"] for t in ctx["todas"] if t["tipo"] == "retiro_ahorro" and t["categoria"] == nombre)
    return ahorro - retiro


def _variable_hasta_dia(transacciones, ctx, dia):
    return sum(t["monto"] for t in transacciones
               if t["tipo"] == "gasto" and not es_fijo(t, ctx) and int(t["fecha"][8:10]) <= dia)


# ---------------------------------------------------------------------------
# Alertas EN EL MOMENTO: se evaluan justo despues de registrar un gasto y
# solo avisan cuando ESE gasto cruza un umbral (no repiten aviso en cada gasto).
# ---------------------------------------------------------------------------

def _cruce(antes, despues, limite):
    if antes < limite <= despues:
        return "excedido"
    if antes < limite * UMBRAL_AVISO <= despues:
        return "aviso"
    return None


def _texto_cruce(nivel, etiqueta, gastado, limite, ctx):
    if nivel == "excedido":
        return f"🚨 Te pasaste del presupuesto {etiqueta} por {pesos(gastado - limite)}."
    restante = limite - gastado
    dias = dias_restantes(ctx)
    return (
        f"⚠️ Ojo: ya vas en el {gastado / limite * 100:.0f}% del presupuesto {etiqueta}. "
        f"Te quedan {pesos(restante)} para {dias} dias (~{pesos(restante / dias)} por dia)."
    )


def alertas_por_gasto(ctx, t):
    """`ctx` debe cargarse DESPUES de guardar la transaccion `t`."""
    if t["tipo"] != "gasto":
        return []

    alertas = []

    if t["fecha"].startswith(ctx["mes"]):
        limite = ctx["presupuestos"].get(t["categoria"])
        if limite and limite > 0:
            despues = sum(x["monto"] for x in gastos_del_mes(ctx, t["categoria"]))
            nivel = _cruce(despues - t["monto"], despues, limite)
            if nivel:
                alertas.append(_texto_cruce(nivel, f"de {t['categoria']}", despues, limite, ctx))

        limite = ctx["presupuesto_general"]
        if limite and limite > 0:
            despues = total(ctx["del_mes"], "gasto")
            nivel = _cruce(despues - t["monto"], despues, limite)
            if nivel:
                alertas.append(_texto_cruce(nivel, "general", despues, limite, ctx))

    if t["fecha"] == ctx["hoy_iso"] and not es_fijo(t, ctx):
        base = promedio_diario_variable(ctx)
        if base:
            hoy_total = gasto_variable_del_dia(ctx, ctx["hoy_iso"])
            if hoy_total - t["monto"] < base * FACTOR_DIA_ATIPICO <= hoy_total:
                alertas.append(
                    f"📊 Hoy ya llevas {pesos(hoy_total)} en gastos, mas del doble de tu "
                    f"promedio diario ({pesos(base)})."
                )

    return alertas


# ---------------------------------------------------------------------------
# Alertas de ESTADO: revisan como va el mes completo (las usa el aviso de la
# manana y el asistente conversacional).
# ---------------------------------------------------------------------------

def _alerta_presupuesto(sujeto, etiqueta, gastado, limite, proyeccion, ctx):
    if gastado >= limite:
        return (f"🚨 Te pasaste del presupuesto {etiqueta}: {pesos(gastado)} de {pesos(limite)} "
                f"(+{pesos(gastado - limite)}).")
    if gastado >= limite * UMBRAL_AVISO:
        restante, dias = limite - gastado, dias_restantes(ctx)
        return (f"⚠️ Vas en el {gastado / limite * 100:.0f}% del presupuesto {etiqueta}. "
                f"Te quedan {pesos(restante)} para {dias} dias (~{pesos(restante / dias)} por dia).")
    if ctx["dia"] >= MIN_DIA_PROYECCION and proyeccion > limite:
        return (f"📈 Al ritmo actual, {sujeto} cerraria el mes en {pesos(proyeccion)}, "
                f"{pesos(proyeccion - limite)} por encima de tu presupuesto de {pesos(limite)}.")
    return None


def _alertas_fondos(ctx):
    alertas = []
    hoy = ctx["hoy"].replace(hour=0, minute=0, second=0, microsecond=0)
    for f in ctx["fondos"]:
        if not f["monto_objetivo"] or not f["fecha_objetivo"]:
            continue
        faltante = f["monto_objetivo"] - ahorrado_en_fondo(ctx, f["nombre"])
        if faltante <= 0:
            continue
        try:
            fecha_meta = datetime.strptime(f["fecha_objetivo"], "%Y-%m-%d")
        except ValueError:
            continue

        dias = (fecha_meta - hoy).days
        if dias < 0:
            alertas.append(f"⏰ La fecha meta del fondo '{f['nombre']}' ya paso y aun te faltan {pesos(faltante)}.")
            continue

        requerido = faltante / max(1, math.ceil(dias / 30.4))
        aporte_mes = sum(t["monto"] for t in ctx["del_mes"]
                         if t["tipo"] == "ahorro" and t["categoria"] == f["nombre"])
        if ctx["dia"] >= 15 and aporte_mes < requerido:
            alertas.append(
                f"💰 Para completar el fondo '{f['nombre']}' el {f['fecha_objetivo']} necesitas apartar "
                f"~{pesos(requerido)} al mes; este mes llevas {pesos(aporte_mes)}."
            )
    return alertas


def alertas_estado(ctx):
    """Lista de avisos sobre como va el mes, los mas graves (🚨) primero."""
    alertas = []
    gastado_total = total(ctx["del_mes"], "gasto")

    for categoria, limite in sorted(ctx["presupuestos"].items()):
        if limite <= 0:
            continue
        gastado = sum(t["monto"] for t in gastos_del_mes(ctx, categoria))
        a = _alerta_presupuesto(categoria, f"de {categoria}", gastado, limite,
                                proyeccion_cierre_mes(ctx, categoria), ctx)
        if a:
            alertas.append(a)

    limite = ctx["presupuesto_general"]
    if limite and limite > 0:
        a = _alerta_presupuesto("tu gasto total", "general", gastado_total, limite,
                                proyeccion_cierre_mes(ctx), ctx)
        if a:
            alertas.append(a)

    ingresos = total(ctx["del_mes"], "ingreso")
    if ingresos > 0 and gastado_total > ingresos:
        alertas.append(
            f"🚨 Este mes ya has gastado {pesos(gastado_total)}, mas de lo que ha entrado "
            f"({pesos(ingresos)}). Estas gastando mas de lo que ganas."
        )

    if ctx["dia"] >= 10:
        actual = _variable_hasta_dia(ctx["del_mes"], ctx, ctx["dia"])
        previo = _variable_hasta_dia(ctx["del_mes_anterior"], ctx, ctx["dia"])
        if previo > 0 and actual > previo * UMBRAL_VS_MES_PASADO:
            alertas.append(
                f"📊 Llevas {pesos(actual)} en gastos variables este mes: "
                f"{(actual / previo - 1) * 100:.0f}% mas que a esta altura del mes pasado ({pesos(previo)})."
            )

    alertas.extend(_alertas_fondos(ctx))

    if ctx["dia"] >= 5:
        pendientes = fijos_pendientes(ctx)
        if pendientes:
            nombres = ", ".join(f["nombre"] for f in pendientes)
            monto = sum(f["monto_mensual"] for f in pendientes)
            alertas.append(
                f"🧾 Tienes {len(pendientes)} gasto(s) fijo(s) sin registrar este mes ({nombres}) "
                f"por {pesos(monto)}. Escribe 'registrar gastos fijos' para contarlos."
            )

    alertas.sort(key=lambda a: 0 if a.startswith("🚨") else 1)  # sort estable
    return alertas


def mensaje_alertas(ctx, maximo=MAX_ALERTAS):
    """Texto listo para enviar ('' si no hay nada que avisar)."""
    return "\n".join(alertas_estado(ctx)[:maximo])
