import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent.parent / "data" / "finanzas.db"


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = conectar()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,          -- YYYY-MM-DD
            tipo TEXT NOT NULL,           -- 'gasto' | 'ingreso' | 'ahorro'
            monto REAL NOT NULL,
            categoria TEXT NOT NULL,      -- para tipo 'ahorro', aqui va el NOMBRE DEL FONDO
            descripcion TEXT,
            creado_en TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT UNIQUE,        -- NULL si es el presupuesto general
            tipo TEXT NOT NULL,           -- 'presupuesto' | 'presupuesto_general'
            limite_mensual REAL
        );

        CREATE TABLE IF NOT EXISTS gastos_fijos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,   -- ej. 'arriendo', 'netflix'
            monto_mensual REAL NOT NULL,
            categoria TEXT
        );

        CREATE TABLE IF NOT EXISTS registros_gastos_fijos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gasto_fijo_id INTEGER NOT NULL,
            mes TEXT NOT NULL,             -- 'YYYY-MM'
            transaccion_id INTEGER,
            UNIQUE(gasto_fijo_id, mes)
        );

        CREATE TABLE IF NOT EXISTS fondos_ahorro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,   -- ej. 'carro', 'estudio', 'emergencia'
            monto_objetivo REAL,
            fecha_objetivo TEXT            -- YYYY-MM-DD, opcional
        );
        """
    )

    # Migracion segura: si la base de datos ya existia (de una version anterior
    # sin medio_pago), agregamos la columna sin perder los datos existentes.
    columnas = [fila["name"] for fila in conn.execute("PRAGMA table_info(transacciones)").fetchall()]
    if "medio_pago" not in columnas:
        conn.execute("ALTER TABLE transacciones ADD COLUMN medio_pago TEXT")

    conn.commit()
    conn.close()


def agregar_transaccion(fecha, tipo, monto, categoria, descripcion, medio_pago=None):
    """Devuelve el id de la transaccion recien creada (util para los gastos fijos,
    que necesitan enlazar la transaccion generada con su registro mensual)."""
    conn = conectar()
    cursor = conn.execute(
        """INSERT INTO transacciones (fecha, tipo, monto, categoria, descripcion, medio_pago)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (fecha, tipo, monto, categoria, descripcion, medio_pago),
    )
    conn.commit()
    nuevo_id = cursor.lastrowid
    conn.close()
    return nuevo_id


def transacciones_del_mes(categoria=None, tipo=None, fecha_ref=None):
    fecha_ref = fecha_ref or datetime.now()
    prefijo = fecha_ref.strftime("%Y-%m")

    query = "SELECT * FROM transacciones WHERE fecha LIKE ?"
    params = [f"{prefijo}%"]

    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)

    conn = conectar()
    filas = conn.execute(query, params).fetchall()
    conn.close()
    return filas


def transacciones_de_la_semana():
    hace_una_semana = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    conn = conectar()
    filas = conn.execute(
        "SELECT * FROM transacciones WHERE fecha >= ?", (hace_una_semana,)
    ).fetchall()
    conn.close()
    return filas


def obtener_meta(categoria):
    conn = conectar()
    fila = conn.execute(
        "SELECT * FROM metas WHERE categoria = ?", (categoria,)
    ).fetchone()
    conn.close()
    return fila


def obtener_todas_las_metas():
    conn = conectar()
    filas = conn.execute("SELECT * FROM metas").fetchall()
    conn.close()
    return filas


def definir_presupuesto(categoria, limite_mensual):
    conn = conectar()
    conn.execute(
        """INSERT INTO metas (categoria, tipo, limite_mensual)
           VALUES (?, 'presupuesto', ?)
           ON CONFLICT(categoria) DO UPDATE SET limite_mensual = excluded.limite_mensual""",
        (categoria, limite_mensual),
    )
    conn.commit()
    conn.close()


# --- Presupuesto general ---

def definir_presupuesto_general(limite_mensual):
    conn = conectar()
    conn.execute("DELETE FROM metas WHERE tipo = 'presupuesto_general'")
    conn.execute(
        """INSERT INTO metas (tipo, limite_mensual) VALUES ('presupuesto_general', ?)""",
        (limite_mensual,),
    )
    conn.commit()
    conn.close()


def obtener_presupuesto_general():
    conn = conectar()
    fila = conn.execute(
        "SELECT * FROM metas WHERE tipo = 'presupuesto_general'"
    ).fetchone()
    conn.close()
    return fila


# --- Editar / borrar transacciones ---

def obtener_transaccion(id_transaccion):
    conn = conectar()
    fila = conn.execute(
        "SELECT * FROM transacciones WHERE id = ?", (id_transaccion,)
    ).fetchone()
    conn.close()
    return fila


