"""Presentaciones de venta de un producto (unidad / sobre / caja).

IDEA PRINCIPAL (para aprender):
    El inventario de un producto SIEMPRE se cuenta en su "unidad principal"
    (campo "Unidad de inventario" de la ficha; columna unidad_venta_id). Esa unidad
    principal usa el precio normal del producto (productos.precio_venta).

    Además, el producto puede tener OTRAS presentaciones, guardadas en la
    tabla producto_presentaciones, cada una con:
        - factor: cuántas unidades principales trae (Sobre x 10 -> 10)
        - su propio precio (y si se quiere, su precio máximo y código de barras)

    Al vender 2 "Sobre x 10", el POS cobra 2 x precio del sobre y descuenta
    2 x 10 = 20 unidades de los lotes (FEFO: primero el que vence antes).

    En todo el programa la presentación principal se identifica con id = 0.
"""
from .formato import pesos
from .db import get_db

PRINCIPAL = 0   # id que usamos para "la unidad principal del producto"


def _principal(fila):
    """Arma la presentación principal a partir de una fila de productos."""
    return {
        "id": PRINCIPAL,
        "unidad_id": fila["unidad_venta_id"],
        "nombre": fila["unidad_nombre"] or "Unidad",
        "factor": 1,
        "precio": float(fila["precio_venta"] or 0),
        "precio_maximo": float(fila["precio_maximo"] or 0),
        "codigo_barras": fila["codigo_barras"],
    }


def presentaciones_de(producto_ids):
    """Devuelve {producto_id: [principal, sobre, caja, ...]} ordenadas de menor a mayor.

    Se usa en el POS para mostrar las opciones al tocar una tarjeta.
    """
    if not producto_ids:
        return {}
    db = get_db()
    marcas = ",".join("?" * len(producto_ids))
    resultado = {}

    # 1. La unidad principal de cada producto (siempre existe)
    for f in db.execute(
            "SELECT p.id, p.precio_venta, p.precio_maximo, p.codigo_barras, p.unidad_venta_id, "
            "       u.nombre AS unidad_nombre "
            "FROM productos p LEFT JOIN unidades_medida u ON u.id = p.unidad_venta_id "
            f"WHERE p.id IN ({marcas})", list(producto_ids)):
        resultado[f["id"]] = [_principal(f)]

    # 2. Las demás presentaciones (de la más pequeña a la más grande)
    for f in db.execute(
            "SELECT pp.*, u.nombre AS nombre FROM producto_presentaciones pp "
            "JOIN unidades_medida u ON u.id = pp.unidad_id "
            f"WHERE pp.producto_id IN ({marcas}) ORDER BY pp.factor, u.nombre",
            list(producto_ids)):
        resultado.setdefault(f["producto_id"], []).append({
            "id": f["id"],
            "unidad_id": f["unidad_id"],
            "nombre": f["nombre"],
            "factor": f["factor"],
            "precio": float(f["precio_venta"] or 0),
            "precio_maximo": float(f["precio_maximo"] or 0),
            "codigo_barras": f["codigo_barras"],
        })
    return resultado


def presentacion_para_vender(producto_id, presentacion_id):
    """La presentación que el POS quiere vender, o None si no existe / no es de ese producto."""
    opciones = presentaciones_de([producto_id]).get(producto_id, [])
    for opcion in opciones:
        if opcion["id"] == presentacion_id:
            return opcion
    return None


def filas_para_formulario(producto_id):
    """Presentaciones guardadas de un producto, tal cual las necesita el formulario."""
    if not producto_id:
        return []
    return get_db().execute(
        "SELECT pp.*, u.nombre AS unidad_nombre FROM producto_presentaciones pp "
        "JOIN unidades_medida u ON u.id = pp.unidad_id "
        "WHERE pp.producto_id = ? ORDER BY pp.factor", (producto_id,)
    ).fetchall()


def leer_del_formulario(form):
    """Lee las filas de "Otras presentaciones" del formulario de productos.

    El formulario manda listas paralelas (una posición por fila):
        pres_unidad_id[], pres_factor[], pres_precio[], pres_maximo[], pres_barras[]
    Las filas totalmente vacías se ignoran.
    """
    def numero(texto):
        texto = (texto or "").strip().replace(",", ".")
        try:
            return float(texto) if texto else None
        except ValueError:
            return "error"

    unidades = form.getlist("pres_unidad_id")
    factores = form.getlist("pres_factor")
    precios = form.getlist("pres_precio")
    maximos = form.getlist("pres_maximo")
    barras = form.getlist("pres_barras")

    filas = []
    for i, unidad in enumerate(unidades):
        tomar = lambda lista: lista[i] if i < len(lista) else ""
        fila = {
            "unidad_id": int(unidad) if unidad.strip().isdigit() else None,
            "factor": numero(tomar(factores)),
            "precio": numero(tomar(precios)),
            "maximo": numero(tomar(maximos)),
            "barras": tomar(barras).strip() or None,
        }
        # Fila sin nada escrito = el usuario agregó la fila pero no la usó
        if fila["unidad_id"] is None and fila["factor"] is None and fila["precio"] is None:
            continue
        filas.append(fila)
    return filas


