"""Cálculos de los reportes R1, R3, R4, R5, R7 y Valor del inventario (las pantallas están en reportes.py).

Todos reciben un período (desde, hasta) como fechas `date`, ambas incluidas.
Reglas comunes:
    - Las ventas ANULADAS no cuentan (v.estado = 'completada').
    - "Sin IVA" = venta_lineas.subtotal; "con IVA" = venta_lineas.total.
    - Las cantidades vendidas se cuentan en UNIDADES del inventario:
      cantidad × factor (1 caja x 100 = 100 unidades).
    - Las fechas se guardan como texto 'AAAA-MM-DD HH:MM:SS'; para incluir todo
      el último día se pide "fecha < día siguiente".
"""
import json
from datetime import date, timedelta

from .db import get_db
from . import formas_pago as fp   # versión 1.1.14: formas de pago y cuentas (con Daviplata) en un solo lugar

DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
FORMAS_PAGO = fp.NOMBRES             # Efectivo, Nequi, Davivienda, Daviplata, Tarjeta... (formas_pago.py)
MESES_CORTOS = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _limites(desde, hasta):
    return desde.isoformat(), (hasta + timedelta(days=1)).isoformat()


# ======================================================================
# R1 · VENTAS
# ======================================================================

# Filtro "Mostrar" del reporte R1. Se cuenta por LÍNEAS de venta, porque
# un mismo tiquete puede tener productos del inventario Y venta libre.
TIPOS_VENTA = {
    "todo": ("Todo", ""),
    "productos": ("Solo productos del inventario", " AND vl.es_libre = 0"),
    "libre": ("Solo venta libre", " AND vl.es_libre = 1"),
}

# Base de casi todas las consultas de R1: líneas de ventas completadas en el período
_DESDE_LINEAS = ("FROM venta_lineas vl JOIN ventas v ON v.id = vl.venta_id "
                 "WHERE v.estado = 'completada' AND v.fecha >= ? AND v.fecha < ?")


def _totales_ventas(db, ini, fin, filtro=""):
    """Totales del período. n = cuántos tiquetes distintos."""
    fila = db.execute(
        "SELECT COUNT(DISTINCT v.id) AS n, COALESCE(SUM(vl.total), 0) AS con_iva, "
        "       COALESCE(SUM(vl.subtotal), 0) AS sin_iva, COALESCE(SUM(vl.iva_valor), 0) AS iva, "
        "       COALESCE(SUM(vl.descuento_linea), 0) AS descuentos "
        + _DESDE_LINEAS + filtro, (ini, fin)).fetchone()
    datos = dict(fila)
    datos["ticket"] = datos["con_iva"] / datos["n"] if datos["n"] else 0
    return datos


def _otros_ingresos(db, ini, fin):
    """Otros ingresos del período (recargas, arriendo...): total y por categoría."""
    por_cat = [dict(f) for f in db.execute(
        "SELECT COALESCE(c.nombre, 'Sin categoría') AS nombre, COUNT(*) AS n, SUM(i.monto) AS total "
        "FROM otros_ingresos i LEFT JOIN catalogos c ON c.id = i.categoria_id "
        "WHERE i.activo = 1 AND i.fecha >= ? AND i.fecha < ? GROUP BY nombre ORDER BY total DESC",
        (ini, fin))]
    return {"total": sum(f["total"] for f in por_cat), "n": sum(f["n"] for f in por_cat),
            "por_categoria": por_cat}


