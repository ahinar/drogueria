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
    (
        4,
        """
        CREATE TABLE catalogos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT,
            UNIQUE (tipo, nombre)
        );
        CREATE INDEX idx_catalogos_tipo ON catalogos (tipo);
        CREATE INDEX idx_catalogos_activo ON catalogos (activo);
        """,
    ),
    (
        5,
        """
        ALTER TABLE productos ADD COLUMN descripcion TEXT;
        ALTER TABLE productos ADD COLUMN grupo TEXT;
        ALTER TABLE productos ADD COLUMN precio_compra REAL NOT NULL DEFAULT 0;
        ALTER TABLE productos ADD COLUMN principio_id INTEGER;
        ALTER TABLE productos ADD COLUMN laboratorio_id INTEGER;
        ALTER TABLE productos ADD COLUMN forma_farmaceutica_id INTEGER;
        ALTER TABLE productos ADD COLUMN maneja_vencimiento INTEGER NOT NULL DEFAULT 1;

        UPDATE catalogos SET tipo = 'forma_farmaceutica' WHERE tipo = 'presentacion';
        UPDATE catalogos SET activo = 0 WHERE tipo = 'medida';

        CREATE TABLE productos_categorias (
            producto_id INTEGER NOT NULL,
            catalogo_id INTEGER NOT NULL,
            PRIMARY KEY (producto_id, catalogo_id),
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE CASCADE,
            FOREIGN KEY (catalogo_id) REFERENCES catalogos (id) ON DELETE CASCADE
        );

        CREATE TABLE productos_usos (
            producto_id INTEGER NOT NULL,
            catalogo_id INTEGER NOT NULL,
            PRIMARY KEY (producto_id, catalogo_id),
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE CASCADE,
            FOREIGN KEY (catalogo_id) REFERENCES catalogos (id) ON DELETE CASCADE
        );

        CREATE TABLE presentaciones_producto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            factor INTEGER NOT NULL DEFAULT 1,
            precio REAL NOT NULL DEFAULT 0,
            codigo_barras TEXT,
            es_compra INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE CASCADE
        );
        CREATE INDEX idx_presentaciones_producto ON presentaciones_producto (producto_id);
        """,
    ),
    (
        6,
        """
        UPDATE catalogos SET tipo = 'forma_farmaceutica' WHERE tipo = 'presentacion';
        UPDATE catalogos SET activo = 0 WHERE tipo = 'medida';
        """,
    ),
    (
        7,
        """
        CREATE TABLE unidades_medida (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
            cantidad REAL NOT NULL DEFAULT 1,
            referencia_id INTEGER,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT,
            FOREIGN KEY (referencia_id) REFERENCES unidades_medida (id)
        );
        CREATE INDEX idx_unidades_activo ON unidades_medida (activo);

        ALTER TABLE productos ADD COLUMN unidad_venta_id INTEGER;
        """,
    ),
    (
        8,
        """
        CREATE TABLE recepciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            fecha TEXT NOT NULL,
            proveedor_id INTEGER NOT NULL,
            factura_numero TEXT,
            remision_numero TEXT,
            temperatura_llegada REAL,
            estado TEXT NOT NULL DEFAULT 'borrador'
                CHECK (estado IN ('borrador', 'cuarentena', 'aprobada', 'rechazada')),
            recibido_por INTEGER,
            recibido_por_nombre TEXT,
            aprobado_por INTEGER,
            aprobado_por_nombre TEXT,
            aprobado_en TEXT,
            observaciones TEXT,
            pdf_ruta TEXT,
            foto_ruta TEXT,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        );
        CREATE INDEX idx_recepciones_fecha ON recepciones (fecha);
        CREATE INDEX idx_recepciones_estado ON recepciones (estado);
        CREATE INDEX idx_recepciones_proveedor ON recepciones (proveedor_id);

        CREATE TABLE recepcion_lineas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recepcion_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            lote TEXT,
            vencimiento TEXT,
            cantidad_facturada REAL NOT NULL DEFAULT 0,
            cantidad_recibida REAL NOT NULL DEFAULT 0,
            costo_unitario REAL NOT NULL DEFAULT 0,
            estado_empaque TEXT NOT NULL DEFAULT 'bueno'
                CHECK (estado_empaque IN ('bueno', 'dañado', 'roto', 'otro')),
            resultado TEXT NOT NULL DEFAULT 'aceptado'
                CHECK (resultado IN ('aceptado', 'cuarentena', 'rechazado')),
            motivo_rechazo TEXT,
            observaciones TEXT,
            FOREIGN KEY (recepcion_id) REFERENCES recepciones (id) ON DELETE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        );
        CREATE INDEX idx_recepcion_lineas_rec ON recepcion_lineas (recepcion_id);
        CREATE INDEX idx_recepcion_lineas_producto ON recepcion_lineas (producto_id);

        CREATE TABLE lotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            lote TEXT,
            vencimiento TEXT,
            cantidad_inicial REAL NOT NULL DEFAULT 0,
            cantidad_disponible REAL NOT NULL DEFAULT 0,
            costo_unitario REAL NOT NULL DEFAULT 0,
            estado TEXT NOT NULL DEFAULT 'cuarentena'
                CHECK (estado IN ('cuarentena', 'disponible', 'bloqueado', 'agotado', 'rechazado')),
            motivo_bloqueo TEXT,
            recepcion_id INTEGER,
            recepcion_linea_id INTEGER,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT,
            FOREIGN KEY (producto_id) REFERENCES productos (id),
            FOREIGN KEY (recepcion_id) REFERENCES recepciones (id),
            FOREIGN KEY (recepcion_linea_id) REFERENCES recepcion_lineas (id)
        );
        CREATE INDEX idx_lotes_producto ON lotes (producto_id);
        CREATE INDEX idx_lotes_vencimiento ON lotes (vencimiento);
        CREATE INDEX idx_lotes_estado ON lotes (estado);

        CREATE TABLE movimientos_inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            lote_id INTEGER,
            producto_id INTEGER NOT NULL,
            tipo TEXT NOT NULL
                CHECK (tipo IN ('recepcion', 'venta', 'devolucion', 'ajuste', 'baja', 'traslado')),
            cantidad REAL NOT NULL,
            referencia TEXT,
            referencia_id INTEGER,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            observaciones TEXT,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (lote_id) REFERENCES lotes (id),
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        );
        CREATE INDEX idx_mov_inv_fecha ON movimientos_inventario (fecha);
        CREATE INDEX idx_mov_inv_producto ON movimientos_inventario (producto_id);
        CREATE INDEX idx_mov_inv_lote ON movimientos_inventario (lote_id);
        """,
    ),
    (
        9,
        """
        ALTER TABLE recepcion_lineas ADD COLUMN temperatura_ingreso REAL;
        ALTER TABLE recepcion_lineas ADD COLUMN clasificacion_defecto TEXT;
        """,
    ),
    (
        10,
        """
        ALTER TABLE productos ADD COLUMN creado_en_importacion INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    (
        11,
        """
        ALTER TABLE productos ADD COLUMN imagen TEXT;
        """,
    ),
    (
        12,
        """
        CREATE TABLE cajas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            abierta_en TEXT NOT NULL,
            abierta_por INTEGER,
            abierta_por_nombre TEXT,
            efectivo_inicial REAL NOT NULL DEFAULT 0,
            cerrada_en TEXT,
            cerrada_por INTEGER,
            cerrada_por_nombre TEXT,
            efectivo_contado REAL,
            diferencia REAL,
            observaciones_apertura TEXT,
            observaciones_cierre TEXT,
            estado TEXT NOT NULL DEFAULT 'abierta'
                CHECK (estado IN ('abierta', 'cerrada'))
        );
        CREATE INDEX idx_cajas_estado ON cajas (estado);
        CREATE INDEX idx_cajas_fecha ON cajas (abierta_en);

        CREATE TABLE ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consecutivo TEXT NOT NULL UNIQUE,
            fecha TEXT NOT NULL,
            caja_id INTEGER NOT NULL,
            cliente_nombre TEXT NOT NULL DEFAULT 'Consumidor final',
            cliente_documento TEXT,
            subtotal REAL NOT NULL DEFAULT 0,
            descuento REAL NOT NULL DEFAULT 0,
            iva REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            forma_pago TEXT NOT NULL DEFAULT 'efectivo',
            monto_recibido REAL,
            cambio REAL,
            observaciones TEXT,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            estado TEXT NOT NULL DEFAULT 'completada'
                CHECK (estado IN ('completada', 'anulada')),
            motivo_anulacion TEXT,
            anulada_en TEXT,
            anulada_por INTEGER,
            anulada_por_nombre TEXT,
            creado_en TEXT NOT NULL,
            factura_numero TEXT,
            cufe TEXT,
            estado_dian TEXT,
            pdf_ruta TEXT,
            xml_ruta TEXT,
            FOREIGN KEY (caja_id) REFERENCES cajas (id)
        );
        CREATE INDEX idx_ventas_fecha ON ventas (fecha);
        CREATE INDEX idx_ventas_estado ON ventas (estado);
        CREATE INDEX idx_ventas_caja ON ventas (caja_id);

        CREATE TABLE venta_lineas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            producto_codigo TEXT NOT NULL,
            producto_nombre TEXT NOT NULL,
            presentacion TEXT,
            factor REAL NOT NULL DEFAULT 1,
            cantidad REAL NOT NULL DEFAULT 1,
            precio_unitario REAL NOT NULL DEFAULT 0,
            descuento_linea REAL NOT NULL DEFAULT 0,
            iva_tipo TEXT NOT NULL DEFAULT 'gravado',
            iva_tarifa REAL NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL DEFAULT 0,
            iva_valor REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            lotes_json TEXT,
            FOREIGN KEY (venta_id) REFERENCES ventas (id) ON DELETE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        );
        CREATE INDEX idx_venta_lineas_venta ON venta_lineas (venta_id);
        CREATE INDEX idx_venta_lineas_producto ON venta_lineas (producto_id);
        """,
    ),
    (
        13,
        """
        ALTER TABLE cajas ADD COLUMN detalle_apertura TEXT;
        ALTER TABLE cajas ADD COLUMN detalle_cierre TEXT;
        """,
    ),
    (
        14,
        """
        CREATE TABLE caja_movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caja_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('ingreso', 'salida')),
            forma_pago TEXT NOT NULL DEFAULT 'efectivo'
                CHECK (forma_pago IN ('efectivo', 'nequi', 'davivienda', 'tarjeta')),
            monto REAL NOT NULL DEFAULT 0,
            motivo TEXT,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (caja_id) REFERENCES cajas (id)
        );
        CREATE INDEX idx_caja_mov_caja ON caja_movimientos (caja_id);
        CREATE INDEX idx_caja_mov_fecha ON caja_movimientos (fecha);
        """,
    ),
    (
        15,
        """
        CREATE TABLE gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            categoria_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL,
            monto REAL NOT NULL DEFAULT 0,
            forma_pago TEXT NOT NULL DEFAULT 'efectivo'
                CHECK (forma_pago IN ('efectivo', 'nequi', 'davivienda', 'tarjeta', 'transferencia')),
            proveedor_id INTEGER,
            comprobante TEXT,
            observaciones TEXT,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT,
            FOREIGN KEY (categoria_id) REFERENCES catalogos (id),
            FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        );
        CREATE INDEX idx_gastos_fecha ON gastos (fecha);
        CREATE INDEX idx_gastos_categoria ON gastos (categoria_id);
        CREATE INDEX idx_gastos_activo ON gastos (activo);
        """,
    ),
    (
        16,
        """
        -- ===== Caja menor (fondo permanente de dinero) =====
        CREATE TABLE caja_menor_movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('aporte', 'retiro', 'apertura_pos', 'cierre_pos', 'gasto')),
            monto REAL NOT NULL DEFAULT 0,
            motivo TEXT,
            caja_id INTEGER,
            gasto_id INTEGER,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            creado_en TEXT NOT NULL
        );
        CREATE INDEX idx_caja_menor_fecha ON caja_menor_movimientos (fecha);
        CREATE INDEX idx_caja_menor_tipo ON caja_menor_movimientos (tipo);

        -- Vínculos para trazabilidad (apertura y cierre del POS)
        ALTER TABLE cajas ADD COLUMN caja_menor_apertura_id INTEGER;
        ALTER TABLE cajas ADD COLUMN caja_menor_cierre_id INTEGER;

        -- Los gastos ahora saben de qué caja salieron
        ALTER TABLE gastos ADD COLUMN origen TEXT NOT NULL DEFAULT 'general';
        ALTER TABLE gastos ADD COLUMN caja_id INTEGER;
        """,
    ),
    (
        17,
        """
        -- ===== Cambios de precio al vender (Opción B) =====
        ALTER TABLE venta_lineas ADD COLUMN precio_original REAL;
        ALTER TABLE venta_lineas ADD COLUMN motivo_precio TEXT;
        """,
    ),
    (
        18,
        """
        -- ===== Toma de inventario (conteo físico) =====
        -- Un "conteo" es una jornada de contar la mercancía.
        -- Mientras está 'abierto' se van anotando cantidades; al 'aplicarlo'
        -- se corrigen los lotes. 'anulado' = se descartó sin tocar nada.
        CREATE TABLE conteos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,              -- CNT-0001, CNT-0002...
            descripcion TEXT,
            categoria_id INTEGER,                     -- NULL = toda la droguería
            estado TEXT NOT NULL DEFAULT 'abierto'
                CHECK (estado IN ('abierto', 'aplicado', 'anulado')),
            creado_en TEXT NOT NULL,
            creado_por INTEGER,
            creado_por_nombre TEXT,
            aplicado_en TEXT,
            aplicado_por INTEGER,
            aplicado_por_nombre TEXT,
            observaciones TEXT,
            FOREIGN KEY (categoria_id) REFERENCES catalogos (id)
        );

        -- Una línea por cada lote contado.
        -- lote_id NULL = lote que apareció en la estantería y no estaba en el sistema;
        -- se crea al aplicar el conteo.
        CREATE TABLE conteo_lineas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conteo_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            lote_id INTEGER,
            lote TEXT,
            vencimiento TEXT,
            costo_unitario REAL NOT NULL DEFAULT 0,
            cantidad_sistema REAL NOT NULL DEFAULT 0,   -- lo que decía el sistema AL MOMENTO de contar
            cantidad_contada REAL NOT NULL,
            diferencia_aplicada REAL,                   -- se llena al aplicar
            contado_en TEXT NOT NULL,
            contado_por INTEGER,
            contado_por_nombre TEXT,
            FOREIGN KEY (conteo_id) REFERENCES conteos (id),
            FOREIGN KEY (producto_id) REFERENCES productos (id),
            FOREIGN KEY (lote_id) REFERENCES lotes (id)
        );
        CREATE INDEX idx_conteo_lineas_conteo ON conteo_lineas (conteo_id);
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