def validar(filas, unidad_principal_id, producto_id=None, codigo_barras_principal=None):
    """Revisa las presentaciones. Devuelve una lista de errores (vacía = todo bien)."""
    errores = []
    db = get_db()
    vistas, codigos = set(), set()
    if codigo_barras_principal:
        codigos.add(codigo_barras_principal)
        # El código del producto tampoco puede ser el de una caja/sobre de OTRO producto
        otro = db.execute(
            "SELECT p.nombre FROM producto_presentaciones pp JOIN productos p ON p.id = pp.producto_id "
            "WHERE pp.codigo_barras = ? AND pp.producto_id IS NOT ? LIMIT 1",
            (codigo_barras_principal, producto_id)).fetchone()
        if otro:
            errores.append(f"El código de barras {codigo_barras_principal} ya es de una "
                           f"presentación de '{otro['nombre']}'.")

    for n, f in enumerate(filas, start=1):
        quien = f"Presentación {n}"
        if not f["unidad_id"]:
            errores.append(f"{quien}: elige la unidad (Sobre x 10, Caja x 100…).")
            continue
        if f["unidad_id"] == unidad_principal_id:
            errores.append(f"{quien}: es la misma unidad principal del producto; "
                           "su precio ya es el 'Precio de venta final'.")
        if f["unidad_id"] in vistas:
            errores.append(f"{quien}: esa unidad está repetida.")
        vistas.add(f["unidad_id"])
        if f["factor"] == "error" or not f["factor"] or f["factor"] <= 1:
            errores.append(f"{quien}: '¿Cuántas trae?' debe ser un número mayor que 1.")
        if f["precio"] == "error" or not f["precio"] or f["precio"] <= 0:
            errores.append(f"{quien}: el precio debe ser mayor que cero.")
        if f["maximo"] == "error":
            errores.append(f"{quien}: el precio máximo no es un número válido.")
        elif f["maximo"] and isinstance(f["precio"], float) and f["precio"] > f["maximo"] + 0.01:
            errores.append(f"{quien}: el precio supera su precio máximo regulado.")

        # Código de barras: no puede repetirse con otro producto ni con otra presentación
        if f["barras"]:
            if f["barras"] in codigos:
                errores.append(f"{quien}: el código de barras {f['barras']} está repetido.")
            codigos.add(f["barras"])
            otro = db.execute(
                "SELECT nombre FROM productos WHERE codigo_barras = ? AND id IS NOT ? "
                "UNION ALL "
                "SELECT p.nombre FROM producto_presentaciones pp JOIN productos p ON p.id = pp.producto_id "
                "WHERE pp.codigo_barras = ? AND pp.producto_id IS NOT ? LIMIT 1",
                (f["barras"], producto_id, f["barras"], producto_id)).fetchone()
            if otro:
                errores.append(f"{quien}: el código de barras {f['barras']} ya lo tiene "
                               f"'{otro['nombre']}'.")
    return errores


def guardar(db, producto_id, filas, ahora_txt):
    """Reemplaza las presentaciones del producto por las del formulario.

    Se pueden borrar y volver a crear sin miedo: las ventas guardan el NOMBRE
    y el FACTOR de la presentación en cada línea, así que el historial no cambia.
    Devuelve un texto corto para la bitácora.
    """
    db.execute("DELETE FROM producto_presentaciones WHERE producto_id = ?", (producto_id,))
    for f in filas:
        db.execute(
            "INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
            "precio_maximo, codigo_barras, creado_en) VALUES (?,?,?,?,?,?,?)",
            (producto_id, f["unidad_id"], f["factor"], f["precio"], f["maximo"] or None,
             f["barras"], ahora_txt))
    if not filas:
        return ""
    nombres = {u["id"]: u["nombre"] for u in db.execute("SELECT id, nombre FROM unidades_medida")}
    return " presentaciones=" + ", ".join(
        f"{nombres.get(f['unidad_id'], '?')} x{f['factor']:g} {pesos(f['precio'])}" for f in filas)


def tiene_historia(db, producto_id):
    """True si el producto ya tiene lotes, movimientos o ventas.

    En ese caso su UNIDAD DE INVENTARIO no se puede cambiar desde la ficha:
    los números guardados (308 tabletas...) están en esa unidad, y cambiarle
    el nombre sin convertir haría que 308 tabletas se lean como 308 sobres.
    Para cambiarla está el asistente "Cambiar unidad de inventario"
    (app/unidad_inventario.py), que convierte todo.
    """
    if not producto_id:
        return False
    for tabla in ("lotes", "movimientos_inventario", "venta_lineas"):
        if db.execute(f"SELECT 1 FROM {tabla} WHERE producto_id = ? LIMIT 1", (producto_id,)).fetchone():
            return True
    return False


def id_por_defecto(opciones, venta_defecto_unidad_id):
    """Cuál de las presentaciones vende el POS al tocar la tarjeta (su id; 0 = unidad de inventario)."""
    for o in opciones:
        if venta_defecto_unidad_id and o["unidad_id"] == venta_defecto_unidad_id:
            return o["id"]
    return PRINCIPAL
