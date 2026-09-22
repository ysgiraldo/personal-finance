"""Asistente financiero conversacional.

Responde preguntas ("¿cuanto llevo?", "¿puedo comprarme X?", "¿como ahorro mas?")
usando DATOS REALES de la persona (los que calcula analisis.py) mas un prompt
con criterio de finanzas personales. Recuerda los ultimos mensajes durante 30
minutos para poder seguir la conversacion ("¿y si lo pago en cuotas?").
"""
import os

from . import analisis, db
from .llm import client
from .utils import DIAS_SEMANA, formato_pesos as pesos

# Haiku 4.5 mantiene el costo casi en cero. Para consejos mas finos puedes
# poner la variable de entorno MODELO_ASISTENTE (ej. "claude-sonnet-5").
MODELO_ASISTENTE = os.environ.get("MODELO_ASISTENTE", "claude-haiku-4-5-20251001")

SYSTEM_ASISTENTE = """Eres el asistente financiero personal de UNA persona que vive en Colombia. Hablas con ella por Telegram, dentro de su bot de finanzas. Tu meta: ayudarle a entender su plata y a tomar mejores decisiones, basandote en SUS datos reales.

COMO RESPONDES
- Español colombiano natural y cercano (tuteo). Montos en pesos con punto de miles ($85.000).
- Mensajes cortos, pensados para leer en el celular: normalmente de 3 a 8 lineas. Primero la respuesta o recomendacion, luego el por que con cifras. Si la persona pide mas detalle, extiendete.
- Texto plano: NO uses markdown (nada de **negritas**, #, tablas ni bloques de codigo). Puedes usar saltos de linea, guiones simples y algun emoji ocasional.
- Maximo una pregunta de vuelta, y solo si de verdad falta un dato clave. Si puedes responder con lo que tienes, responde.

REGLAS CON LOS DATOS (muy importantes)
- Usa SOLO las cifras del bloque "DATOS DEL USUARIO". Nunca inventes gastos, ingresos, saldos ni fechas. Si falta un dato para responder bien (no hay ingresos registrados, no hay presupuesto, etc.), dilo y explica como registrarlo (ej: 'me pagaron 2 millones de sueldo', 'definir presupuesto comida 600000').
- Las cifras ya vienen calculadas: no las recalcules desde cero. Si necesitas una cuenta simple, hazla con cuidado y muestra solo el resultado.
- Los gastos fijos se pagan una vez al mes; no los trates como gasto diario.
- No tienes acceso a cuentas bancarias, solo a lo que la persona ha registrado en el bot. Tampoco puedes registrar ni editar nada tu: eso se hace escribiendole al bot normalmente.

LO QUE SABES DE FINANZAS PERSONALES (usalo cuando aplique, adaptado a Colombia)
- Pagate primero: apartar el ahorro apenas entra el ingreso funciona mejor que ahorrar "lo que sobre".
- La regla 50/30/20 (necesidades/gustos/ahorro) es una referencia orientativa, no una ley: ajustala a su realidad.
- Fondo de emergencia: 3 a 6 meses de gastos esenciales (mas si el ingreso es variable o independiente), en algo liquido y de bajo riesgo. Va antes que invertir.
- Deudas: primero las mas caras. La tarjeta de credito y los prestamos de consumo tienen tasas muy altas; pagar solo el minimo sale carisimo. Revisa cuota de manejo, seguros e intereses reales de las cuotas.
- Compras grandes o por impulso: esperar 24 a 72 horas, comparar el costo total (no solo la cuota) y no financiar lo que no cabe en el presupuesto de contado.
- Presupuesto por categorias con un colchon para imprevistos. Los "gastos hormiga" (cafes, domicilios, apps, suscripciones) suman mas de lo que parece.
- Metas: dividir lo que falta entre los meses que quedan para saber cuanto apartar al mes, y automatizar el aporte.
- Inversion (CDT, fondos de inversion colectiva, ahorro programado, pension voluntaria...): explica conceptos, riesgos y diferencias en general; NO recomiendes un producto o entidad concreta ni prometas rentabilidades. Para decisiones de inversion, impuestos o deudas complejas, sugiere hablar con un asesor certificado. Si no estas seguro de una tasa o norma vigente, dilo en vez de inventarla.

PREGUNTAS DEL TIPO "¿PUEDO COMPRAR X?"
Mira cuanto queda del presupuesto, si el mes va en superavit o deficit, si hay fondo de emergencia y si hay metas de ahorro pendientes. Da una respuesta clara (si / no / mejor esperar) con las 2 o 3 razones principales, con cifras.

ACTITUD
- Se honesto aunque no sea lo que la persona quiere oir, pero sin regañar ni juzgar. Reconoce tambien lo que va bien.
- Si la persona muestra angustia por deudas o una crisis economica, responde con empatia y ayudale a ordenar prioridades paso a paso.
- Si preguntan algo que no tiene que ver con finanzas personales, responde breve y ofrece volver al tema.
- Puedes sugerir comandos del bot cuando ayuden: 'hoy', 'resumen mensual', 'definir presupuesto <categoria> <monto>', 'definir presupuesto general <monto>', 'definir fondo <nombre> <meta> <AAAA-MM-DD>', 'listar', 'editar <id> monto <valor>'."""


