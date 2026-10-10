"""Devoluciones: de un CLIENTE (sale de una venta) y a un PROVEEDOR.

CÓMO FUNCIONA (para aprender):

  DEVOLUCIÓN DE CLIENTE  (numeración DC-0001)
    1. Se busca la venta (ej: V-0012). Solo ventas completadas (no anuladas).
    2. Por cada producto se elige cuánto devuelve (máximo lo que compró menos
       lo que ya devolvió antes) y qué pasa con él:
         - "reingreso": está bueno -> vuelve al MISMO lote del que salió.
         - "baja":      está dañado o abierto -> NO vuelve al inventario.
    3. Se le devuelve la plata en proporción a lo que pagó (con su descuento),
       saliendo de la CAJA ABIERTA (efectivo, Nequi, Davivienda o tarjeta).
       Queda como una "salida" de la caja, así el cierre cuadra.
    4. En Utilidades, lo devuelto se RESTA de las ventas. Si reingresó, también
       se resta su costo; si se dio de baja, el costo se queda (es una pérdida).

  DEVOLUCIÓN A PROVEEDOR  (numeración DP-0001)
    1. Se eligen lotes y cantidades (vencidos, averiados, error de pedido...).
    2. Salen del inventario (kardex tipo 'devolucion').
    3. Si el proveedor NO reconoce el valor (sin nota crédito ni cambio), el
       movimiento es tipo 'baja' y Utilidades lo cuenta como pérdida.
    4. Se genera un acta en PDF.

  Solo administrador y director técnico. Todo queda en la bitácora.
"""
import json
from datetime import date, datetime
from io import BytesIO

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   send_file, url_for)

from .audit import registrar
from .auth import roles_required
from .db import ahora, get_db
from .formato import pesos

bp = Blueprint("devoluciones", __name__, url_prefix="/devoluciones")

FORMAS_REEMBOLSO = {"efectivo": "Efectivo", "nequi": "Nequi", "davivienda": "Davivienda", "tarjeta": "Tarjeta"}
MOTIVOS_PROVEEDOR = ["Producto vencido", "Próximo a vencer", "Averiado / empaque dañado",
                     "Error en el pedido", "Retiro del mercado (alerta INVIMA)", "Otro"]
JEFES = ("administrador", "director_tecnico")


class _Error(Exception):
    """Error de negocio: el mensaje se le muestra a la persona."""


def _numero(tipo):
    """Siguiente número: DC-0001 para clientes, DP-0001 para proveedores."""
    prefijo = "DC" if tipo == "cliente" else "DP"
    fila = get_db().execute("SELECT numero FROM devoluciones WHERE tipo = ? ORDER BY id DESC LIMIT 1",
                            (tipo,)).fetchone()
    n = int(fila["numero"].split("-")[1]) + 1 if fila else 1
    return f"{prefijo}-{n:04d}"


def _cantidad(texto):
    """'2' -> 2.0 ; '1,5' -> 1.5 ; vacío o inválido -> 0."""
    try:
        return max(0.0, float((texto or "").replace(",", ".")))
    except ValueError:
        return -1.0      # inválido: se rechaza más adelante


# ======================================================================
# LISTA
# ======================================================================

@bp.route("/")
@roles_required(*JEFES)
def lista():
    filas = get_db().execute(
        "SELECT d.*, v.consecutivo AS venta, pr.razon_social AS proveedor, "
        "       (SELECT COUNT(*) FROM devolucion_lineas l WHERE l.devolucion_id = d.id) AS n_lineas "
        "FROM devoluciones d LEFT JOIN ventas v ON v.id = d.venta_id "
        "LEFT JOIN proveedores pr ON pr.id = d.proveedor_id ORDER BY d.id DESC LIMIT 300").fetchall()
    return render_template("devoluciones/lista.html", devoluciones=filas)