def ventas(desde, hasta, anterior_desde, anterior_hasta, tipo="todo"):
    """R1: totales (y los del período anterior), por día, forma de pago, vendedor y hora.

    tipo = 'todo', 'productos' (del inventario) o 'libre' (venta libre).
    Además trae la composición (productos vs venta libre) y los OTROS
    INGRESOS del período, que se muestran aparte (no son ventas).
    """
    db = get_db()
    filtro = TIPOS_VENTA.get(tipo, TIPOS_VENTA["todo"])[1]
    ini, fin = _limites(desde, hasta)
    ini_ant, fin_ant = _limites(anterior_desde, anterior_hasta)
    actual = _totales_ventas(db, ini, fin, filtro)
    anterior = _totales_ventas(db, ini_ant, fin_ant, filtro)

    # Composición: cuánto fue de productos y cuánto de venta libre (siempre todo)
    composicion = {
        "productos": _totales_ventas(db, ini, fin, TIPOS_VENTA["productos"][1])["con_iva"],
        "libre": _totales_ventas(db, ini, fin, TIPOS_VENTA["libre"][1])["con_iva"],
    }
    otros = _otros_ingresos(db, ini, fin)
    otros["total_anterior"] = _otros_ingresos(db, ini_ant, fin_ant)["total"]

    anuladas = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total FROM ventas "
        "WHERE estado = 'anulada' AND fecha >= ? AND fecha < ?", (ini, fin)).fetchone()
    # Devoluciones de clientes en el período (plata que se les devolvió)
    devoluciones = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total FROM devoluciones "
        "WHERE tipo = 'cliente' AND fecha >= ? AND fecha < ?", (ini, fin)).fetchone()

    # Por día: TODOS los días del período, aunque en alguno no se haya vendido (sale en 0)
    por_dia_bd = {f["dia"]: dict(f) for f in db.execute(
        "SELECT substr(v.fecha, 1, 10) AS dia, COUNT(DISTINCT v.id) AS n, SUM(vl.total) AS total "
        + _DESDE_LINEAS + filtro + " GROUP BY dia", (ini, fin))}
    por_dia, d = [], desde
    while d <= hasta:
        f = por_dia_bd.get(d.isoformat(), {"n": 0, "total": 0})
        por_dia.append({"fecha": d, "etiqueta": f"{DIAS_SEMANA[d.weekday()]} {d.day:02d}/{d.month:02d}",
                        "n": f["n"], "total": f["total"] or 0})
        d += timedelta(days=1)

    def agrupar(columna):
        return [dict(f) for f in db.execute(
            f"SELECT {columna} AS nombre, COUNT(DISTINCT v.id) AS n, SUM(vl.total) AS total "
            + _DESDE_LINEAS + filtro + f" GROUP BY {columna} ORDER BY total DESC", (ini, fin))]

    por_pago = agrupar("v.forma_pago")
    for f in por_pago:
        f["nombre"] = FORMAS_PAGO.get(f["nombre"], f["nombre"])
    por_vendedor = agrupar("COALESCE(v.usuario_nombre, '—')")

    # Por hora del día: ¿a qué horas se vende más? (sirve para turnos)
    por_hora = {int(f["hora"]): dict(f) for f in db.execute(
        "SELECT substr(v.fecha, 12, 2) AS hora, COUNT(DISTINCT v.id) AS n, SUM(vl.total) AS total "
        + _DESDE_LINEAS + filtro + " GROUP BY hora", (ini, fin))}
    horas = [{"hora": h, "n": por_hora.get(h, {}).get("n", 0), "total": por_hora.get(h, {}).get("total", 0) or 0}
             for h in range(24)]
    # Solo el rango de horas con ventas (ej: 7 a. m. a 9 p. m.)
    con_ventas = [h["hora"] for h in horas if h["n"]]
    horas = horas[min(con_ventas):max(con_ventas) + 1] if con_ventas else []

    total = actual["con_iva"] or 1
    for lista in (por_pago, por_vendedor):
        for f in lista:
            f["pct"] = f["total"] / total * 100

    return {"actual": actual, "anterior": anterior, "anuladas": dict(anuladas),
            "devoluciones": dict(devoluciones), "composicion": composicion, "otros_ingresos": otros,
            "por_dia": por_dia, "por_pago": por_pago, "por_vendedor": por_vendedor, "por_hora": horas,
            "libres": ventas_libres(db, ini, fin)}


