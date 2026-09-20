import os
import boto3
from decimal import Decimal
from datetime import timedelta
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from .utils import ahora

TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "finanzas_bot")

_dynamodb = boto3.resource("dynamodb")
_tabla = _dynamodb.Table(TABLE_NAME)


# --- Helpers de conversion (DynamoDB usa Decimal, el resto del codigo usa float) ---

def _f(valor):
    """Decimal (o None) -> float (o None). Evita TypeErrors al mezclar Decimal con float."""
    if valor is None:
        return None
    return float(valor)


def _dec(valor):
    """float (o None) -> Decimal (o None). DynamoDB no acepta float directamente."""
    if valor is None:
        return None
    return Decimal(str(valor))


def init_db():
    """No-op: la tabla de DynamoDB se crea con infraestructura (consola/CLI/CloudFormation),
    no en tiempo de ejecucion como hacíamos con sqlite3.executescript()."""
    pass


# --- Transacciones ---

def _siguiente_id_transaccion():
    """Contador atomico (equivalente al AUTOINCREMENT de SQLite)."""
    respuesta = _tabla.update_item(
        Key={"PK": "COUNTER", "SK": "TXN"},
        UpdateExpression="ADD #v :incr",
        ExpressionAttributeNames={"#v": "valor"},
        ExpressionAttributeValues={":incr": 1},
        ReturnValues="UPDATED_NEW",
    )
    return int(respuesta["Attributes"]["valor"])


def agregar_transaccion(fecha, tipo, monto, categoria, descripcion, medio_pago=None):
    nuevo_id = _siguiente_id_transaccion()
    item = {
        "PK": "TXN",
        "SK": f"{nuevo_id:010d}",
        "id": nuevo_id,
        "fecha": fecha,
        "tipo": tipo,
        "monto": _dec(monto),
        "categoria": categoria,
        "descripcion": descripcion or "",
    }
    if medio_pago:
        item["medio_pago"] = medio_pago
    _tabla.put_item(Item=item)
    return nuevo_id


def _item_a_transaccion(item):
    return {
        "id": int(item["id"]),  # DynamoDB lo devuelve como Decimal; sin int() falla f"{id:010d}"
        "fecha": item["fecha"],
        "tipo": item["tipo"],
        "monto": _f(item["monto"]),
        "categoria": item["categoria"],
        "descripcion": item.get("descripcion", ""),
        "medio_pago": item.get("medio_pago"),
    }


def _todas_las_transacciones():
    """Trae todas las transacciones (volumen personal = pequeno, no hace falta
    paginar ni optimizar con indices secundarios)."""
    resultado = []
    respuesta = _tabla.query(KeyConditionExpression=Key("PK").eq("TXN"))
    resultado.extend(respuesta["Items"])
    while "LastEvaluatedKey" in respuesta:
        respuesta = _tabla.query(
            KeyConditionExpression=Key("PK").eq("TXN"),
            ExclusiveStartKey=respuesta["LastEvaluatedKey"],
        )
        resultado.extend(respuesta["Items"])
    return [_item_a_transaccion(i) for i in resultado]


def todas_las_transacciones():
    """Version publica de _todas_las_transacciones (la usa analisis.py para
    leer la tabla UNA sola vez y calcular todo en memoria)."""
    return _todas_las_transacciones()


def transacciones_del_mes(categoria=None, tipo=None, fecha_ref=None):
    fecha_ref = fecha_ref or ahora()
    prefijo = fecha_ref.strftime("%Y-%m")

    transacciones = [t for t in _todas_las_transacciones() if t["fecha"].startswith(prefijo)]
    if categoria:
        transacciones = [t for t in transacciones if t["categoria"] == categoria]
    if tipo:
        transacciones = [t for t in transacciones if t["tipo"] == tipo]
    return transacciones


def transacciones_de_la_semana():
    hace_una_semana = (ahora() - timedelta(days=7)).strftime("%Y-%m-%d")
    return [t for t in _todas_las_transacciones() if t["fecha"] >= hace_una_semana]


def obtener_transaccion(id_transaccion):
    respuesta = _tabla.get_item(Key={"PK": "TXN", "SK": f"{id_transaccion:010d}"})
    item = respuesta.get("Item")
    return _item_a_transaccion(item) if item else None


def ultimas_transacciones(limite=10):
    respuesta = _tabla.query(
        KeyConditionExpression=Key("PK").eq("TXN"),
        ScanIndexForward=False,  # descendente, las mas nuevas primero
        Limit=limite,
    )
    return [_item_a_transaccion(i) for i in respuesta["Items"]]


