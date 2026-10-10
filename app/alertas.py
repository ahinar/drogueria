"""Panel de alertas del Inicio: "¿qué hay que atender hoy?".

CÓMO FUNCIONA (para aprender):
    calcular_alertas() hace varias consultas pequeñas a la base de datos y
    devuelve una LISTA de alertas. Cada alerta es un diccionario así:

        {
          "clave":  "invima_vencido",          # nombre interno (para pruebas y CSS)
          "nivel":  "rojo" o "amarillo",       # rojo = urgente / ilegal; amarillo = pronto
          "icono":  "📄",
          "titulo": "Registro INVIMA vencido",
          "explicacion": "No se deben vender ...",   # qué significa y qué hacer
          "total":  3,                         # cuántos casos hay en total
          "items":  [ {"texto": ..., "detalle": ..., "url": ...}, ... ],  # máximo 5
          "url":    "/productos/?...",         # botón "Ver todos" (puede ser None)
          "boton":  "Ver productos",
        }

    Las alertas SIN casos no se devuelven. Primero van las rojas.
    La plantilla inicio.html solo las pinta: aquí está toda la lógica.

    Algunas alertas solo las ve el administrador / director técnico (por ejemplo
    las de proveedores), porque el auxiliar no puede corregirlas.
"""
from datetime import date, timedelta

from flask import url_for

from .db import get_db

MAX_ITEMS = 5            # cuántos casos se muestran en cada tarjeta
DIAS_INVIMA = 90         # avisar 3 meses antes: renovar un registro toma tiempo
DIAS_PROVEEDOR = 30      # concepto sanitario del proveedor
DIAS_LOTE = 30           # lotes por vencer

# Stock vendible de un producto: lotes disponibles, con cantidad y sin vencer
# (la misma regla que usa el POS para vender).
SQL_STOCK = (
    "COALESCE((SELECT SUM(l.cantidad_disponible) FROM lotes l "
    "  WHERE l.producto_id = p.id AND l.estado = 'disponible' AND l.cantidad_disponible > 0 "
    "  AND (l.vencimiento IS NULL OR l.vencimiento = '' OR l.vencimiento >= :hoy)), 0)"
)


def _fecha(iso):
    """'2026-10-09' -> '09/10/2026' (formato colombiano)."""
    if not iso:
        return "—"
    partes = str(iso)[:10].split("-")
    return f"{partes[2]}/{partes[1]}/{partes[0]}" if len(partes) == 3 else iso


def _dias_texto(iso, hoy):
    """Texto amable: 'venció hace 3 días', 'vence hoy', 'vence en 12 días'."""
    try:
        dias = (date.fromisoformat(str(iso)[:10]) - hoy).days
    except ValueError:
        return ""
    if dias < 0:
        return f"venció hace {-dias} día{'s' if dias != -1 else ''}"
    if dias == 0:
        return "vence hoy"
    return f"vence en {dias} día{'s' if dias != 1 else ''}"


def _cant(n):
    """3.0 -> '3' ; 2.5 -> '2,5'"""
    n = float(n or 0)
    return str(int(n)) if n.is_integer() else f"{n:.2f}".replace(".", ",")


def _pesos(n):
    return "$" + f"{float(n or 0):,.0f}".replace(",", ".")