def ventas_libres(db, ini, fin):
    """Versión 1.1.13: cuánto se vendió de cada VENTA RÁPIDA y de cada venta libre escrita a mano.

    Las de una venta rápida se juntan por su número (aunque se haya cambiado el nombre).
    Las escritas a mano se juntan por el texto, sin importar mayúsculas ni tildes
    ("Fotocopia" y "fotocopía" son lo mismo). Ganancia = venta sin IVA − costo, solo
    cuando se sabe el costo (si una parte no tiene costo, se avisa con sin_costo).
    """
    from .nombres import plano
    grupos = {}
    for f in db.execute(
            "SELECT vl.venta_rapida_id, vr.nombre AS rapida, vl.producto_nombre, vl.cantidad, "
            "       vl.subtotal, vl.total, vl.costo_libre "
            "FROM venta_lineas vl JOIN ventas v ON v.id = vl.venta_id "
            "LEFT JOIN ventas_rapidas vr ON vr.id = vl.venta_rapida_id "
            "WHERE v.estado = 'completada' AND v.fecha >= ? AND v.fecha < ? AND vl.es_libre = 1",
            (ini, fin)):
        if f["venta_rapida_id"]:
            clave, nombre, tipo = ("r", f["venta_rapida_id"]), f["rapida"], "Venta rápida"
        else:
            nombre = " ".join((f["producto_nombre"] or "Venta libre").split())
            clave, tipo = ("t", plano(nombre)), "Escrita a mano"
        g = grupos.setdefault(clave, {"nombre": nombre, "tipo": tipo, "lineas": 0, "cantidad": 0.0,
                                      "con_iva": 0.0, "sin_iva": 0.0, "costo": 0.0, "sin_costo": 0})
        g["lineas"] += 1
        g["cantidad"] += f["cantidad"]
        g["con_iva"] += f["total"]
        g["sin_iva"] += f["subtotal"]
        if f["costo_libre"] is None:
            g["sin_costo"] += 1
        else:
            g["costo"] += f["costo_libre"] * f["cantidad"]
    lista = sorted(grupos.values(), key=lambda g: (-g["con_iva"], g["nombre"]))
    for g in lista:
        # Ganancia solo si TODAS las ventas de ese concepto tienen costo
        g["ganancia"] = g["sin_iva"] - g["costo"] if not g["sin_costo"] else None
    return lista


# ======================================================================
# R3 · TOP PRODUCTOS
# ======================================================================

def top_productos(desde, hasta, cuantos=10, orden="dinero"):
    """R3: los más vendidos por dinero, por unidades o por utilidad."""
    db = get_db()
    ini, fin = _limites(desde, hasta)
    lineas = db.execute(
        "SELECT vl.producto_id, vl.producto_codigo, vl.producto_nombre, vl.cantidad, "
        "       COALESCE(vl.factor, 1) AS factor, vl.subtotal, vl.total, vl.lotes_json "
        "FROM venta_lineas vl JOIN ventas v ON v.id = vl.venta_id "
        "WHERE v.estado = 'completada' AND v.fecha >= ? AND v.fecha < ? "
        "AND vl.es_libre = 0", (ini, fin)).fetchall()    # la venta libre no es un producto

    # Costo de los lotes usados (para la utilidad de cada producto)
    ids = {a["lote_id"] for ln in lineas for a in json.loads(ln["lotes_json"] or "[]")}
    costos = {}
    if ids:
        marcas = ",".join("?" * len(ids))
        costos = {f["id"]: f["costo_unitario"] or 0 for f in db.execute(
            f"SELECT id, costo_unitario FROM lotes WHERE id IN ({marcas})", list(ids))}

    productos = {}
    for ln in lineas:
        p = productos.setdefault(ln["producto_id"], {
            "id": ln["producto_id"], "codigo": ln["producto_codigo"], "nombre": ln["producto_nombre"],
            "unidades": 0.0, "con_iva": 0.0, "sin_iva": 0.0, "costo": 0.0, "lineas": 0})
        p["unidades"] += ln["cantidad"] * ln["factor"]
        p["con_iva"] += ln["total"]
        p["sin_iva"] += ln["subtotal"]
        p["costo"] += sum(a["cantidad"] * costos.get(a["lote_id"], 0) for a in json.loads(ln["lotes_json"] or "[]"))
        p["lineas"] += 1
    for p in productos.values():
        p["utilidad"] = p["sin_iva"] - p["costo"]
        p["margen"] = p["utilidad"] / p["sin_iva"] * 100 if p["sin_iva"] else 0

    claves = {"dinero": "con_iva", "unidades": "unidades", "utilidad": "utilidad"}
    lista = sorted(productos.values(), key=lambda p: -p[claves.get(orden, "con_iva")])
    total_ventas = sum(p["con_iva"] for p in productos.values()) or 1
    top = lista[:cuantos]
    for p in top:
        p["pct"] = p["con_iva"] / total_ventas * 100
    return {"top": top, "total_productos": len(productos),
            "pct_top": sum(p["con_iva"] for p in top) / total_ventas * 100 if productos else 0}