def eliminar_transaccion(id_transaccion):
    respuesta = _tabla.delete_item(
        Key={"PK": "TXN", "SK": f"{id_transaccion:010d}"},
        ReturnValues="ALL_OLD",
    )
    return "Attributes" in respuesta


CAMPOS_EDITABLES = ("fecha", "tipo", "monto", "categoria", "descripcion", "medio_pago")


def actualizar_transaccion(id_transaccion, cambios):
    """Modifica campos de una transaccion YA EXISTENTE.

    - `cambios` es un dict {campo: valor}. Un valor None elimina el campo
      (solo tiene sentido para medio_pago).
    - Devuelve (antes, despues) con la transaccion antes y despues del cambio,
      o None si el id no existe.
    - NUNCA crea una transaccion nueva: update_item de DynamoDB hace "upsert"
      por defecto (si la llave no existe, la crea). El ConditionExpression
      attribute_exists(PK) lo impide y ademas evita la carrera entre el
      get_item previo y el update.
    """
    cambios = {c: v for c, v in cambios.items() if c in CAMPOS_EDITABLES}
    if not cambios:
        raise ValueError("No hay campos validos para editar")

    asignaciones, eliminaciones = [], []
    nombres, valores = {}, {}
    for i, (campo, valor) in enumerate(cambios.items()):
        nombres[f"#c{i}"] = campo
        if valor is None:
            eliminaciones.append(f"#c{i}")
        else:
            valores[f":v{i}"] = _dec(valor) if campo == "monto" else valor
            asignaciones.append(f"#c{i} = :v{i}")

    partes = []
    if asignaciones:
        partes.append("SET " + ", ".join(asignaciones))
    if eliminaciones:
        partes.append("REMOVE " + ", ".join(eliminaciones))

    argumentos = {
        "Key": {"PK": "TXN", "SK": f"{id_transaccion:010d}"},
        "UpdateExpression": " ".join(partes),
        "ConditionExpression": "attribute_exists(PK)",
        "ExpressionAttributeNames": nombres,
        "ReturnValues": "ALL_OLD",
    }
    if valores:  # DynamoDB rechaza un ExpressionAttributeValues vacio
        argumentos["ExpressionAttributeValues"] = valores

    try:
        respuesta = _tabla.update_item(**argumentos)
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise

    antes = _item_a_transaccion(respuesta["Attributes"])
    despues = {**antes, **cambios}
    return antes, despues


# Atajos que ya existian (se conservan por compatibilidad)
def editar_monto_transaccion(id_transaccion, nuevo_monto):
    return actualizar_transaccion(id_transaccion, {"monto": nuevo_monto}) is not None


def editar_categoria_transaccion(id_transaccion, nueva_categoria):
    return actualizar_transaccion(id_transaccion, {"categoria": nueva_categoria}) is not None


def editar_fecha_transaccion(id_transaccion, nueva_fecha):
    return actualizar_transaccion(id_transaccion, {"fecha": nueva_fecha}) is not None


# --- Metas (presupuesto por categoria y presupuesto general) ---

def obtener_meta(categoria):
    respuesta = _tabla.get_item(Key={"PK": "META", "SK": f"CAT#{categoria}"})
    item = respuesta.get("Item")
    if not item:
        return None
    return {"categoria": item["categoria"], "tipo": item["tipo"], "limite_mensual": _f(item["limite_mensual"])}


def obtener_todas_las_metas():
    respuesta = _tabla.query(KeyConditionExpression=Key("PK").eq("META"))
    metas = []
    for item in respuesta["Items"]:
        metas.append({
            "categoria": item.get("categoria"),
            "tipo": item["tipo"],
            "limite_mensual": _f(item.get("limite_mensual")),
        })
    return metas


def definir_presupuesto(categoria, limite_mensual):
    _tabla.put_item(Item={
        "PK": "META", "SK": f"CAT#{categoria}",
        "categoria": categoria, "tipo": "presupuesto",
        "limite_mensual": _dec(limite_mensual),
    })


def definir_presupuesto_general(limite_mensual):
    _tabla.put_item(Item={
        "PK": "META", "SK": "GENERAL",
        "tipo": "presupuesto_general",
        "limite_mensual": _dec(limite_mensual),
    })


def obtener_presupuesto_general():
    respuesta = _tabla.get_item(Key={"PK": "META", "SK": "GENERAL"})
    item = respuesta.get("Item")
    if not item:
        return None
    return {"tipo": item["tipo"], "limite_mensual": _f(item["limite_mensual"])}


# --- Gastos fijos ---

def definir_gasto_fijo(nombre, monto_mensual, categoria=None):
    _tabla.put_item(Item={
        "PK": "GASTO_FIJO", "SK": nombre,
        "nombre": nombre, "monto_mensual": _dec(monto_mensual),
        "categoria": categoria or nombre,
    })


