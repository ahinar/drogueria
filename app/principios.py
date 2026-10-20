"""
VARIOS PRINCIPIOS ACTIVOS POR PRODUCTO (versión 1.1.6)
=====================================================

PARA QUÉ (para aprender):
    Hay productos COMPUESTOS: "Acetaminofén + Codeína", "Losartán +
    Hidroclorotiazida"... Antes un producto solo podía tener UN principio
    activo (la columna productos.principio_id), así que el otro no aparecía
    y buscando "codeína" el producto no salía.

    Ahora se escriben separados por comas: "acetaminofén, codeína".
      - Cada uno es un registro del catálogo de principios activos. Si ya
        existe escrito de otra forma ("Acetaminofen" sin tilde), se usa ese
        (ver app/nombres.py); si no existe, se crea.
      - La tabla producto_principios guarda TODOS, en el orden escrito.
      - productos.principio_id sigue guardando el PRIMERO: así todo lo que ya
        existía (pantallas, reportes, la búsqueda vieja) sigue funcionando igual.

    En pantalla se muestran unidos con "+": "Acetaminofén + Codeína".
"""
from .db import ahora
from .nombres import catalogo_igual


def partir(texto):
    """'acetaminofén, codeína ,, ' -> ['acetaminofén', 'codeína'] (sin vacíos)."""
    return [p.strip() for p in (texto or "").replace(";", ",").split(",") if p.strip()]


def ids_de_texto(db, texto):
    """Ids del catálogo para cada principio escrito, en orden y sin repetir. Crea los que falten."""
    ids = []
    for nombre in partir(texto):
        fila = catalogo_igual(db, "principio", nombre)
        if fila is None:
            cid = db.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES ('principio', ?, 1, ?)",
                             (nombre, ahora())).lastrowid
        else:
            cid = fila["id"]
            if not fila["activo"]:                       # estaba desactivado: se vuelve a activar
                db.execute("UPDATE catalogos SET activo = 1 WHERE id = ?", (cid,))
        if cid not in ids:
            ids.append(cid)
    return ids


def guardar_ids(db, producto_id, ids):
    """Deja al producto con EXACTAMENTE esos principios (el primero va también en principio_id)."""
    db.execute("DELETE FROM producto_principios WHERE producto_id = ?", (producto_id,))
    for orden_, cid in enumerate(ids):
        db.execute("INSERT OR IGNORE INTO producto_principios (producto_id, catalogo_id, orden) VALUES (?, ?, ?)",
                   (producto_id, cid, orden_))
    db.execute("UPDATE productos SET principio_id = ? WHERE id = ?", (ids[0] if ids else None, producto_id))


def guardar(db, producto_id, texto):
    """Guarda los principios escritos ("acetaminofén, codeína") para un producto."""
    guardar_ids(db, producto_id, ids_de_texto(db, texto))


def nombres_de(db, producto_id):
    """['Acetaminofén', 'Codeína'] en el orden guardado.

    Si el producto todavía no tiene filas en producto_principios (algo viejo),
    se usa principio_id para no perder nada.
    """
    filas = db.execute(
        "SELECT c.nombre FROM producto_principios pp JOIN catalogos c ON c.id = pp.catalogo_id "
        "WHERE pp.producto_id = ? ORDER BY pp.orden, c.nombre COLLATE ES", (producto_id,)).fetchall()
    if filas:
        return [f["nombre"] for f in filas]
    fila = db.execute("SELECT c.nombre FROM productos p JOIN catalogos c ON c.id = p.principio_id "
                      "WHERE p.id = ?", (producto_id,)).fetchone()
    return [fila["nombre"]] if fila else []


def texto_de(db, producto_id, separador=", "):
    """'Acetaminofén, Codeína' (para el campo de escribir) o con ' + ' para mostrar."""
    return separador.join(nombres_de(db, producto_id))


def nombres_por_producto(db, ids, separador=" + "):
    """{producto_id: 'Acetaminofén + Codeína'} para muchos productos de una vez (listas)."""
    ids = list(ids)
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    salida = {}
    for f in db.execute(
            f"SELECT pp.producto_id, c.nombre FROM producto_principios pp JOIN catalogos c ON c.id = pp.catalogo_id "
            f"WHERE pp.producto_id IN ({marcas}) ORDER BY pp.producto_id, pp.orden", ids):
        salida.setdefault(f["producto_id"], []).append(f["nombre"])
    return {pid: separador.join(n) for pid, n in salida.items()}