# ======================================================================
# R4 · VENTAS VS COMPRAS (12 meses)
# ======================================================================

def ventas_vs_compras(meses=12, hoy=None):
    """R4: por mes, lo vendido (sin IVA) y lo comprado (recepciones aprobadas, al costo)."""
    db = get_db()
    hoy = hoy or date.today()
    # Primer día de cada uno de los últimos 12 meses (del más viejo al actual)
    inicio, lista = hoy.replace(day=1), []
    for _ in range(meses):
        lista.insert(0, inicio)
        inicio = (inicio - timedelta(days=1)).replace(day=1)
    desde = lista[0].isoformat()

    vendido = {f["mes"]: f for f in db.execute(
        "SELECT substr(v.fecha, 1, 7) AS mes, SUM(vl.subtotal) AS sin_iva, "
        "       SUM(vl.total) AS con_iva FROM venta_lineas vl JOIN ventas v ON v.id = vl.venta_id "
        "WHERE v.estado = 'completada' AND v.fecha >= ? GROUP BY mes", (desde,))}
    comprado = {f["mes"]: f["total"] for f in db.execute(
        "SELECT substr(r.fecha, 1, 7) AS mes, SUM(rl.cantidad_recibida * rl.costo_unitario) AS total "
        "FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id "
        "WHERE r.estado = 'aprobada' AND rl.resultado = 'aceptado' AND r.fecha >= ? GROUP BY mes", (desde,))}
    # Lo devuelto al proveedor con nota crédito resta de lo comprado
    for f in db.execute(
            "SELECT substr(fecha, 1, 7) AS mes, SUM(total) AS total FROM devoluciones "
            "WHERE tipo = 'proveedor' AND con_credito = 1 AND fecha >= ? GROUP BY mes", (desde,)):
        comprado[f["mes"]] = (comprado.get(f["mes"]) or 0) - (f["total"] or 0)

    filas = []
    for d in lista:
        clave = d.strftime("%Y-%m")
        v = vendido.get(clave)
        sin_iva = (v["sin_iva"] if v else 0) or 0
        c = comprado.get(clave, 0) or 0
        filas.append({"mes": f"{MESES_CORTOS[d.month]} {d.year}", "clave": clave,
                      "vendido": sin_iva, "comprado": c, "diferencia": sin_iva - c,
                      "relacion": (c / sin_iva * 100) if sin_iva else None})
    return {"filas": filas,
            "total_vendido": sum(f["vendido"] for f in filas),
            "total_comprado": sum(f["comprado"] for f in filas)}


# ======================================================================
# R5 · GASTOS
# ======================================================================