def ultimas_transacciones(limite=10):
    conn = conectar()
    filas = conn.execute(
        "SELECT * FROM transacciones ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()
    conn.close()
    return filas


def eliminar_transaccion(id_transaccion):
    conn = conectar()
    cursor = conn.execute("DELETE FROM transacciones WHERE id = ?", (id_transaccion,))
    conn.commit()
    filas_afectadas = cursor.rowcount
    conn.close()
    return filas_afectadas > 0


def editar_monto_transaccion(id_transaccion, nuevo_monto):
    conn = conectar()
    cursor = conn.execute(
        "UPDATE transacciones SET monto = ? WHERE id = ?", (nuevo_monto, id_transaccion)
    )
    conn.commit()
    filas_afectadas = cursor.rowcount
    conn.close()
    return filas_afectadas > 0


def editar_categoria_transaccion(id_transaccion, nueva_categoria):
    conn = conectar()
    cursor = conn.execute(
        "UPDATE transacciones SET categoria = ? WHERE id = ?", (nueva_categoria, id_transaccion)
    )
    conn.commit()
    filas_afectadas = cursor.rowcount
    conn.close()
    return filas_afectadas > 0


# --- Gastos fijos ---

def definir_gasto_fijo(nombre, monto_mensual, categoria=None):
    conn = conectar()
    conn.execute(
        """INSERT INTO gastos_fijos (nombre, monto_mensual, categoria)
           VALUES (?, ?, ?)
           ON CONFLICT(nombre) DO UPDATE SET
             monto_mensual = excluded.monto_mensual,
             categoria = excluded.categoria""",
        (nombre, monto_mensual, categoria),
    )
    conn.commit()
    conn.close()


def eliminar_gasto_fijo(nombre):
    conn = conectar()
    cursor = conn.execute("DELETE FROM gastos_fijos WHERE nombre = ?", (nombre,))
    conn.commit()
    filas_afectadas = cursor.rowcount
    conn.close()
    return filas_afectadas > 0


def obtener_gastos_fijos():
    conn = conectar()
    filas = conn.execute("SELECT * FROM gastos_fijos ORDER BY nombre").fetchall()
    conn.close()
    return filas


def gasto_fijo_ya_registrado_este_mes(gasto_fijo_id, mes):
    conn = conectar()
    fila = conn.execute(
        "SELECT 1 FROM registros_gastos_fijos WHERE gasto_fijo_id = ? AND mes = ?",
        (gasto_fijo_id, mes),
    ).fetchone()
    conn.close()
    return fila is not None


def marcar_gasto_fijo_registrado(gasto_fijo_id, mes, transaccion_id):
    conn = conectar()
    conn.execute(
        """INSERT INTO registros_gastos_fijos (gasto_fijo_id, mes, transaccion_id)
           VALUES (?, ?, ?)""",
        (gasto_fijo_id, mes, transaccion_id),
    )
    conn.commit()
    conn.close()


def registrar_gastos_fijos_pendientes(fecha_ref=None):
    """Revisa todos los gastos fijos definidos y crea la transaccion del mes
    para los que aun no se hayan registrado. Es seguro llamarla varias veces
    en el mismo mes: no duplica los que ya estan registrados.
    Devuelve la lista de gastos fijos que se registraron en esta llamada."""
    fecha_ref = fecha_ref or datetime.now()
    mes_actual = fecha_ref.strftime("%Y-%m")
    fecha_hoy = fecha_ref.strftime("%Y-%m-%d")

    registrados_ahora = []

    for gasto_fijo in obtener_gastos_fijos():
        if gasto_fijo_ya_registrado_este_mes(gasto_fijo["id"], mes_actual):
            continue

        transaccion_id = agregar_transaccion(
            fecha=fecha_hoy,
            tipo="gasto",
            monto=gasto_fijo["monto_mensual"],
            categoria=gasto_fijo["categoria"] or gasto_fijo["nombre"],
            descripcion=f"{gasto_fijo['nombre']} (gasto fijo)",
        )
        marcar_gasto_fijo_registrado(gasto_fijo["id"], mes_actual, transaccion_id)
        registrados_ahora.append(gasto_fijo)

    return registrados_ahora


# --- Fondos de ahorro ---

def definir_fondo(nombre, monto_objetivo=None, fecha_objetivo=None):
    conn = conectar()
    conn.execute(
        """INSERT INTO fondos_ahorro (nombre, monto_objetivo, fecha_objetivo)
           VALUES (?, ?, ?)
           ON CONFLICT(nombre) DO UPDATE SET
             monto_objetivo = COALESCE(excluded.monto_objetivo, fondos_ahorro.monto_objetivo),
             fecha_objetivo = COALESCE(excluded.fecha_objetivo, fondos_ahorro.fecha_objetivo)""",
        (nombre, monto_objetivo, fecha_objetivo),
    )
    conn.commit()
    conn.close()


def eliminar_fondo(nombre):
    conn = conectar()
    cursor = conn.execute("DELETE FROM fondos_ahorro WHERE nombre = ?", (nombre,))
    conn.commit()
    filas_afectadas = cursor.rowcount
    conn.close()
    return filas_afectadas > 0


def obtener_fondo(nombre):
    conn = conectar()
    fila = conn.execute("SELECT * FROM fondos_ahorro WHERE nombre = ?", (nombre,)).fetchone()
    conn.close()
    return fila


def obtener_todos_los_fondos():
    conn = conectar()
    filas = conn.execute("SELECT * FROM fondos_ahorro ORDER BY nombre").fetchall()
    conn.close()
    return filas


def total_ahorrado_fondo(nombre):
    """Suma TODO el historico ahorrado hacia un fondo, restando lo que se haya
    retirado de ese mismo fondo (tipo 'retiro_ahorro'). No se limita al mes
    actual, ya que un fondo de ahorro se acumula a lo largo de varios meses."""
    conn = conectar()
    fila_ahorro = conn.execute(
        "SELECT COALESCE(SUM(monto), 0) as total FROM transacciones WHERE tipo = 'ahorro' AND categoria = ?",
        (nombre,),
    ).fetchone()
    fila_retiro = conn.execute(
        "SELECT COALESCE(SUM(monto), 0) as total FROM transacciones WHERE tipo = 'retiro_ahorro' AND categoria = ?",
        (nombre,),
    ).fetchone()
    conn.close()
    return fila_ahorro["total"] - fila_retiro["total"]
