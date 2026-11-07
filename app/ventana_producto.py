"""VENTANA «EDITAR PRODUCTO» — lo que necesita para dibujarse (versión 1.1.17).

PARA QUÉ (pedido de Fernando)
-----------------------------
Antes había DOS ventanas para cambiar un producto sin salir de la pantalla:
  - «Editar» del POS (y de la toma de inventario): precios, presentaciones,
    código de barras, IVA, categorías...
  - «Completar datos» de la Recepción: registro INVIMA, laboratorio, principio
    activo, concentración, forma farmacéutica.
Ahora es UNA sola ventana con dos pestañas (Venta y Datos técnicos), la misma en
el POS, la toma de inventario y la Recepción
(templates/pos/_modal_editar_producto.html + static/js/editar_producto.js).

Esa ventana necesita varias listas para sus menús (categorías, unidades,
laboratorios, formas farmacéuticas, principios activos). En vez de que cada
pantalla se acuerde de mandarlas, la ventana misma las pide con
listas_ventana_producto(), que queda disponible en todas las plantillas
(ver app/__init__.py, «jinja_env.globals»).
"""
from .db import get_db

# Quién puede cambiar PRECIOS (la pestaña «Venta"). Los demás solo ven «Datos técnicos».
ROLES_VENTA = ("administrador", "director_tecnico")


def _catalogo(db, tipo):
    """Las opciones activas de un catálogo (laboratorio, categoria...), en orden alfabético."""
    return db.execute("SELECT id, nombre FROM catalogos WHERE tipo = ? AND activo = 1 "
                      "ORDER BY nombre COLLATE ES", (tipo,)).fetchall()


def listas_ventana_producto():
    """Las listas de los menús de la ventana (se llama desde la plantilla)."""
    from .configuracion import obtener_config
    from .nombres import orden_unidades          # «Unidad» primero y después por tamaño
    db = get_db()
    try:
        margen = float(str(obtener_config().get("margen_costo_estimado") or "30").replace(",", "."))
    except ValueError:
        margen = 30.0
    return {
        "categorias": _catalogo(db, "categoria"),
        "unidades": orden_unidades(db.execute(
            "SELECT id, nombre, cantidad FROM unidades_medida WHERE activo = 1").fetchall()),
        "laboratorios": _catalogo(db, "laboratorio"),
        "formas": _catalogo(db, "forma_farmaceutica"),
        # Para las sugerencias mientras se escribe el principio activo
        "principios": [f["nombre"] for f in _catalogo(db, "principio")],
        # El margen de ganancia de Configuración: con él se sugiere el precio en la Recepción
        "margen": margen,
    }


def ultimo_costo(db, producto_id, sin_recepcion=None):
    """Costo por unidad de la última compra aceptada (para decir «subió 23 %»).

    sin_recepcion: no contar esa recepción (la que se está editando).
    Devuelve None si nunca se ha comprado.
    """
    fila = db.execute(
        "SELECT rl.costo_unitario FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id "
        "WHERE rl.producto_id = ? AND r.estado = 'aprobada' AND rl.resultado = 'aceptado' "
        "AND rl.costo_unitario > 0 AND r.id IS NOT ? "
        "ORDER BY r.fecha DESC, r.id DESC, rl.id DESC LIMIT 1",
        (producto_id, sin_recepcion)).fetchone()
    return round(fila[0], 2) if fila else None


# Lo mismo, como pedazo de SQL para meterlo en una consulta de productos (alias «p»)
SQL_ULTIMO_COSTO = (
    "(SELECT rl.costo_unitario FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id "
    " WHERE rl.producto_id = p.id AND r.estado = 'aprobada' AND rl.resultado = 'aceptado' "
    " AND rl.costo_unitario > 0 ORDER BY r.fecha DESC, r.id DESC, rl.id DESC LIMIT 1) AS ultimo_costo"
)