def calcular_alertas(rol):
    """Devuelve la lista de alertas que este rol debe ver (rojas primero)."""
    db = get_db()
    hoy = date.today()
    hoy_txt = hoy.isoformat()
    jefe = rol in ("administrador", "director_tecnico")

    # Enlace para "arreglar" un producto: el jefe va a editarlo; el auxiliar
    # (que no puede editar) va a ver su kardex.
    def url_producto(pid):
        return (url_for("productos.editar", prod_id=pid) if jefe
                else url_for("inventario.kardex", producto_id=pid))

    alertas = []

    def agregar(clave, nivel, icono, titulo, explicacion, filas, item, url=None, boton=None):
        """Arma la alerta solo si hay filas. item(fila) -> {texto, detalle, url}."""
        if not filas:
            return
        alertas.append({
            "clave": clave, "nivel": nivel, "icono": icono, "titulo": titulo,
            "explicacion": explicacion, "total": len(filas),
            "items": [item(f) for f in filas[:MAX_ITEMS]],
            "url": url, "boton": boton,
        })

    # ------------------------------------------------------------------
    # 1. LOTES VENCIDOS que todavía tienen unidades (hay que sacarlos)
    # ------------------------------------------------------------------
    filas = db.execute(
        "SELECT l.id, l.lote, l.vencimiento, l.cantidad_disponible, p.nombre "
        "FROM lotes l JOIN productos p ON p.id = l.producto_id "
        "WHERE l.cantidad_disponible > 0 AND l.estado <> 'agotado' "
        "AND l.vencimiento IS NOT NULL AND l.vencimiento <> '' AND l.vencimiento < ? "
        "ORDER BY l.vencimiento", (hoy_txt,)).fetchall()
    agregar("lotes_vencidos", "rojo", "⛔", "Lotes vencidos en el inventario",
            "El POS ya no los vende. Sácalos de la estantería, sepáralos y "
            "regístralos como baja (Inventario → lote → Ajustar).",
            filas, lambda f: {
                "texto": f"{f['nombre']} · lote {f['lote'] or 's/n'}",
                "detalle": f"{_cant(f['cantidad_disponible'])} und · {_dias_texto(f['vencimiento'], hoy)}",
                "url": url_for("inventario.lote_ver", lote_id=f["id"]),
            }, url_for("inventario.lotes", vencimiento="vencidos"), "Ver lotes vencidos")

    # ------------------------------------------------------------------
    # 2. PRECIO POR ENCIMA DEL MÁXIMO REGULADO (riesgo de sanción)
    #    Revisa el precio normal y el de cada presentación (sobre, caja...)
    # ------------------------------------------------------------------
    filas = db.execute(
        "SELECT p.id, p.nombre, 'Unidad principal' AS pres, p.precio_venta AS precio, p.precio_maximo AS maximo "
        "FROM productos p WHERE p.activo = 1 AND p.precio_maximo > 0 AND p.precio_venta > p.precio_maximo + 0.01 "
        "UNION ALL "
        "SELECT p.id, p.nombre, u.nombre, pp.precio_venta, pp.precio_maximo "
        "FROM producto_presentaciones pp JOIN productos p ON p.id = pp.producto_id "
        "JOIN unidades_medida u ON u.id = pp.unidad_id "
        "WHERE p.activo = 1 AND pp.precio_maximo > 0 AND pp.precio_venta > pp.precio_maximo + 0.01 "
        "ORDER BY 2").fetchall()
    agregar("precio_maximo", "rojo", "💲", "Precio por encima del máximo regulado",
            "Vender por encima del precio máximo puede traer sanciones. Baja el precio de venta.",
            filas, lambda f: {
                "texto": f"{f['nombre']} ({f['pres']})",
                "detalle": f"vende a {_pesos(f['precio'])} · máximo {_pesos(f['maximo'])}",
                "url": url_producto(f["id"]),
            })

    # ------------------------------------------------------------------
    # 3. REGISTRO INVIMA vencido (rojo) o por vencer en 90 días (amarillo)
    # ------------------------------------------------------------------
    limite = (hoy + timedelta(days=DIAS_INVIMA)).isoformat()
    filas = db.execute(
        "SELECT id, nombre, registro_sanitario, registro_vence FROM productos "
        "WHERE activo = 1 AND registro_vence IS NOT NULL AND registro_vence <> '' "
        "AND registro_vence <= ? ORDER BY registro_vence", (limite,)).fetchall()
    item_invima = lambda f: {
        "texto": f"{f['nombre']}",
        "detalle": f"{f['registro_sanitario'] or 'sin número'} · {_dias_texto(f['registro_vence'], hoy)} "
                   f"({_fecha(f['registro_vence'])})",
        "url": url_producto(f["id"]),
    }
    agregar("invima_vencido", "rojo", "📄", "Registro INVIMA vencido",
            "Verifica en la página del INVIMA si fue renovado y actualiza la fecha; "
            "si no, el producto no se debe vender.",
            [f for f in filas if f["registro_vence"] < hoy_txt], item_invima)
    agregar("invima_por_vencer", "amarillo", "📄", f"Registro INVIMA vence en {DIAS_INVIMA} días o menos",
            "Pregunta al proveedor o laboratorio por la renovación.",
            [f for f in filas if f["registro_vence"] >= hoy_txt], item_invima)

    # ------------------------------------------------------------------
    # 4. PROVEEDORES: concepto sanitario vencido o por vencer (solo jefe)
    # ------------------------------------------------------------------
    if jefe:
        limite = (hoy + timedelta(days=DIAS_PROVEEDOR)).isoformat()
        filas = db.execute(
            "SELECT id, razon_social, concepto_vence FROM proveedores "
            "WHERE activo = 1 AND concepto_vence IS NOT NULL AND concepto_vence <> '' "
            "AND concepto_vence <= ? ORDER BY concepto_vence", (limite,)).fetchall()
        item_prov = lambda f: {
            "texto": f["razon_social"],
            "detalle": f"concepto sanitario {_dias_texto(f['concepto_vence'], hoy)} ({_fecha(f['concepto_vence'])})",
            "url": url_for("proveedores.editar", prov_id=f["id"]),
        }
        agregar("proveedor_vencido", "rojo", "🚚", "Proveedor con concepto sanitario vencido",
                "Pídele el concepto vigente antes de volver a comprarle.",
                [f for f in filas if f["concepto_vence"] < hoy_txt], item_prov,
                url_for("proveedores.lista"), "Ver proveedores")
        agregar("proveedor_por_vencer", "amarillo", "🚚",
                f"Concepto sanitario de proveedor vence en {DIAS_PROVEEDOR} días o menos",
                "Pídele al proveedor el documento renovado.",
                [f for f in filas if f["concepto_vence"] >= hoy_txt], item_prov,
                url_for("proveedores.lista"), "Ver proveedores")

    # ------------------------------------------------------------------
    # 4b. EQUIPOS: calibración vencida / no conforme (rojo), por vencer o
    #     sin calibración (amarillo). Ver app/equipos.py
    # ------------------------------------------------------------------
    from .equipos import ESTADOS, ULTIMO_RESULTADO, estado_calibracion
    equipos = []
    for f in db.execute("SELECT e.id, e.nombre, e.proxima_calibracion, " + ULTIMO_RESULTADO +
                        " FROM equipos e WHERE e.activo = 1 ORDER BY e.proxima_calibracion").fetchall():
        estado, _ = estado_calibracion(f["proxima_calibracion"], hoy)
        if f["ultimo_resultado"] == "no_conforme":
            estado = "no_conforme"
        equipos.append((estado, f))
    item_equipo = lambda par: {
        "texto": par[1]["nombre"],
        "detalle": (ESTADOS[par[0]][0] if par[0] in ("no_conforme", "sin") else
                    f"calibración {_dias_texto(par[1]['proxima_calibracion'], hoy)} "
                    f"({_fecha(par[1]['proxima_calibracion'])})"),
        "url": url_for("equipos.ver", equipo_id=par[1]["id"]),
    }
    agregar("calibracion_vencida", "rojo", "📏", "Equipo con calibración vencida o no conforme",
            "Las lecturas de temperatura con un equipo sin calibrar no valen ante la Secretaría. "
            "Calíbralo o reemplázalo.",
            [p for p in equipos if p[0] in ("vencida", "no_conforme")], item_equipo,
            url_for("equipos.lista"), "Ver equipos")
    agregar("calibracion_por_vencer", "amarillo", "📏", "Calibración de equipos por vencer o sin registrar",
            "Agenda la calibración con un laboratorio y sube el certificado.",
            [p for p in equipos if p[0] in ("por_vencer", "sin")], item_equipo,
            url_for("equipos.lista"), "Ver equipos")

    # ------------------------------------------------------------------
    # 5. STOCK: agotados (rojo) y por debajo del mínimo (amarillo).
    #    Solo productos con "stock mínimo" definido: así un producto que no
    #    se maneja (mínimo 0) no llena el panel de avisos.
    # ------------------------------------------------------------------
    filas = db.execute(
        f"SELECT p.id, p.nombre, p.stock_minimo, {SQL_STOCK} AS stock FROM productos p "
        "WHERE p.activo = 1 AND p.stock_minimo > 0 "
        f"AND {SQL_STOCK} <= p.stock_minimo ORDER BY stock, p.nombre COLLATE NOCASE",
        {"hoy": hoy_txt}).fetchall()
    item_stock = lambda f: {
        "texto": f["nombre"],
        "detalle": f"hay {_cant(f['stock'])} · mínimo {_cant(f['stock_minimo'])}",
        "url": url_for("inventario.kardex", producto_id=f["id"]),
    }
    agregar("agotados", "rojo", "📭", "Productos agotados",
            "Tienen stock mínimo definido y no queda nada para vender. Pídelos al proveedor.",
            [f for f in filas if f["stock"] <= 0], item_stock)
    agregar("stock_minimo", "amarillo", "📉", "Productos en o por debajo del stock mínimo",
            "Inclúyelos en el próximo pedido.",
            [f for f in filas if f["stock"] > 0], item_stock)

    # ------------------------------------------------------------------
    # 6. LOTES POR VENCER en los próximos 30 días (para rotarlos o devolverlos)
    # ------------------------------------------------------------------
    limite = (hoy + timedelta(days=DIAS_LOTE)).isoformat()
    filas = db.execute(
        "SELECT l.id, l.lote, l.vencimiento, l.cantidad_disponible, p.nombre "
        "FROM lotes l JOIN productos p ON p.id = l.producto_id "
        "WHERE l.cantidad_disponible > 0 AND l.estado = 'disponible' "
        "AND l.vencimiento >= ? AND l.vencimiento <= ? ORDER BY l.vencimiento",
        (hoy_txt, limite)).fetchall()
    agregar("lotes_por_vencer", "amarillo", "⏳", f"Lotes que vencen en {DIAS_LOTE} días o menos",
            "Ponlos adelante para venderlos primero, o gestiona la devolución con el proveedor.",
            filas, lambda f: {
                "texto": f"{f['nombre']} · lote {f['lote'] or 's/n'}",
                "detalle": f"{_cant(f['cantidad_disponible'])} und · {_dias_texto(f['vencimiento'], hoy)}",
                "url": url_for("inventario.lote_ver", lote_id=f["id"]),
            }, url_for("inventario.vencimientos"), "Ver semáforo de vencimientos")

    # ------------------------------------------------------------------
    # 7. RECEPCIONES EN CUARENTENA esperando aprobación del director técnico
    # ------------------------------------------------------------------
    filas = db.execute(
        "SELECT r.id, r.numero, r.fecha, r.factura_numero, pr.razon_social "
        "FROM recepciones r JOIN proveedores pr ON pr.id = r.proveedor_id "
        "WHERE r.estado = 'cuarentena' ORDER BY r.fecha").fetchall()
    agregar("cuarentena", "amarillo", "📦", "Recepciones en cuarentena",
            "Esa mercancía no se puede vender hasta que el director técnico la apruebe.",
            filas, lambda f: {
                "texto": f"{f['numero']} · {f['razon_social']}",
                "detalle": f"factura {f['factura_numero'] or '—'} · {_fecha(f['fecha'])}",
                "url": url_for("recepciones.ver", rec_id=f["id"]),
            }, url_for("recepciones.lista", filtro="cuarentena"), "Ver recepciones")

    # ------------------------------------------------------------------
    # 8. PRODUCTOS SIN PRECIO DE VENTA (típico después de importar el Excel)
    # ------------------------------------------------------------------
    if jefe:
        filas = db.execute(
            "SELECT id, nombre FROM productos WHERE activo = 1 "
            "AND (precio_venta IS NULL OR precio_venta <= 0) ORDER BY nombre COLLATE NOCASE").fetchall()
        agregar("sin_precio", "amarillo", "🏷️", "Productos sin precio de venta",
                "No se pueden vender en el POS hasta ponerles precio.",
                filas, lambda f: {"texto": f["nombre"], "detalle": "", "url": url_producto(f["id"])})

    # ------------------------------------------------------------------
    # 9. CAJA ABIERTA DESDE UN DÍA ANTERIOR (se olvidó cerrarla)
    # ------------------------------------------------------------------
    filas = db.execute(
        "SELECT id, numero, abierta_en, abierta_por_nombre FROM cajas "
        "WHERE estado = 'abierta' AND abierta_en < ?", (hoy_txt,)).fetchall()
    agregar("caja_vieja", "amarillo", "💵", "Caja abierta desde un día anterior",
            "Ciérrala con el conteo del efectivo para que las ventas de cada día queden separadas.",
            filas, lambda f: {
                "texto": f"Caja {f['numero']}",
                "detalle": f"abierta el {_fecha(f['abierta_en'])} por {f['abierta_por_nombre'] or '—'}",
                "url": url_for("pos.index"),
            })

    # Rojas primero; dentro de cada color se respeta el orden de arriba
    alertas.sort(key=lambda a: 0 if a["nivel"] == "rojo" else 1)
    return alertas