@bp.route("/<int:dev_id>")
@roles_required(*JEFES)
def ver(dev_id):
    dev = get_db().execute(
        "SELECT d.*, v.consecutivo AS venta, pr.razon_social AS proveedor, pr.nit AS proveedor_nit "
        "FROM devoluciones d LEFT JOIN ventas v ON v.id = d.venta_id "
        "LEFT JOIN proveedores pr ON pr.id = d.proveedor_id WHERE d.id = ?", (dev_id,)).fetchone()
    if dev is None:
        abort(404)
    lineas = get_db().execute(
        "SELECT l.*, lo.lote AS lote_codigo, lo.vencimiento FROM devolucion_lineas l "
        "LEFT JOIN lotes lo ON lo.id = l.lote_id WHERE l.devolucion_id = ? ORDER BY l.id", (dev_id,)).fetchall()
    return render_template("devoluciones/ver.html", d=dev, lineas=lineas, formas=FORMAS_REEMBOLSO)


# ======================================================================
# DEVOLUCIÓN DE CLIENTE
# ======================================================================

def _lineas_devolvibles(venta_id):
    """Líneas de la venta con lo que aún se puede devolver de cada una."""
    db = get_db()
    salida = []
    for ln in db.execute("SELECT * FROM venta_lineas WHERE venta_id = ? ORDER BY id", (venta_id,)):
        ya = db.execute("SELECT COALESCE(SUM(cantidad), 0) FROM devolucion_lineas WHERE venta_linea_id = ?",
                        (ln["id"],)).fetchone()[0]
        d = dict(ln)
        d["ya_devuelto"] = ya
        d["disponible"] = round(ln["cantidad"] - ya, 4)
        # La VENTA LIBRE (ej: una inyectología) no se devuelve: no hay producto
        # que vuelva al inventario. Si se cobró mal, se anula la venta completa.
        if ln["es_libre"]:
            d["disponible"] = 0
        salida.append(d)
    return salida


@bp.route("/cliente", methods=["GET", "POST"])
@roles_required(*JEFES)
def cliente():
    """Paso 1: buscar la venta por su número (ej: V-0012). Paso 2: elegir qué devuelve."""
    db = get_db()
    buscado = (request.values.get("venta") or "").strip().upper()
    venta = None
    if buscado:
        if buscado.isdigit():                      # escribieron solo "12" -> V-0012
            buscado = f"V-{int(buscado):04d}"
        venta = db.execute("SELECT * FROM ventas WHERE consecutivo = ?", (buscado,)).fetchone()
        if venta is None:
            flash(f"No existe la venta {buscado}.", "error")
        elif venta["estado"] != "completada":
            flash(f"La venta {buscado} está anulada: no tiene nada que devolver.", "error")
            venta = None

    if request.method == "POST" and venta is not None:
        try:
            dev_id = _registrar_devolucion_cliente(venta)
        except _Error as e:
            flash(str(e), "error")
        else:
            return redirect(url_for("devoluciones.ver", dev_id=dev_id))

    caja = db.execute("SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1").fetchone()
    return render_template("devoluciones/cliente.html", buscado=buscado, venta=venta, caja=caja,
                           lineas=_lineas_devolvibles(venta["id"]) if venta else [],
                           formas=FORMAS_REEMBOLSO)