def eliminar_gasto_fijo(nombre):
    respuesta = _tabla.delete_item(Key={"PK": "GASTO_FIJO", "SK": nombre}, ReturnValues="ALL_OLD")
    return "Attributes" in respuesta


def obtener_gastos_fijos():
    respuesta = _tabla.query(KeyConditionExpression=Key("PK").eq("GASTO_FIJO"))
    gastos = [{
        "nombre": i["nombre"], "monto_mensual": _f(i["monto_mensual"]), "categoria": i.get("categoria"),
    } for i in respuesta["Items"]]
    return sorted(gastos, key=lambda g: g["nombre"])


def gasto_fijo_ya_registrado_este_mes(nombre_gasto_fijo, mes):
    respuesta = _tabla.get_item(Key={"PK": "REGISTRO_FIJO", "SK": f"{nombre_gasto_fijo}#{mes}"})
    return "Item" in respuesta


def marcar_gasto_fijo_registrado(nombre_gasto_fijo, mes, transaccion_id):
    _tabla.put_item(Item={
        "PK": "REGISTRO_FIJO", "SK": f"{nombre_gasto_fijo}#{mes}",
        "nombre": nombre_gasto_fijo, "mes": mes, "transaccion_id": transaccion_id,
    })


def registrar_gastos_fijos_pendientes(fecha_ref=None):
    """Revisa todos los gastos fijos definidos y crea la transaccion del mes
    para los que aun no se hayan registrado. Seguro de llamar varias veces:
    no duplica los que ya estan registrados ese mes."""
    fecha_ref = fecha_ref or ahora()
    mes_actual = fecha_ref.strftime("%Y-%m")
    fecha_hoy = fecha_ref.strftime("%Y-%m-%d")

    registrados_ahora = []
    for gasto_fijo in obtener_gastos_fijos():
        if gasto_fijo_ya_registrado_este_mes(gasto_fijo["nombre"], mes_actual):
            continue
        transaccion_id = agregar_transaccion(
            fecha=fecha_hoy, tipo="gasto", monto=gasto_fijo["monto_mensual"],
            categoria=gasto_fijo["categoria"] or gasto_fijo["nombre"],
            descripcion=f"{gasto_fijo['nombre']} (gasto fijo)",
        )
        marcar_gasto_fijo_registrado(gasto_fijo["nombre"], mes_actual, transaccion_id)
        registrados_ahora.append(gasto_fijo)

    return registrados_ahora


# --- Fondos de ahorro ---

def definir_fondo(nombre, monto_objetivo=None, fecha_objetivo=None):
    existente = obtener_fondo(nombre)
    item = {
        "PK": "FONDO", "SK": nombre, "nombre": nombre,
        "monto_objetivo": _dec(monto_objetivo) if monto_objetivo is not None else (
            _dec(existente["monto_objetivo"]) if existente and existente.get("monto_objetivo") is not None else None
        ),
        "fecha_objetivo": fecha_objetivo or (existente["fecha_objetivo"] if existente else None),
    }
    # DynamoDB no permite guardar attribute con valor None: lo quitamos si aplica
    item = {k: v for k, v in item.items() if v is not None}
    _tabla.put_item(Item=item)


def eliminar_fondo(nombre):
    respuesta = _tabla.delete_item(Key={"PK": "FONDO", "SK": nombre}, ReturnValues="ALL_OLD")
    return "Attributes" in respuesta


def obtener_fondo(nombre):
    respuesta = _tabla.get_item(Key={"PK": "FONDO", "SK": nombre})
    item = respuesta.get("Item")
    if not item:
        return None
    return {
        "nombre": item["nombre"],
        "monto_objetivo": _f(item.get("monto_objetivo")),
        "fecha_objetivo": item.get("fecha_objetivo"),
    }


def obtener_todos_los_fondos():
    respuesta = _tabla.query(KeyConditionExpression=Key("PK").eq("FONDO"))
    fondos = [{
        "nombre": i["nombre"], "monto_objetivo": _f(i.get("monto_objetivo")), "fecha_objetivo": i.get("fecha_objetivo"),
    } for i in respuesta["Items"]]
    return sorted(fondos, key=lambda f: f["nombre"])


def total_ahorrado_fondo(nombre):
    """Suma el historico ahorrado hacia un fondo, restando los retiros de ese mismo fondo."""
    todas = _todas_las_transacciones()
    ahorrado = sum(t["monto"] for t in todas if t["tipo"] == "ahorro" and t["categoria"] == nombre)
    retirado = sum(t["monto"] for t in todas if t["tipo"] == "retiro_ahorro" and t["categoria"] == nombre)
    return ahorrado - retirado

