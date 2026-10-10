"""
CAMBIAR LA UNIDAD DE INVENTARIO de un producto que ya tiene movimientos.

¿Por qué hace falta un asistente?
    Todas las cantidades guardadas de un producto (lotes, kardex, ventas,
    recepciones, conteos) están en su unidad de inventario. Si solo se
    cambia el nombre de la unidad, 308 TABLETAS pasan a leerse como
    308 SOBRES (eso le pasó a Fernando con el acetaminofén).

Este asistente ofrece dos caminos:
    1. CORREGIR EL NOMBRE (factor 1): las cantidades ya estaban en la unidad
       nueva y solo el nombre estaba mal. No se cambia ningún número.
    2. CONVERTIR (factor N = cuántas unidades nuevas trae 1 unidad vieja):
       ej. de "Caja x 100" a "Tableta" -> N = 100. Se multiplican TODAS las
       cantidades por N, se dividen los costos por unidad entre N, las
       presentaciones se ajustan, y la unidad vieja pasa a ser una
       presentación más (con su precio de antes), así el POS la sigue vendiendo.

Todo se hace en una sola transacción (o se cambia todo, o nada) y queda en
la bitácora.
"""
import json

from .db import ahora


class UnidadError(Exception):
    """Error que se le muestra a la persona tal cual."""


def _por(lista_json, n):
    """Multiplica por n las cantidades de un lotes_json ([{lote_id, cantidad}, ...])."""
    datos = json.loads(lista_json or "[]")
    for d in datos:
        d["cantidad"] = round(d.get("cantidad", 0) * n, 4)
    return json.dumps(datos, ensure_ascii=False)


def cambiar(db, producto, unidad_nueva_id, factor, precio_nuevo=None, maximo_nuevo=None):
    """Cambia la unidad de inventario. Devuelve un texto para la bitácora.

    producto        -> fila de productos (con unidad_venta_id)
    unidad_nueva_id -> id de unidades_medida
    factor          -> cuántas unidades NUEVAS trae 1 unidad VIEJA (1 = solo corregir el nombre)
    precio_nuevo / maximo_nuevo -> precio de 1 unidad nueva (si se convierte)
    """
    pid = producto["id"]
    vieja_id = producto["unidad_venta_id"]
    if not unidad_nueva_id:
        raise UnidadError("Escoge la unidad nueva.")
    if unidad_nueva_id == vieja_id:
        raise UnidadError("Esa ya es la unidad de inventario.")
    nueva = db.execute("SELECT * FROM unidades_medida WHERE id = ?", (unidad_nueva_id,)).fetchone()
    if nueva is None:
        raise UnidadError("Esa unidad no existe.")
    if factor is None or factor < 1:
        raise UnidadError("El factor debe ser 1 o más: la unidad nueva tiene que ser igual o más "
                          "pequeña que la de ahora (ej. de Caja a Tableta).")
    if db.execute("SELECT 1 FROM producto_presentaciones WHERE producto_id = ? AND unidad_id = ?",
                  (pid, unidad_nueva_id)).fetchone():
        raise UnidadError(f"'{nueva['nombre']}' ya es una presentación de este producto. "
                          "Quítala de las presentaciones (en la ficha) y vuelve a intentarlo.")
    vieja = db.execute("SELECT nombre FROM unidades_medida WHERE id = ?", (vieja_id,)).fetchone()
    nombre_viejo = vieja["nombre"] if vieja else "unidad anterior"
    n = float(factor)

    db.execute("BEGIN IMMEDIATE")
    try:
        if n != 1:
            # ---- Cantidades x N y costos por unidad ÷ N, en todas las tablas ----
            db.execute("UPDATE lotes SET cantidad_inicial = cantidad_inicial * ?, "
                       "cantidad_disponible = cantidad_disponible * ?, costo_unitario = costo_unitario / ? "
                       "WHERE producto_id = ?", (n, n, n, pid))
            db.execute("UPDATE movimientos_inventario SET cantidad = cantidad * ? WHERE producto_id = ?", (n, pid))
            db.execute("UPDATE conteo_lineas SET cantidad_sistema = cantidad_sistema * ?, "
                       "cantidad_contada = cantidad_contada * ?, "
                       "diferencia_aplicada = diferencia_aplicada * ?, costo_unitario = costo_unitario / ? "
                       "WHERE producto_id = ?", (n, n, n, n, pid))
            # Recepciones: se guardan en unidades; la presentación en que llegó se conserva
            db.execute("UPDATE recepcion_lineas SET cantidad_facturada = cantidad_facturada * ?, "
                       "cantidad_recibida = cantidad_recibida * ?, costo_unitario = costo_unitario / ?, "
                       "factor = COALESCE(factor, 1) * ?, presentacion = COALESCE(presentacion, ?) "
                       "WHERE producto_id = ?", (n, n, n, n, nombre_viejo, pid))
            # Ventas: lo vendido (1 sobre) sigue igual; cambia cuántas unidades era (factor)
            for v in db.execute("SELECT id, lotes_json FROM venta_lineas WHERE producto_id = ?", (pid,)).fetchall():
                db.execute("UPDATE venta_lineas SET factor = COALESCE(factor, 1) * ?, lotes_json = ? WHERE id = ?",
                           (n, _por(v["lotes_json"], n), v["id"]))
            for d in db.execute("SELECT id, lotes_json FROM devolucion_lineas WHERE producto_id = ?", (pid,)).fetchall():
                db.execute("UPDATE devolucion_lineas SET unidades = unidades * ?, lotes_json = ? WHERE id = ?",
                           (n, _por(d["lotes_json"], n), d["id"]))
            # Presentaciones: un sobre que traía 1 caja... ahora trae N veces más unidades
            db.execute("UPDATE producto_presentaciones SET factor = factor * ? WHERE producto_id = ?", (n, pid))
            # La unidad vieja pasa a ser una presentación (con su precio de siempre)
            db.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                       "precio_maximo, codigo_barras, creado_en) VALUES (?,?,?,?,?,NULL,?)",
                       (pid, vieja_id, n, producto["precio_venta"] or 0, producto["precio_maximo"], ahora()))
            # Precios de 1 unidad nueva (si no los escribieron: el de antes ÷ N)
            precio = precio_nuevo if precio_nuevo is not None else round((producto["precio_venta"] or 0) / n)
            maximo = maximo_nuevo if maximo_nuevo is not None else (
                round(producto["precio_maximo"] / n) if producto["precio_maximo"] else None)
            # El POS sigue vendiendo por defecto lo mismo que antes (la unidad vieja)
            defecto = producto["venta_defecto_unidad_id"] or vieja_id
            db.execute("UPDATE productos SET unidad_venta_id = ?, precio_venta = ?, precio_maximo = ?, "
                       "precio_compra = precio_compra / ?, stock_minimo = stock_minimo * ?, "
                       "venta_defecto_unidad_id = ?, actualizado_en = ? WHERE id = ?",
                       (unidad_nueva_id, precio, maximo, n, n, defecto, ahora(), pid))
            texto = (f"unidad de inventario {nombre_viejo} -> {nueva['nombre']} (1 {nombre_viejo} = "
                     f"{n:g} {nueva['nombre']}); cantidades x{n:g}, precio {producto['precio_venta']} -> {precio}")
        else:
            # Solo corregir el nombre: los números ya estaban en la unidad nueva
            db.execute("UPDATE productos SET unidad_venta_id = ?, actualizado_en = ? WHERE id = ?",
                       (unidad_nueva_id, ahora(), pid))
            texto = f"unidad de inventario corregida {nombre_viejo} -> {nueva['nombre']} (sin convertir)"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return texto