def gastos(desde, hasta, anterior_desde, anterior_hasta):
    """R5: gastos por categoría (con el período anterior), por forma de pago y el listado."""
    db = get_db()
    ini, fin = _limites(desde, hasta)
    a_ini, a_fin = _limites(anterior_desde, anterior_hasta)

    def por_categoria(i, f):
        return {r["categoria"]: r for r in db.execute(
            "SELECT COALESCE(c.nombre, 'Sin categoría') AS categoria, COUNT(*) AS n, SUM(g.monto) AS total "
            "FROM gastos g LEFT JOIN catalogos c ON c.id = g.categoria_id "
            "WHERE g.activo = 1 AND g.fecha >= ? AND g.fecha < ? GROUP BY categoria", (i, f))}

    actual, anterior = por_categoria(ini, fin), por_categoria(a_ini, a_fin)
    total = sum(r["total"] for r in actual.values())
    total_ant = sum(r["total"] for r in anterior.values())
    nombres = sorted(set(actual) | set(anterior), key=lambda n: -(actual[n]["total"] if n in actual else 0))
    categorias = [{
        "categoria": n,
        "n": actual[n]["n"] if n in actual else 0,
        "total": actual[n]["total"] if n in actual else 0,
        "anterior": anterior[n]["total"] if n in anterior else 0,
        "pct": (actual[n]["total"] / total * 100) if n in actual and total else 0,
    } for n in nombres]

    por_pago = [{"nombre": FORMAS_PAGO.get(f["forma_pago"], f["forma_pago"]), "total": f["total"], "n": f["n"]}
                for f in db.execute(
                    "SELECT forma_pago, COUNT(*) AS n, SUM(monto) AS total FROM gastos "
                    "WHERE activo = 1 AND fecha >= ? AND fecha < ? GROUP BY forma_pago ORDER BY total DESC",
                    (ini, fin))]
    detalle = [dict(f) for f in db.execute(
        "SELECT g.fecha, g.descripcion, g.monto, g.forma_pago, COALESCE(c.nombre, 'Sin categoría') AS categoria, "
        "       pr.razon_social AS proveedor "
        "FROM gastos g LEFT JOIN catalogos c ON c.id = g.categoria_id "
        "LEFT JOIN proveedores pr ON pr.id = g.proveedor_id "
        "WHERE g.activo = 1 AND g.fecha >= ? AND g.fecha < ? ORDER BY g.fecha DESC, g.id DESC", (ini, fin))]
    return {"categorias": categorias, "total": total, "total_anterior": total_ant,
            "por_pago": por_pago, "detalle": detalle}


# ======================================================================
# R7 · RECEPCIONES
# ======================================================================

def recepciones(desde, hasta):
    """R7: recepciones por proveedor (cuántas, valor, rechazos) y el detalle de los rechazos."""
    db = get_db()
    ini, fin = _limites(desde, hasta)
    por_proveedor = [dict(f) for f in db.execute(
        "SELECT pr.razon_social AS proveedor, COUNT(DISTINCT r.id) AS recepciones, "
        "       COUNT(DISTINCT CASE WHEN r.estado = 'aprobada' THEN r.id END) AS aprobadas, "
        "       COUNT(DISTINCT CASE WHEN r.estado = 'rechazada' THEN r.id END) AS rechazadas, "
        "       COUNT(DISTINCT CASE WHEN r.estado = 'cuarentena' THEN r.id END) AS en_cuarentena, "
        "       COUNT(rl.id) AS lineas, "
        "       SUM(CASE WHEN rl.resultado = 'rechazado' THEN 1 ELSE 0 END) AS lineas_rechazadas, "
        "       COALESCE(SUM(CASE WHEN r.estado = 'aprobada' AND rl.resultado = 'aceptado' "
        "                    THEN rl.cantidad_recibida * rl.costo_unitario END), 0) AS valor "
        "FROM recepciones r JOIN proveedores pr ON pr.id = r.proveedor_id "
        "LEFT JOIN recepcion_lineas rl ON rl.recepcion_id = r.id "
        "WHERE r.estado <> 'borrador' AND r.fecha >= ? AND r.fecha < ? "
        "GROUP BY pr.id ORDER BY valor DESC", (ini, fin))]
    for f in por_proveedor:
        f["pct_rechazo"] = f["lineas_rechazadas"] / f["lineas"] * 100 if f["lineas"] else 0

    rechazos = [dict(f) for f in db.execute(
        "SELECT r.id AS recepcion_id, r.numero, r.fecha, pr.razon_social AS proveedor, p.nombre AS producto, "
        "       rl.lote, rl.cantidad_recibida, rl.estado_empaque, rl.motivo_rechazo, rl.observaciones "
        "FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id "
        "JOIN proveedores pr ON pr.id = r.proveedor_id JOIN productos p ON p.id = rl.producto_id "
        "WHERE rl.resultado = 'rechazado' AND r.fecha >= ? AND r.fecha < ? ORDER BY r.fecha DESC", (ini, fin))]
    return {"por_proveedor": por_proveedor, "rechazos": rechazos,
            "total_recepciones": sum(f["recepciones"] for f in por_proveedor),
            "total_valor": sum(f["valor"] for f in por_proveedor)}