def _registrar_devolucion_cliente(venta):
    """Guarda la devolución de un cliente. O se guarda TODO, o NADA."""
    db = get_db()
    motivo = (request.form.get("motivo") or "").strip()
    forma = request.form.get("forma_reembolso")
    if len(motivo) < 3:
        raise _Error("Escribe el motivo de la devolución.")
    if forma not in FORMAS_REEMBOLSO:
        raise _Error("Elige cómo se le devuelve la plata al cliente.")
    caja = db.execute("SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1").fetchone()
    if caja is None:
        raise _Error("Abre la caja del POS: la plata de la devolución sale de la caja abierta.")

    # Qué devuelve de cada línea (los campos del formulario se llaman cant_<id de la línea>)
    elegidas = []
    for ln in _lineas_devolvibles(venta["id"]):
        cantidad = _cantidad(request.form.get(f"cant_{ln['id']}"))
        if cantidad < 0:
            raise _Error(f"{ln['producto_nombre']}: la cantidad no es válida.")
        if cantidad == 0:
            continue
        if cantidad > ln["disponible"] + 1e-9:
            raise _Error(f"{ln['producto_nombre']}: solo se pueden devolver {ln['disponible']:g}.")
        destino = "baja" if request.form.get(f"destino_{ln['id']}") == "baja" else "reingreso"
        elegidas.append((ln, cantidad, destino))
    if not elegidas:
        raise _Error("Escribe cuántas unidades devuelve de al menos un producto.")

    db.execute("BEGIN IMMEDIATE")
    try:
        numero = _numero("cliente")
        dev_id = db.execute(
            "INSERT INTO devoluciones (numero, tipo, fecha, venta_id, motivo, forma_reembolso, caja_id, "
            "usuario_id, usuario_nombre, creado_en) VALUES (?, 'cliente', ?,?,?,?,?,?,?,?)",
            (numero, ahora(), venta["id"], motivo, forma, caja["id"], g.user["id"], g.user["nombre"],
             ahora())).lastrowid

        tot_sub = tot_iva = tot_total = tot_costo = 0.0
        for ln, cantidad, destino in elegidas:
            proporcion = cantidad / ln["cantidad"]          # ej: devuelve 1 de 3 -> 1/3 de lo que pagó
            subtotal = round(ln["subtotal"] * proporcion)
            total = round(ln["total"] * proporcion)
            iva = total - subtotal
            factor = ln["factor"] or 1
            unidades = round(cantidad * factor, 4)

            # Costo y lotes: se devuelve primero al ÚLTIMO lote del que salió.
            # Si de esta línea ya hubo devoluciones antes, se descuenta lo que
            # ya se devolvió de cada lote (para no devolver más de lo que salió).
            asignaciones = json.loads(ln["lotes_json"] or "[]")
            ya_por_lote = {}
            for previa in db.execute("SELECT lotes_json FROM devolucion_lineas WHERE venta_linea_id = ?",
                                     (ln["id"],)):
                for v in json.loads(previa["lotes_json"] or "[]"):
                    ya_por_lote[v["lote_id"]] = ya_por_lote.get(v["lote_id"], 0) + v["cantidad"]
            pendiente, vuelve, costo = unidades, [], 0.0
            for a in reversed(asignaciones):
                if pendiente <= 1e-9:
                    break
                libre = a["cantidad"] - ya_por_lote.get(a["lote_id"], 0)
                if libre <= 1e-9:
                    continue
                toma = min(pendiente, libre)
                lote = db.execute("SELECT * FROM lotes WHERE id = ?", (a["lote_id"],)).fetchone()
                costo += toma * (lote["costo_unitario"] if lote else 0)
                vuelve.append({"lote_id": a["lote_id"], "lote": a.get("lote"), "cantidad": toma})
                pendiente -= toma

            if destino == "reingreso":
                for v in vuelve:
                    lote = db.execute("SELECT estado FROM lotes WHERE id = ?", (v["lote_id"],)).fetchone()
                    # Un lote que había quedado "agotado" vuelve a estar disponible
                    nuevo_estado = "disponible" if lote and lote["estado"] == "agotado" else (lote["estado"] if lote else None)
                    db.execute("UPDATE lotes SET cantidad_disponible = cantidad_disponible + ?, estado = ?, "
                               "actualizado_en = ? WHERE id = ?", (v["cantidad"], nuevo_estado, ahora(), v["lote_id"]))
                    db.execute(
                        "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, referencia, "
                        "referencia_id, usuario_id, usuario_nombre, observaciones, creado_en) "
                        "VALUES (?,?,?, 'devolucion', ?,?,?,?,?,?,?)",
                        (ahora(), v["lote_id"], ln["producto_id"], v["cantidad"],
                         f"Devolución {numero} (venta {venta['consecutivo']})", dev_id,
                         g.user["id"], g.user["nombre"], motivo, ahora()))

            db.execute(
                "INSERT INTO devolucion_lineas (devolucion_id, producto_id, producto_nombre, venta_linea_id, "
                "presentacion, cantidad, unidades, destino, subtotal, iva, total, costo, lotes_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (dev_id, ln["producto_id"], ln["producto_nombre"], ln["id"], ln["presentacion"], cantidad,
                 unidades, destino, subtotal, iva, total, costo, json.dumps(vuelve, ensure_ascii=False)))
            tot_sub += subtotal
            tot_iva += iva
            tot_total += total
            tot_costo += costo

        db.execute("UPDATE devoluciones SET subtotal=?, iva=?, total=?, costo=? WHERE id=?",
                   (tot_sub, tot_iva, tot_total, tot_costo, dev_id))
        # La plata sale de la caja abierta (así el cierre de caja cuadra)
        db.execute(
            "INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, usuario_id, "
            "usuario_nombre, creado_en) VALUES (?,?, 'salida', ?,?,?,?,?,?)",
            (caja["id"], ahora(), forma, tot_total, f"Devolución {numero} (venta {venta['consecutivo']})",
             g.user["id"], g.user["nombre"], ahora()))
        db.commit()
    except Exception:
        db.rollback()
        raise

    registrar("devolucion_cliente", "devoluciones", dev_id,
              f"{numero} venta={venta['consecutivo']} total={tot_total} forma={forma} motivo={motivo}")
    flash(f"Devolución {numero} registrada: entrégale {pesos(tot_total)} al cliente ({FORMAS_REEMBOLSO[forma]}).", "ok")
    return dev_id


