"""Acceso a la base de datos SQLite y migraciones.

Cada fase nueva agrega una migración al final de MIGRATIONS. Nunca se edita una
migración ya aplicada: así la base de datos real se actualiza sin perder datos.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import current_app, g


def ahora() -> str:
    """Fecha y hora local del servidor (siempre la misma fuente para ambos PCs)."""
    return datetime.now().isoformat(sep=" ", timespec="seconds")


MIGRATIONS = [
    (
        1,
        """
        CREATE TABLE usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
            clave_hash TEXT NOT NULL,
            rol TEXT NOT NULL CHECK (rol IN ('administrador', 'director_tecnico', 'auxiliar')),
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            ultimo_ingreso TEXT
        );

        CREATE TABLE bitacora (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            accion TEXT NOT NULL,
            tabla TEXT,
            registro_id INTEGER,
            detalle TEXT,
            ip TEXT
        );
        CREATE INDEX idx_bitacora_fecha ON bitacora (fecha);

        -- La bitácora es un registro de auditoría: no se puede editar ni borrar.
        CREATE TRIGGER bitacora_no_editar BEFORE UPDATE ON bitacora
        BEGIN SELECT RAISE(ABORT, 'La bitácora no se puede modificar'); END;
        CREATE TRIGGER bitacora_no_borrar BEFORE DELETE ON bitacora
        BEGIN SELECT RAISE(ABORT, 'La bitácora no se puede borrar'); END;

        CREATE TABLE config (
            clave TEXT PRIMARY KEY,
            valor TEXT
        );
        """,

        
    ),
        (
        2,
        """
        CREATE TABLE proveedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nit TEXT NOT NULL UNIQUE,
            razon_social TEXT NOT NULL,
            nombre_comercial TEXT,
            contacto TEXT,
            telefono TEXT,
            correo TEXT,
            direccion TEXT,
            ciudad TEXT,
            concepto_sanitario TEXT,
            concepto_vence TEXT,
            certificaciones TEXT,
            observaciones TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT
        );
        CREATE INDEX idx_proveedores_razon ON proveedores (razon_social);
        CREATE INDEX idx_proveedores_activo ON proveedores (activo);

        CREATE TABLE productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE COLLATE NOCASE,
            codigo_barras TEXT,
            nombre TEXT NOT NULL,
            principio_activo TEXT,
            concentracion TEXT,
            forma_farmaceutica TEXT,
            registro_sanitario TEXT,
            registro_vence TEXT,
            fabricante TEXT,
            unidad TEXT,
            iva_tipo TEXT NOT NULL DEFAULT 'gravado'
                CHECK (iva_tipo IN ('excluido', 'exento', 'gravado')),
            iva_tarifa REAL NOT NULL DEFAULT 19.0,
            precio_venta REAL NOT NULL DEFAULT 0,
            precio_maximo REAL,
            stock_minimo INTEGER NOT NULL DEFAULT 0,
            requiere_formula INTEGER NOT NULL DEFAULT 0,
            cadena_frio INTEGER NOT NULL DEFAULT 0,
            control_especial INTEGER NOT NULL DEFAULT 0,
            observaciones TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT
        );
        CREATE INDEX idx_productos_codigo_barras ON productos (codigo_barras);
        CREATE INDEX idx_productos_nombre ON productos (nombre);
        CREATE INDEX idx_productos_activo ON productos (activo);
        """,
    ),
        (
        3,
        """
        CREATE TABLE zonas_temperatura (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
            descripcion TEXT,
            temp_min REAL NOT NULL,
            temp_max REAL NOT NULL,
            controla_humedad INTEGER NOT NULL DEFAULT 0,
            humedad_min REAL,
            humedad_max REAL,
            horarios TEXT NOT NULL DEFAULT '09:00,18:00',
            dias_semana TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7',
            activa INTEGER NOT NULL DEFAULT 1,
            minutos_tolerancia INTEGER NOT NULL DEFAULT 30,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT
        );

        CREATE TABLE equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'termohigrometro'
                CHECK (tipo IN ('termohigrometro', 'nevera', 'data_logger')),
            marca TEXT,
            modelo TEXT,
            serie TEXT,
            zona_id INTEGER,
            fecha_calibracion TEXT,
            proxima_calibracion TEXT,
            observaciones TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (zona_id) REFERENCES zonas_temperatura (id)
        );

        CREATE TABLE temperatura_registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zona_id INTEGER NOT NULL,
            equipo_id INTEGER,
            fecha TEXT NOT NULL,
            programada_para TEXT,
            temperatura REAL NOT NULL,
            humedad REAL,
            dentro_de_rango INTEGER NOT NULL DEFAULT 1,
            accion_correctiva TEXT,
            corregido_por INTEGER,
            corregido_en TEXT,
            observaciones TEXT,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (zona_id) REFERENCES zonas_temperatura (id),
            FOREIGN KEY (equipo_id) REFERENCES equipos (id)
        );
        CREATE INDEX idx_temp_reg_zona_fecha ON temperatura_registros (zona_id, fecha);
        CREATE INDEX idx_temp_reg_fecha ON temperatura_registros (fecha);
        """,
    ),
]


def conectar(ruta) -> sqlite3.Connection:
    conn = sqlite3.connect(str(ruta), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def init_db(ruta) -> int:
    """Crea la base si no existe y aplica las migraciones pendientes. Devuelve la versión final."""
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    conn = conectar(ruta)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, aplicada_en TEXT NOT NULL)"
        )
        conn.commit()
        actual = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        for version, sql in MIGRATIONS:
            if version > actual:
                try:
                    conn.executescript(
                        "BEGIN;\n"
                        + sql
                        + f"\nINSERT INTO schema_version (version, aplicada_en) VALUES ({version}, '{ahora()}');\nCOMMIT;"
                    )
                except Exception:
                    if conn.in_transaction:
                        conn.rollback()
                    raise
                actual = version
                        # Sembrar zonas típicas si la tabla está vacía.
        try:
            hay_zonas = conn.execute("SELECT 1 FROM zonas_temperatura LIMIT 1").fetchone()
            if not hay_zonas:
                from datetime import datetime as _dt
                semilla = [
                    ("Nevera", "Medicamentos refrigerados 2–8 °C", 2.0, 8.0, 1, 0.0, 75.0, "09:00,18:00", 0),
                    ("Ambiente", "Bodega y área de venta", 0.0, 30.0, 1, 0.0, 75.0, "09:00,18:00", 1),
                    ("Vitrina", "Mostrador principal", 0.0, 30.0, 0, None, None, "09:00", 0),
                    ("Cuarentena", "Producto en cuarentena", 0.0, 30.0, 0, None, None, "09:00", 0),
                ]
                for n, d, tmin, tmax, ch, hmin, hmax, hor, act in semilla:
                    conn.execute(
                        "INSERT INTO zonas_temperatura (nombre, descripcion, temp_min, temp_max, "
                        "controla_humedad, humedad_min, humedad_max, horarios, dias_semana, activa, "
                        "minutos_tolerancia, creado_en) VALUES (?,?,?,?,?,?,?,?, '1,2,3,4,5,6,7', ?, 30, ?)",
                        (n, d, tmin, tmax, ch, hmin, hmax, hor, act, _dt.now().isoformat(sep=" ", timespec="seconds")),
                    )
                conn.commit()
        except sqlite3.OperationalError:
            pass  # la tabla aún no existe (primera pasada): la sembrará en la siguiente ejecución
        return actual
    finally:
        conn.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = conectar(current_app.config["DB_PATH"])
    return g.db


def cerrar_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(cerrar_db)