# ======================================================================
# VALOR DEL INVENTARIO (versión 1.1.13)
# ======================================================================
# Pregunta de Fernando: "¿cómo veo el valor del inventario?".
#
# CÓMO SE CALCULA (en palabras sencillas):
#   - Se miran todos los LOTES que tienen mercancía (cantidad_disponible > 0).
#   - VALOR AL COSTO de un lote = cantidad × costo unitario del lote
#     (lo que se pagó por él; es el dato que sirve para la contabilidad).
#   - VALOR A PRECIO DE VENTA = cantidad × precio de venta de UNA unidad
#     (con IVA, como se le cobra al cliente). Si la unidad no se vende suelta,
#     se toma el precio de la presentación ÷ lo que trae (Sello x 10 a $4.000 → $400).
#   - GANANCIA EN EL ESTANTE = venta SIN IVA − costo (el IVA no es del negocio:
#     es de la DIAN). Es lo que se ganaría si se vendiera todo a precio normal.
#   - Lo que NO se puede vender va APARTE y no suma al total:
#       vencidos, en cuarentena y bloqueados.
#   - Un producto con VARIAS categorías se cuenta solo en la PRIMERA (en orden
#     alfabético); si se contara en todas, la suma por categorías daría más que el total.

def _sin_iva(precio, iva_tipo, tarifa):
    """Quita el IVA de un precio: $11.900 con IVA 19 % → $10.000."""
    if iva_tipo == "gravado" and (tarifa or 0) > 0:
        return precio / (1 + tarifa / 100)
    return precio