# ======================================================================
# DEVOLUCIÓN A PROVEEDOR
# ======================================================================

@bp.route("/proveedor", methods=["GET", "POST"])
@roles_required(*JEFES)
def proveedor():
    """Elegir lotes y cantidades para devolver al proveedor."""
    db = get_db()
    q = (request.values.get("q") or "").strip()
    lote_id = request.values.get("lote", type=int)

    if request.method == "POST":
        try:
            dev_id = _registrar_devolucion_proveedor()
        except _Error as e:
            flash(str(e), "error")
        else:
            return redirect(url_for("devoluciones.ver", dev_id=dev_id))

    # Lotes con existencias (de cualquier estado: los vencidos y bloqueados también se devuelven)
    sql = ("SELECT l.*, p.nombre AS producto_nombre, p.codigo AS producto_codigo, "
           "       r.proveedor_id, pr.razon_social AS proveedor_nombre "
           "FROM lotes l JOIN productos p ON p.id = l.producto_id "
           "LEFT JOIN recepciones r ON r.id = l.recepcion_id "
           "LEFT JOIN proveedores pr ON pr.id = r.proveedor_id "
           "WHERE l.cantidad_disponible > 0 AND l.estado <> 'rechazado'")
    params = []
    if lote_id:
        sql += " AND l.id = ?"
        params.append(lote_id)
    elif q:
        sql += " AND (p.nombre LIKE ? OR p.codigo LIKE ? OR l.lote LIKE ? OR p.codigo_barras = ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%", q]
    else:
        # Sin búsqueda: primero lo vencido y lo que vence pronto (lo más común de devolver)
        sql += " AND l.vencimiento IS NOT NULL AND l.vencimiento <> '' AND l.vencimiento <= date('now', '+90 day')"
    sql += " ORDER BY l.vencimiento IS NULL, l.vencimiento, p.nombre LIMIT 100"
    lotes = db.execute(sql, params).fetchall()
    proveedores = db.execute("SELECT id, razon_social FROM proveedores WHERE activo = 1 "
                             "ORDER BY razon_social COLLATE NOCASE").fetchall()
    sugerido = next((l["proveedor_id"] for l in lotes if l["proveedor_id"]), None)
    return render_template("devoluciones/proveedor.html", lotes=lotes, q=q, lote_id=lote_id,
                           proveedores=proveedores, proveedor_sugerido=sugerido,
                           motivos=MOTIVOS_PROVEEDOR, hoy=date.today().isoformat())


