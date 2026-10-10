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

# Palabras parecidas para cada uso/síntoma (como las dice la gente en el mostrador).
# Se usan al sembrar una base nueva y en la migración 19 para bases existentes.
SINONIMOS_USOS = {
    "Dolor": "dolor de cabeza, cefalea, migraña, dolor muscular, dolor de muela, dolor de espalda",
    "Fiebre": "calentura, temperatura alta",
    "Inflamación": "hinchazón, golpe, esguince, torcedura",
    "Alergia": "rinitis, estornudos, picazón, ronchas, urticaria",
    "Tos": "tos seca, tos con flema, expectorante, carraspera",
    "Gripe": "gripa, resfriado, resfrío, catarro, malestar general",
    "Congestión nasal": "nariz tapada, mocos, sinusitis",
    "Acidez": "agrieras, reflujo, ardor de estómago, gastritis, indigestión",
    "Diarrea": "soltura, deposiciones, suero oral",
    "Estreñimiento": "estítico, no puede ir al baño, laxante",
    "Cólico menstrual": "cólicos, dolor de período, menstruación",
    "Cansancio": "decaimiento, fatiga, agotamiento",
    "Cicatrizante": "herida, cortada, raspón, quemadura",
    "Conjuntivitis": "ojo rojo, ojos irritados, lagañas",
    "Dermatitis": "irritación de piel, rasquiña, resequedad, pañalitis",
}

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
    (
        19,
        """
        -- ===== Limpieza =====
        -- Tabla vieja que ningún código usa (la reemplazó unidades_medida).
        DROP TABLE IF EXISTS presentaciones_producto;

        -- ===== Usos como buscador por síntoma =====
        -- Palabras como las dice la gente en el mostrador. Solo se llenan si la
        -- descripción está vacía (no se pisa lo que el usuario ya escribió).
        UPDATE catalogos SET descripcion = 'dolor de cabeza, cefalea, migraña, dolor muscular, dolor de muela, dolor de espalda' WHERE tipo = 'uso' AND nombre = 'Dolor' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'calentura, temperatura alta' WHERE tipo = 'uso' AND nombre = 'Fiebre' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'hinchazón, golpe, esguince, torcedura' WHERE tipo = 'uso' AND nombre = 'Inflamación' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'rinitis, estornudos, picazón, ronchas, urticaria' WHERE tipo = 'uso' AND nombre = 'Alergia' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'tos seca, tos con flema, expectorante, carraspera' WHERE tipo = 'uso' AND nombre = 'Tos' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'gripa, resfriado, resfrío, catarro, malestar general' WHERE tipo = 'uso' AND nombre = 'Gripe' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'nariz tapada, mocos, sinusitis' WHERE tipo = 'uso' AND nombre = 'Congestión nasal' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'agrieras, reflujo, ardor de estómago, gastritis, indigestión' WHERE tipo = 'uso' AND nombre = 'Acidez' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'soltura, deposiciones, suero oral' WHERE tipo = 'uso' AND nombre = 'Diarrea' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'estítico, no puede ir al baño, laxante' WHERE tipo = 'uso' AND nombre = 'Estreñimiento' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'cólicos, dolor de período, menstruación' WHERE tipo = 'uso' AND nombre = 'Cólico menstrual' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'decaimiento, fatiga, agotamiento' WHERE tipo = 'uso' AND nombre = 'Cansancio' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'herida, cortada, raspón, quemadura' WHERE tipo = 'uso' AND nombre = 'Cicatrizante' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'ojo rojo, ojos irritados, lagañas' WHERE tipo = 'uso' AND nombre = 'Conjuntivitis' AND (descripcion IS NULL OR descripcion = '');
        UPDATE catalogos SET descripcion = 'irritación de piel, rasquiña, resequedad, pañalitis' WHERE tipo = 'uso' AND nombre = 'Dermatitis' AND (descripcion IS NULL OR descripcion = '');
        """,
    ),
    (
        20,
        """
        -- ===== Venta por presentación (unidad / sobre / caja) =====
        -- El inventario SIEMPRE se cuenta en la unidad principal del producto
        -- (la de "Se vende por"). Aquí se guardan las OTRAS formas de venderlo,
        -- cada una con su precio. "factor" = cuántas unidades principales trae.
        -- Ejemplo: Acetaminofén (unidad principal: Tableta, $200)
        --          Sobre x 10  -> factor 10,  precio $1.800
        --          Caja x 100  -> factor 100, precio $15.000
        CREATE TABLE producto_presentaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            unidad_id INTEGER NOT NULL,          -- nombre tomado de unidades_medida
            factor REAL NOT NULL,                -- unidades principales que contiene (> 1)
            precio_venta REAL NOT NULL,
            precio_maximo REAL,                  -- tope regulado de ESTA presentación (opcional)
            codigo_barras TEXT,                  -- la caja suele tener otro código que la unidad
            creado_en TEXT NOT NULL,
            actualizado_en TEXT,
            FOREIGN KEY (producto_id) REFERENCES productos (id),
            FOREIGN KEY (unidad_id) REFERENCES unidades_medida (id),
            UNIQUE (producto_id, unidad_id)
        );
        CREATE INDEX idx_presentaciones_producto ON producto_presentaciones (producto_id);
        CREATE INDEX idx_presentaciones_barras ON producto_presentaciones (codigo_barras);

        -- Para saber qué presentación se vendió en cada línea
        ALTER TABLE venta_lineas ADD COLUMN presentacion_id INTEGER;
        """,
    ),
    (
        21,
        """
        -- ===== Estado de resultados (R2) =====
        -- Un retiro de la caja menor puede ser "plata que se lleva el dueño"
        -- (su ganancia) o solo mover dinero (consignar). Esta marca los separa:
        -- los retiros del dueño se muestran aparte en el estado de resultados.
        ALTER TABLE caja_menor_movimientos ADD COLUMN retiro_dueno INTEGER NOT NULL DEFAULT 0;

        -- Categoría de gasto para el sueldo del dueño. Solo se agrega aquí si la
        -- base ya tenía categorías (en una base nueva la siembra init_db).
        INSERT OR IGNORE INTO catalogos (tipo, nombre, activo, creado_en)
        SELECT 'categoria_gasto', 'Sueldo del dueño', 1, datetime('now', 'localtime')
        WHERE EXISTS (SELECT 1 FROM catalogos WHERE tipo = 'categoria_gasto');
        """,
    ),
    (
        22,
        """
        -- ===== Equipos y calibraciones =====
        -- 1) La tabla "equipos" (sin uso hasta ahora) solo aceptaba 3 tipos. SQLite no
        --    deja cambiar esa regla, así que se crea de nuevo con más tipos y con la
        --    frecuencia de calibración, se copian los datos y se cambia el nombre.
        CREATE TABLE equipos_nuevo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'termohigrometro'
                CHECK (tipo IN ('termohigrometro', 'nevera', 'data_logger', 'termometro',
                                'balanza', 'tensiometro', 'glucometro', 'otro')),
            marca TEXT,
            modelo TEXT,
            serie TEXT,
            zona_id INTEGER,                         -- zona de temperatura que mide (si aplica)
            fecha_calibracion TEXT,                  -- última calibración
            proxima_calibracion TEXT,                -- cuándo vence
            frecuencia_meses INTEGER NOT NULL DEFAULT 12,
            observaciones TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT,
            FOREIGN KEY (zona_id) REFERENCES zonas_temperatura (id)
        );
        INSERT INTO equipos_nuevo (id, nombre, tipo, marca, modelo, serie, zona_id, fecha_calibracion,
                                   proxima_calibracion, observaciones, activo, creado_en)
            SELECT id, nombre, tipo, marca, modelo, serie, zona_id, fecha_calibracion,
                   proxima_calibracion, observaciones, activo, creado_en FROM equipos;
        DROP TABLE equipos;
        ALTER TABLE equipos_nuevo RENAME TO equipos;
        CREATE INDEX idx_equipos_zona ON equipos (zona_id);

        -- 2) Historial: cada calibración queda guardada con su certificado
        CREATE TABLE calibraciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,                     -- día en que se calibró
            proxima TEXT NOT NULL,                   -- vence
            empresa TEXT,                            -- laboratorio que calibró
            certificado_numero TEXT,
            resultado TEXT NOT NULL DEFAULT 'conforme'
                CHECK (resultado IN ('conforme', 'no_conforme')),
            archivo TEXT,                            -- certificado escaneado (PDF o foto)
            observaciones TEXT,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (equipo_id) REFERENCES equipos (id)
        );
        CREATE INDEX idx_calibraciones_equipo ON calibraciones (equipo_id);
        """,
    ),
    (
        23,
        """
        -- ===== Devoluciones =====
        -- tipo 'cliente':   un cliente devuelve algo que compró (sale de una venta).
        -- tipo 'proveedor': se le devuelve mercancía al proveedor (vencidos, averías...).
        CREATE TABLE devoluciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,              -- DC-0001 (cliente) / DP-0001 (proveedor)
            tipo TEXT NOT NULL CHECK (tipo IN ('cliente', 'proveedor')),
            fecha TEXT NOT NULL,
            venta_id INTEGER,                         -- cliente: venta de origen
            proveedor_id INTEGER,                     -- proveedor: a quién se devuelve
            motivo TEXT NOT NULL,
            forma_reembolso TEXT,                     -- cliente: efectivo, nequi, davivienda, tarjeta
            caja_id INTEGER,                          -- caja de la que salió el reembolso
            con_credito INTEGER NOT NULL DEFAULT 1,   -- proveedor: 1 = reconoce el valor (nota crédito o cambio)
            nota_credito TEXT,                        -- proveedor: número de la nota crédito
            subtotal REAL NOT NULL DEFAULT 0,         -- sin IVA
            iva REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,            -- cliente: lo que se le devolvió; proveedor: valor al costo
            costo REAL NOT NULL DEFAULT 0,            -- costo de la mercancía devuelta
            usuario_id INTEGER,
            usuario_nombre TEXT,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas (id),
            FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        );
        CREATE INDEX idx_devoluciones_fecha ON devoluciones (fecha);
        CREATE INDEX idx_devoluciones_venta ON devoluciones (venta_id);

        CREATE TABLE devolucion_lineas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            devolucion_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            producto_nombre TEXT NOT NULL,
            venta_linea_id INTEGER,                   -- cliente: línea de la venta
            lote_id INTEGER,                          -- proveedor: lote que sale
            presentacion TEXT,
            cantidad REAL NOT NULL,                   -- en la presentación vendida (cliente) o unidades (proveedor)
            unidades REAL NOT NULL,                   -- unidades del inventario (cantidad x factor)
            destino TEXT NOT NULL CHECK (destino IN ('reingreso', 'baja', 'proveedor')),
            subtotal REAL NOT NULL DEFAULT 0,
            iva REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            costo REAL NOT NULL DEFAULT 0,
            lotes_json TEXT,                          -- a qué lotes volvió (reingreso)
            FOREIGN KEY (devolucion_id) REFERENCES devoluciones (id) ON DELETE CASCADE
        );
        CREATE INDEX idx_devolucion_lineas_dev ON devolucion_lineas (devolucion_id);
        CREATE INDEX idx_devolucion_lineas_venta ON devolucion_lineas (venta_linea_id);
        """,
    ),
    (
        24,
        """
        -- ===== Temas (apariencia) =====
        -- Cada usuario escoge cómo se ve el programa: 'verde' (por defecto),
        -- 'azul' o 'clasico' (el aspecto que tenía antes del rediseño).
        ALTER TABLE usuarios ADD COLUMN tema TEXT NOT NULL DEFAULT 'verde';
        """,
    ),
    (
        25,
        """
        -- ===== Venta libre y otros ingresos =====
        -- 1) VENTA LIBRE: vender algo que NO está en el inventario (una
        --    inyectología, una toma de presión...). Esas líneas no tienen
        --    producto, así que producto_id debe poder quedar vacío (NULL).
        --    SQLite no deja quitar el "NOT NULL" de una columna: se crea la
        --    tabla de nuevo, se copian los datos y se cambia el nombre.
        --    Columnas nuevas:
        --      es_libre    = 1 si la línea es venta libre
        --      costo_libre = lo que le cuesta a la droguería CADA UNA (opcional,
        --                    para que Utilidades calcule bien la ganancia)
        CREATE TABLE venta_lineas_nueva (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER,                      -- vacío en las líneas de venta libre
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
            precio_original REAL,
            motivo_precio TEXT,
            presentacion_id INTEGER,
            es_libre INTEGER NOT NULL DEFAULT 0,
            costo_libre REAL,
            FOREIGN KEY (venta_id) REFERENCES ventas (id) ON DELETE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos (id)
        );
        INSERT INTO venta_lineas_nueva (id, venta_id, producto_id, producto_codigo, producto_nombre,
                presentacion, factor, cantidad, precio_unitario, descuento_linea, iva_tipo, iva_tarifa,
                subtotal, iva_valor, total, lotes_json, precio_original, motivo_precio, presentacion_id)
            SELECT id, venta_id, producto_id, producto_codigo, producto_nombre,
                presentacion, factor, cantidad, precio_unitario, descuento_linea, iva_tipo, iva_tarifa,
                subtotal, iva_valor, total, lotes_json, precio_original, motivo_precio, presentacion_id
            FROM venta_lineas;
        DROP TABLE venta_lineas;
        ALTER TABLE venta_lineas_nueva RENAME TO venta_lineas;
        CREATE INDEX idx_venta_lineas_venta ON venta_lineas (venta_id);
        CREATE INDEX idx_venta_lineas_producto ON venta_lineas (producto_id);

        -- 2) OTROS INGRESOS: plata que entra y NO es una venta (comisión de
        --    recargas, arriendo de un espacio, reciclaje...). Es el "espejo"
        --    de la tabla gastos.
        --    origen: 'pos' = entró a la caja del POS abierta; 'ninguna' = no
        --    pasó por la caja (ej: llegó al banco).
        CREATE TABLE otros_ingresos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            categoria_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL,
            monto REAL NOT NULL DEFAULT 0,
            forma_pago TEXT NOT NULL DEFAULT 'efectivo'
                CHECK (forma_pago IN ('efectivo', 'nequi', 'davivienda', 'tarjeta', 'transferencia')),
            origen TEXT NOT NULL DEFAULT 'ninguna' CHECK (origen IN ('pos', 'ninguna')),
            caja_id INTEGER,
            comprobante TEXT,
            observaciones TEXT,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT,
            FOREIGN KEY (categoria_id) REFERENCES catalogos (id),
            FOREIGN KEY (caja_id) REFERENCES cajas (id)
        );
        CREATE INDEX idx_otros_ingresos_fecha ON otros_ingresos (fecha);

        -- Las categorías de ingreso se siembran en init_db (más abajo), igual que
        -- las de gasto: si se sembraran aquí, la siembra general de catálogos
        -- creería que ya hay catálogos y no pondría los demás.
        """,
    ),
    (
        26,
        """
        -- ===== Cartera (cuentas por cobrar) =====
        -- 1) CLIENTES registrados: solo a ellos se les puede vender a crédito.
        --    cupo = hasta cuánto pueden deber (vacío = sin límite).
        CREATE TABLE clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            documento TEXT,                          -- cédula o NIT
            telefono TEXT,
            direccion TEXT,
            cupo REAL,                               -- NULL = sin límite
            observaciones TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT
        );
        -- No puede haber dos clientes con el mismo documento
        CREATE UNIQUE INDEX idx_clientes_documento ON clientes (documento)
            WHERE documento IS NOT NULL AND documento <> '';

        -- 2) A qué cliente registrado se le hizo la venta (las ventas a crédito
        --    siempre lo tienen; forma_pago = 'credito').
        ALTER TABLE ventas ADD COLUMN cliente_id INTEGER REFERENCES clientes (id);
        CREATE INDEX idx_ventas_cliente ON ventas (cliente_id);

        -- 3) ABONOS: lo que el cliente va pagando de su deuda (AB-0001...).
        --    Si es en efectivo (o Nequi/Davivienda) con la caja abierta, también
        --    queda como "ingreso" en caja_movimientos para que el cierre cuadre.
        CREATE TABLE cartera_abonos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            cliente_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            monto REAL NOT NULL,
            forma_pago TEXT NOT NULL
                CHECK (forma_pago IN ('efectivo', 'nequi', 'davivienda', 'tarjeta', 'transferencia')),
            caja_id INTEGER,                         -- caja donde entró la plata (si aplica)
            observaciones TEXT,
            usuario_id INTEGER,
            usuario_nombre TEXT,
            anulado INTEGER NOT NULL DEFAULT 0,
            anulado_motivo TEXT,
            anulado_en TEXT,
            anulado_por_nombre TEXT,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (caja_id) REFERENCES cajas (id)
        );
        CREATE INDEX idx_abonos_cliente ON cartera_abonos (cliente_id);
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
                    "laboratorio": [],
                    "principio": [],
                }
                for tipo, nombres in semillas.items():
                    for nombre in nombres:
                        # Los usos se siembran con sus sinónimos para el buscador por síntoma
                        descripcion = SINONIMOS_USOS.get(nombre) if tipo == "uso" else None
                        conn.execute(
                            "INSERT INTO catalogos (tipo, nombre, descripcion, activo, creado_en) "
                            "VALUES (?, ?, ?, 1, ?)",
                            (tipo, nombre, descripcion, _ahora),
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
                    "Sueldo del dueño",
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

        # Sembrar categorías de OTROS INGRESOS (si no existen)
        try:
            if not conn.execute("SELECT 1 FROM catalogos WHERE tipo = 'categoria_ingreso' LIMIT 1").fetchone():
                from datetime import datetime as _dt
                _ahora = _dt.now().isoformat(sep=" ", timespec="seconds")
                for nombre in ["Comisiones (recargas, pagos de servicios)", "Arriendo de espacios",
                               "Reciclaje y aprovechamientos", "Reintegros y reembolsos",
                               "Intereses bancarios", "Otros"]:
                    conn.execute(
                        "INSERT OR IGNORE INTO catalogos (tipo, nombre, activo, creado_en) "
                        "VALUES ('categoria_ingreso', ?, 1, ?)", (nombre, _ahora))
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