def _asegurar_columnas_productos(conn):
    """Agrega columnas faltantes en productos (por si una migración se aplicó antes)."""
    existentes = {r[1] for r in conn.execute("PRAGMA table_info(productos)").fetchall()}
    requeridas = [
        ("descripcion", "TEXT"),
        ("grupo", "TEXT"),
        ("precio_compra", "REAL NOT NULL DEFAULT 0"),
        ("principio_id", "INTEGER"),
        ("laboratorio_id", "INTEGER"),
        ("forma_farmaceutica_id", "INTEGER"),
        ("maneja_vencimiento", "INTEGER NOT NULL DEFAULT 1"),
        ("unidad_venta_id", "INTEGER"),
    ]
    cambios = False
    for nombre, tipo in requeridas:
        if nombre not in existentes:
            conn.execute(f"ALTER TABLE productos ADD COLUMN {nombre} {tipo}")
            cambios = True
    if cambios:
        conn.commit()

def _asegurar_columnas_recepcion_lineas(conn):
    """Agrega columnas faltantes en recepcion_lineas."""
    try:
        existentes = {r[1] for r in conn.execute("PRAGMA table_info(recepcion_lineas)").fetchall()}
    except sqlite3.OperationalError:
        return
    requeridas = [
        ("temperatura_ingreso", "REAL"),
        ("clasificacion_defecto", "TEXT"),
    ]
    cambios = False
    for nombre, tipo in requeridas:
        if nombre not in existentes:
            conn.execute(f"ALTER TABLE recepcion_lineas ADD COLUMN {nombre} {tipo}")
            cambios = True
    if cambios:
        conn.commit()

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

        # Sembrar zonas típicas
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
                        (n, d, tmin, tmax, ch, hmin, hmax, hor, act,
                         _dt.now().isoformat(sep=" ", timespec="seconds")),
                    )
                conn.commit()
        except sqlite3.OperationalError:
            pass

        # Sembrar catálogos típicos
        try:
            hay_catalogos = conn.execute("SELECT 1 FROM catalogos LIMIT 1").fetchone()
            if not hay_catalogos:
                from datetime import datetime as _dt
                _ahora = _dt.now().isoformat(sep=" ", timespec="seconds")
                semillas = {
                    "categoria": [
                        "Analgésicos", "Antiinflamatorios", "Antibióticos",
                        "Antihistamínicos", "Antigripales", "Crónicos y de control",
                        "Dermatológicos", "Gastrointestinales", "Vitaminas y suplementos",
                        "Cuidado personal e higiene", "Belleza y cosméticos",
                        "Dispositivos médicos y ayudas", "Naturales y homeopáticos",
                        "Línea infantil y bebés", "Control especial (FNE)",
                    ],
                    "forma_farmaceutica": [
                        "Tableta", "Cápsula", "Jarabe", "Suspensión", "Crema",
                        "Gel", "Gotas", "Inyectable", "Supositorio", "Óvulo",
                        "Parche", "Polvo", "Óvulo vaginal", "Sobre",
                    ],
                    "uso": [
                        "Dolor", "Fiebre", "Inflamación", "Alergia", "Tos",
                        "Gripe", "Congestión nasal", "Hipertensión", "Diabetes",
                        "Colesterol", "Infección", "Diarrea", "Estreñimiento",
                        "Acidez", "Cólico menstrual", "Cansancio",
                        "Deficiencia de vitaminas", "Cicatrizante",
                        "Conjuntivitis", "Dermatitis",
                    ],
                    "tipo_pago": ["Efectivo", "Tarjeta", "Davivienda", "Nequi"],
                    "laboratorio": [],
                    "principio": [],
                }
                for tipo, nombres in semillas.items():
                    for nombre in nombres:
                        conn.execute(
                            "INSERT INTO catalogos (tipo, nombre, activo, creado_en) "
                            "VALUES (?, ?, 1, ?)",
                            (tipo, nombre, _ahora),
                        )
                conn.commit()
        except sqlite3.OperationalError:
            pass

        # Sembrar unidad base "Unidad"
        try:
            hay = conn.execute("SELECT 1 FROM unidades_medida LIMIT 1").fetchone()
            if not hay:
                from datetime import datetime as _dt
                conn.execute(
                    "INSERT INTO unidades_medida (nombre, cantidad, referencia_id, activo, creado_en) "
                    "VALUES ('Unidad', 1, NULL, 1, ?)",
                    (_dt.now().isoformat(sep=" ", timespec="seconds"),),
                )
                conn.commit()
        except sqlite3.OperationalError:
            pass

        # Sembrar categorías de gasto (si no existen)
        try:
            hay_cat_gasto = conn.execute(
                "SELECT 1 FROM catalogos WHERE tipo = 'categoria_gasto' LIMIT 1"
            ).fetchone()
            if not hay_cat_gasto:
                from datetime import datetime as _dt
                _ahora = _dt.now().isoformat(sep=" ", timespec="seconds")
                cats_gasto = [
                    "Arriendo",
                    "Servicios públicos",
                    "Nómina",
                    "Papelería y suministros",
                    "Mantenimiento y reparaciones",
                    "Publicidad",
                    "Domicilios",
                    "Impuestos (ICA, predial)",
                    "Gastos bancarios",
                    "Aseo y cafetería",
                    "Otros",
                ]
                for nombre in cats_gasto:
                    conn.execute(
                        "INSERT OR IGNORE INTO catalogos (tipo, nombre, activo, creado_en) "
                        "VALUES ('categoria_gasto', ?, 1, ?)",
                        (nombre, _ahora),
                    )
                conn.commit()
        except sqlite3.OperationalError:
            pass

        # Asegurar columnas
        _asegurar_columnas_productos(conn)
        _asegurar_columnas_recepcion_lineas(conn)

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