def _registrar_devolucion_proveedor():
    db = get_db()
    proveedor_id = request.form.get("proveedor_id", type=int)
    motivo = request.form.get("motivo") or ""
    detalle = (request.form.get("detalle") or "").strip()
    if motivo not in MOTIVOS_PROVEEDOR:
        raise _Error("Elige el motivo de la devolución.")
    if motivo == "Otro" and len(detalle) < 3:
        raise _Error("Escribe el motivo de la devolución.")
    prov = db.execute("SELECT * FROM proveedores WHERE id = ?", (proveedor_id,)).fetchone() if proveedor_id else None
    if prov is None:
        raise _Error("Elige el proveedor al que se devuelve.")
    con_credito = 1 if request.form.get("con_credito") else 0
    nota = (request.form.get("nota_credito") or "").strip() or None

    # Cantidades: campos cant_<id del lote>
    elegidos = []
    for clave, valor in request.form.items():
        if not clave.startswith("cant_") or not valor.strip():
            continue
        cantidad = _cantidad(valor)
        lote = db.execute("SELECT l.*, p.nombre AS producto_nombre FROM lotes l "
                          "JOIN productos p ON p.id = l.producto_id WHERE l.id = ?",
                          (int(clave[5:]) if clave[5:].isdigit() else 0,)).fetchone()
        if lote is None or cantidad < 0:
            raise _Error("Hay una cantidad inválida.")
        if cantidad == 0:
            continue
        if cantidad > lote["cantidad_disponible"] + 1e-9:
            raise _Error(f"{lote['producto_nombre']} (lote {lote['lote'] or 's/n'}): solo hay "
                         f"{lote['cantidad_disponible']:g}.")
        elegidos.append((lote, cantidad))
    if not elegidos:
        raise _Error("Escribe la cantidad a devolver de al menos un lote.")

    motivo_txt = motivo + (f": {detalle}" if detalle else "")
    # Con nota crédito el proveedor devuelve el valor -> no es pérdida ('devolucion').
    # Sin crédito, la mercancía se pierde -> 'baja' (Utilidades la cuenta como pérdida).
    tipo_mov = "devolucion" if con_credito else "baja"

    db.execute("BEGIN IMMEDIATE")
    try:
        numero = _numero("proveedor")
        dev_id = db.execute(
            "INSERT INTO devoluciones (numero, tipo, fecha, proveedor_id, motivo, con_credito, nota_credito, "
            "usuario_id, usuario_nombre, creado_en) VALUES (?, 'proveedor', ?,?,?,?,?,?,?,?)",
            (numero, ahora(), prov["id"], motivo_txt, con_credito, nota, g.user["id"], g.user["nombre"],
             ahora())).lastrowid
        total = 0.0
        for lote, cantidad in elegidos:
            costo = cantidad * (lote["costo_unitario"] or 0)
            restante = lote["cantidad_disponible"] - cantidad
            estado = "agotado" if restante <= 1e-9 and lote["estado"] == "disponible" else lote["estado"]
            db.execute("UPDATE lotes SET cantidad_disponible = ?, estado = ?, actualizado_en = ? WHERE id = ?",
                       (max(0, restante), estado, ahora(), lote["id"]))
            db.execute(
                "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, referencia, "
                "referencia_id, usuario_id, usuario_nombre, observaciones, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ahora(), lote["id"], lote["producto_id"], tipo_mov, -cantidad,
                 f"Devolución a proveedor {numero}", dev_id, g.user["id"], g.user["nombre"], motivo_txt, ahora()))
            db.execute(
                "INSERT INTO devolucion_lineas (devolucion_id, producto_id, producto_nombre, lote_id, cantidad, "
                "unidades, destino, total, costo) VALUES (?,?,?,?,?,?, 'proveedor', ?,?)",
                (dev_id, lote["producto_id"], lote["producto_nombre"], lote["id"], cantidad, cantidad, costo, costo))
            total += costo
        db.execute("UPDATE devoluciones SET total = ?, costo = ?, subtotal = ? WHERE id = ?", (total, total, total, dev_id))
        db.commit()
    except Exception:
        db.rollback()
        raise

    registrar("devolucion_proveedor", "devoluciones", dev_id,
              f"{numero} proveedor={prov['razon_social']} valor={total} con_credito={con_credito} motivo={motivo_txt}")
    flash(f"Devolución {numero} registrada. Descarga el acta para que el proveedor la firme.", "ok")
    return dev_id


# ======================================================================
# ACTA EN PDF (sirve para los dos tipos)
# ======================================================================

