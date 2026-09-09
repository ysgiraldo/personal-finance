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
            categoria TEXT NOT NULL,
            descripcion TEXT,
            creado_en TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT UNIQUE,        -- NULL si es la meta general de ahorro
            tipo TEXT NOT NULL,           -- 'presupuesto' | 'ahorro'
            limite_mensual REAL,          -- para tipo 'presupuesto'
            monto_objetivo REAL,          -- para tipo 'ahorro'
            fecha_objetivo TEXT           -- para tipo 'ahorro', YYYY-MM-DD
        );
        """
    )
    conn.commit()
    conn.close()


def agregar_transaccion(fecha, tipo, monto, categoria, descripcion):
    conn = conectar()
    conn.execute(
        """INSERT INTO transacciones (fecha, tipo, monto, categoria, descripcion)
           VALUES (?, ?, ?, ?, ?)""",
        (fecha, tipo, monto, categoria, descripcion),
    )
    conn.commit()
    conn.close()


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


def obtener_meta_ahorro():
    conn = conectar()
    fila = conn.execute("SELECT * FROM metas WHERE tipo = 'ahorro'").fetchone()
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


def definir_meta_ahorro(monto_objetivo, fecha_objetivo):
    conn = conectar()
    # Solo permitimos una meta de ahorro general a la vez
    conn.execute("DELETE FROM metas WHERE tipo = 'ahorro'")
    conn.execute(
        """INSERT INTO metas (tipo, monto_objetivo, fecha_objetivo)
           VALUES ('ahorro', ?, ?)""",
        (monto_objetivo, fecha_objetivo),
    )
    conn.commit()
    conn.close()