def valor_inventario(hoy=None):
    """Devuelve el valor del inventario (ver la explicación de arriba).

    Resultado (un diccionario):
      costo, venta, venta_sin_iva, ganancia, margen   -> totales de lo VENDIBLE
      productos     -> lista por producto (de mayor a menor valor al costo)
      categorias    -> lista por categoría (de mayor a menor valor al costo)
      no_vendible   -> [{grupo, lotes, unidades, costo}] vencidos / cuarentena / bloqueados
      sin_costo     -> productos con lotes vendibles SIN costo (no suman al costo: hay que corregirlos)
      sin_precio    -> productos vendibles SIN precio de venta
    """
    from . import presentaciones as pres
    from .conteos import _precio_de_una_unidad

    db = get_db()
    hoy_txt = (hoy or date.today()).isoformat()
    lotes = db.execute(
        "SELECT l.id, l.producto_id, l.cantidad_disponible AS cantidad, COALESCE(l.costo_unitario, 0) AS costo, "
        "       l.estado, l.vencimiento, p.codigo, p.nombre, p.iva_tipo, p.iva_tarifa, "
        "       (SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad, "
        # La primera categoría del producto en orden alfabético (o ninguna)
        "       (SELECT c.nombre FROM productos_categorias pc JOIN catalogos c ON c.id = pc.catalogo_id "
        "         WHERE pc.producto_id = p.id ORDER BY c.nombre COLLATE ES LIMIT 1) AS categoria "
        "FROM lotes l JOIN productos p ON p.id = l.producto_id "
        "WHERE l.cantidad_disponible > 0 AND l.estado NOT IN ('agotado', 'rechazado')").fetchall()

    # Precio de UNA unidad de cada producto (una sola consulta para todos)
    ids = sorted({l["producto_id"] for l in lotes})
    opciones = pres.presentaciones_de(ids)
    precio_unidad = {pid: _precio_de_una_unidad(pid, opciones.get(pid, [])) for pid in ids}

    # Grupos de lo que NO se puede vender (el orden importa: vencido gana)
    no_vendible = {"vencidos": {"grupo": "Vencidos", "lotes": 0, "unidades": 0.0, "costo": 0.0},
                   "cuarentena": {"grupo": "En cuarentena", "lotes": 0, "unidades": 0.0, "costo": 0.0},
                   "bloqueado": {"grupo": "Bloqueados", "lotes": 0, "unidades": 0.0, "costo": 0.0}}
    productos = {}
    for l in lotes:
        vencido = bool(l["vencimiento"]) and l["vencimiento"][:10] < hoy_txt
        if vencido or l["estado"] in ("cuarentena", "bloqueado"):
            g = no_vendible["vencidos" if vencido else l["estado"]]
            g["lotes"] += 1
            g["unidades"] += l["cantidad"]
            g["costo"] += l["cantidad"] * l["costo"]
            continue
        # Lote vendible: suma al producto
        precio = precio_unidad.get(l["producto_id"], 0) or 0
        p = productos.setdefault(l["producto_id"], {
            "id": l["producto_id"], "codigo": l["codigo"], "nombre": l["nombre"],
            "unidad": l["unidad"] or "unidades", "categoria": l["categoria"] or "Sin categoría",
            "precio": precio, "unidades": 0.0, "lotes": 0, "costo": 0.0, "venta": 0.0,
            "venta_sin_iva": 0.0, "lotes_sin_costo": 0})
        p["unidades"] += l["cantidad"]
        p["lotes"] += 1
        p["costo"] += l["cantidad"] * l["costo"]
        p["venta"] += l["cantidad"] * precio
        p["venta_sin_iva"] += l["cantidad"] * _sin_iva(precio, l["iva_tipo"], l["iva_tarifa"])
        if l["costo"] <= 0:
            p["lotes_sin_costo"] += 1

    for p in productos.values():
        p["ganancia"] = p["venta_sin_iva"] - p["costo"]
    lista = sorted(productos.values(), key=lambda p: (-p["costo"], p["nombre"]))

    # Totales por categoría
    cats = {}
    for p in lista:
        c = cats.setdefault(p["categoria"], {"categoria": p["categoria"], "productos": 0,
                                             "costo": 0.0, "venta": 0.0, "ganancia": 0.0})
        c["productos"] += 1
        c["costo"] += p["costo"]
        c["venta"] += p["venta"]
        c["ganancia"] += p["ganancia"]
    costo = sum(p["costo"] for p in lista)
    for c in cats.values():
        c["pct"] = c["costo"] / costo * 100 if costo else 0
    venta_sin_iva = sum(p["venta_sin_iva"] for p in lista)
    ganancia = venta_sin_iva - costo
    return {
        "costo": costo,
        "venta": sum(p["venta"] for p in lista),
        "venta_sin_iva": venta_sin_iva,
        "ganancia": ganancia,
        "margen": ganancia / venta_sin_iva * 100 if venta_sin_iva else 0,
        "unidades": sum(p["unidades"] for p in lista),
        "productos": lista,
        "categorias": sorted(cats.values(), key=lambda c: (-c["costo"], c["categoria"])),
        "no_vendible": [g for g in no_vendible.values() if g["lotes"]],
        "costo_no_vendible": sum(g["costo"] for g in no_vendible.values()),
        "sin_costo": [p for p in lista if p["lotes_sin_costo"]],
        "sin_precio": [p for p in lista if p["precio"] <= 0],
    }