@bp.route("/<int:dev_id>/pdf")
@roles_required(*JEFES)
def acta(dev_id):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .configuracion import obtener_config
    from .pdf_utils import encabezado_pdf

    db = get_db()
    d = db.execute("SELECT d.*, v.consecutivo AS venta, pr.razon_social AS proveedor, pr.nit AS proveedor_nit "
                   "FROM devoluciones d LEFT JOIN ventas v ON v.id = d.venta_id "
                   "LEFT JOIN proveedores pr ON pr.id = d.proveedor_id WHERE d.id = ?", (dev_id,)).fetchone()
    if d is None:
        abort(404)
    lineas = db.execute("SELECT l.*, lo.lote AS lote_codigo, lo.vencimiento FROM devolucion_lineas l "
                        "LEFT JOIN lotes lo ON lo.id = l.lote_id WHERE l.devolucion_id = ?", (dev_id,)).fetchall()
    config = obtener_config()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=f"Devolución {d['numero']}")
    estilos = getSampleStyleSheet()
    sub = ParagraphStyle("Sub", parent=estilos["Normal"], fontSize=9.5, leading=13)
    celda = ParagraphStyle("Celda", parent=estilos["Normal"], fontSize=8.5)
    der = ParagraphStyle("Der", parent=celda, alignment=2)
    fecha = datetime.fromisoformat(d["fecha"]).strftime("%d/%m/%Y %H:%M")

    if d["tipo"] == "proveedor":
        titulo = f"ACTA DE DEVOLUCIÓN A PROVEEDOR N.º {d['numero']}"
        datos = (f"Fecha: <b>{fecha}</b><br/>Proveedor: <b>{d['proveedor']}</b> (NIT {d['proveedor_nit']})<br/>"
                 f"Motivo: {d['motivo']}<br/>"
                 f"Nota crédito / cambio: {'Sí' + (' — N.º ' + d['nota_credito'] if d['nota_credito'] else '') if d['con_credito'] else 'No (se registra como pérdida)'}")
        cabeza = ["Producto", "Lote", "Vence", "Cantidad", "Costo"]
        filas = [[l["producto_nombre"], l["lote_codigo"] or "s/n",
                  (l["vencimiento"] or "—")[8:10] + "/" + (l["vencimiento"] or "")[5:7] + "/" + (l["vencimiento"] or "")[0:4]
                  if l["vencimiento"] else "—", f"{l['cantidad']:g}", pesos(l["costo"])] for l in lineas]
        firmas = ("Entrega (droguería)", "Recibe (proveedor)")
    else:
        titulo = f"DEVOLUCIÓN DE CLIENTE N.º {d['numero']}"
        datos = (f"Fecha: <b>{fecha}</b> · Venta: <b>{d['venta']}</b><br/>Motivo: {d['motivo']}<br/>"
                 f"Reembolso: {FORMAS_REEMBOLSO.get(d['forma_reembolso'], d['forma_reembolso'])}")
        cabeza = ["Producto", "Presentación", "Destino", "Cantidad", "Valor"]
        filas = [[l["producto_nombre"], l["presentacion"] or "—",
                  "Vuelve al inventario" if l["destino"] == "reingreso" else "Baja (no vuelve)",
                  f"{l['cantidad']:g}", pesos(l["total"])] for l in lineas]
        firmas = ("Entrega (droguería)", "Recibe (cliente)")

    elementos = list(encabezado_pdf(config, titulo))
    elementos += [Spacer(1, 6), Paragraph(datos, sub), Spacer(1, 10)]
    data = [[Paragraph(f"<b>{c}</b>", celda if i < 3 else der) for i, c in enumerate(cabeza)]]
    data += [[Paragraph(str(x), celda if i < 3 else der) for i, x in enumerate(f)] for f in filas]
    data.append([Paragraph("<b>Total</b>", celda), "", "", "", Paragraph(f"<b>{pesos(d['total'])}</b>", der)])
    tabla = Table(data, colWidths=[6.5 * cm, 2.8 * cm, 3.2 * cm, 2 * cm, 2.6 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe6ef")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elementos += [tabla, Spacer(1, 40)]
    firma = Table([[Paragraph("_______________________________<br/>" + firmas[0], sub),
                    Paragraph("_______________________________<br/>" + firmas[1], sub)]],
                  colWidths=[8.5 * cm, 8.5 * cm])
    elementos.append(firma)
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(f"Registró: {d['usuario_nombre'] or '—'}", sub))

    doc.build(elementos)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=f"devolucion_{d['numero']}.pdf")