def texto_contexto(ctx):
    """Resumen legible y YA CALCULADO de las finanzas de la persona."""
    hoy_iso = ctx["hoy_iso"]
    L = []

    L.append(
        f"Fecha de hoy: {DIAS_SEMANA[ctx['hoy'].weekday()]} {hoy_iso} "
        f"(dia {ctx['dia']} de {ctx['dias_mes']}; quedan {analisis.dias_restantes(ctx)} dias contando hoy)."
    )

    # --- Hoy ---
    del_dia = [t for t in ctx["todas"] if t["fecha"] == hoy_iso]
    gastos_hoy = [t for t in del_dia if t["tipo"] == "gasto"]
    L.append("")
    if gastos_hoy:
        L.append(f"HOY: {pesos(sum(t['monto'] for t in gastos_hoy))} en gastos ({len(gastos_hoy)} movimientos).")
    else:
        L.append("HOY: sin gastos registrados todavia.")

    # --- Mes actual ---
    mes = ctx["del_mes"]
    ingresos = analisis.total(mes, "ingreso")
    gastos = [t for t in mes if t["tipo"] == "gasto"]
    total_gastos = sum(t["monto"] for t in gastos)
    fijos = sum(t["monto"] for t in gastos if analisis.es_fijo(t, ctx))
    ahorro = analisis.total(mes, "ahorro")
    retiros = analisis.total(mes, "retiro_ahorro")

    L.append("")
    L.append(f"MES ACTUAL ({ctx['mes']}):")
    L.append(f"- Ingresos registrados: {pesos(ingresos)}")
    L.append(f"- Gastos: {pesos(total_gastos)} (fijos {pesos(fijos)}, variables {pesos(total_gastos - fijos)})")
    L.append(f"- Ahorro apartado: {pesos(ahorro)}" + (f"; retiros de ahorro: {pesos(retiros)}" if retiros else ""))
    if ingresos > 0:
        L.append(f"- Balance ingresos - gastos: {pesos(ingresos - total_gastos)}"
                 f" | gasto = {total_gastos / ingresos * 100:.0f}% de los ingresos"
                 f" | ahorro = {ahorro / ingresos * 100:.0f}% de los ingresos")
    else:
        L.append("- (No hay ingresos registrados este mes, no se puede calcular balance ni tasa de ahorro.)")
    L.append(f"- Proyeccion de gasto al cierre del mes: {pesos(analisis.proyeccion_cierre_mes(ctx))}"
             + ("" if ctx["dia"] >= analisis.MIN_DIA_PROYECCION else " (poco confiable: es inicio de mes)"))

    por_categoria = {}
    for t in gastos:
        por_categoria[t["categoria"]] = por_categoria.get(t["categoria"], 0) + t["monto"]
    if por_categoria:
        L.append("- Gasto por categoria: " + ", ".join(
            f"{c} {pesos(m)} ({m / total_gastos * 100:.0f}%)"
            for c, m in sorted(por_categoria.items(), key=lambda kv: kv[1], reverse=True)[:10]))

    base = analisis.promedio_diario_variable(ctx)
    if base:
        L.append(f"- Promedio diario de gasto variable (ultimos 30 dias, sin fijos): {pesos(base)}")

    # --- Presupuestos ---
    L.append("")
    if ctx["presupuestos"] or ctx["presupuesto_general"]:
        L.append("PRESUPUESTOS:")
        for categoria, limite in sorted(ctx["presupuestos"].items()):
            gastado = por_categoria.get(categoria, 0)
            if limite > 0:
                L.append(f"- {categoria}: {pesos(gastado)} de {pesos(limite)} ({gastado / limite * 100:.0f}%), "
                         f"proyeccion de cierre {pesos(analisis.proyeccion_cierre_mes(ctx, categoria))}")
        disp = analisis.disponible_mes(ctx)
        if disp:
            L.append(f"- GENERAL: {pesos(disp['gastado'])} de {pesos(disp['limite'])} "
                     f"({disp['gastado'] / disp['limite'] * 100:.0f}%)")
            L.append(f"- Libre para el resto del mes: {pesos(disp['libre'])} "
                     f"(~{pesos(disp['por_dia'])} por dia durante {disp['dias_restantes']} dias)"
                     + (f", ya descontando {pesos(disp['fijos_pendientes'])} de gastos fijos por registrar"
                        if disp["fijos_pendientes"] > 0 else ""))
    else:
        L.append("PRESUPUESTOS: no ha definido ninguno.")

    # --- Gastos fijos ---
    if ctx["fijos"]:
        pendientes = {f["nombre"] for f in analisis.fijos_pendientes(ctx)}
        L.append("")
        L.append("GASTOS FIJOS MENSUALES: " + ", ".join(
            f"{f['nombre']} {pesos(f['monto_mensual'])} ({'pendiente de registrar' if f['nombre'] in pendientes else 'ya registrado'})"
            for f in ctx["fijos"]))

    # --- Fondos de ahorro ---
    if ctx["fondos"]:
        L.append("")
        L.append("FONDOS DE AHORRO:")
        for f in ctx["fondos"]:
            ahorrado = analisis.ahorrado_en_fondo(ctx, f["nombre"])
            linea = f"- {f['nombre']}: {pesos(ahorrado)}"
            if f["monto_objetivo"]:
                linea += f" de {pesos(f['monto_objetivo'])} ({ahorrado / f['monto_objetivo'] * 100:.0f}%)"
            if f["fecha_objetivo"]:
                linea += f", meta para el {f['fecha_objetivo']}"
            L.append(linea)

    # --- Mes anterior ---
    previo = ctx["del_mes_anterior"]
    if previo:
        L.append("")
        L.append(f"MES ANTERIOR ({ctx['mes_anterior']}): ingresos {pesos(analisis.total(previo, 'ingreso'))}, "
                 f"gastos {pesos(analisis.total(previo, 'gasto'))}, ahorro {pesos(analisis.total(previo, 'ahorro'))}")

    # --- Ultimos movimientos ---
    recientes = sorted(ctx["todas"], key=lambda t: t["id"], reverse=True)[:12]
    if recientes:
        L.append("")
        L.append("ULTIMOS MOVIMIENTOS (id, fecha, tipo, monto, categoria):")
        for t in recientes:
            L.append(f"- #{t['id']} {t['fecha']} {t['tipo']} {pesos(t['monto'])} {t['categoria']}"
                     + (f" ({t['descripcion']})" if t.get("descripcion") else ""))
    else:
        L.append("")
        L.append("Aun no hay movimientos registrados.")

    # --- Alertas activas ---
    alertas = analisis.alertas_estado(ctx)
    if alertas:
        L.append("")
        L.append("ALERTAS ACTIVAS (ya calculadas por el sistema):")
        L.extend(f"- {a}" for a in alertas)

    return "\n".join(L)


def responder(pregunta):
    """Contesta una pregunta libre sobre finanzas, con los datos reales de la persona."""
    ctx = analisis.cargar_contexto()
    system = SYSTEM_ASISTENTE + "\n\n=== DATOS DEL USUARIO (fuente unica de cifras) ===\n" + texto_contexto(ctx)

    historial = db.obtener_conversacion()
    while historial and historial[0]["role"] != "user":  # la API exige empezar con "user"
        historial.pop(0)
    mensajes = historial + [{"role": "user", "content": pregunta}]

    respuesta = client.messages.create(
        model=MODELO_ASISTENTE,
        max_tokens=700,
        system=system,
        messages=mensajes,
    )
    texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
    if not texto:
        return "No pude armar una respuesta, intenta de nuevo."
    texto = texto[:3900]  # Telegram acepta maximo 4096 caracteres por mensaje

    try:
        db.guardar_conversacion(mensajes + [{"role": "assistant", "content": texto}])
    except Exception as err:  # la respuesta ya esta lista: perder la memoria no es grave
        print(f"No se pudo guardar la conversacion: {err}")

    return texto
