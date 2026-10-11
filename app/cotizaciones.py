"""
COTIZACIONES
============

Un cliente pregunta "¿cuánto me sale todo esto?". Se arma el carrito en el
POS como si fuera a vender y, en vez de cobrar, se toca "Guardar como
cotización" (menú ☰ del POS). Queda guardada con un número (COT-0001):
    - se imprime en la tirilla o se manda por WhatsApp;
    - si el cliente vuelve, "Cargar en el POS" la pone en una venta nueva con
      los precios que se le cotizaron (mientras esté vigente) y se cobra;
    - al cobrarla queda "convertida" y enlazada a la venta.

Una cotización NO descuenta inventario ni mueve plata: es solo un papel.
Vigencia: 8 días por defecto. Vencida, se puede cargar igual, pero con los
precios de hoy.
"""
import json
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .audit import registrar
from .auth import login_required
from .configuracion import obtener_config
from .db import ahora, get_db
from . import presentaciones as pres

bp = Blueprint("cotizaciones", __name__, url_prefix="/cotizaciones")

VALIDEZ_DIAS = 8


def _siguiente_numero(db):
    fila = db.execute("SELECT numero FROM cotizaciones ORDER BY id DESC LIMIT 1").fetchone()
    n = int(fila["numero"].split("-")[-1]) + 1 if fila else 1
    return f"COT-{n:04d}"


def _vence(c):
    """Fecha (aaaa-mm-dd) hasta la que vale la cotización."""
    return (datetime.strptime(c["fecha"][:10], "%Y-%m-%d") + timedelta(days=c["validez_dias"])).strftime("%Y-%m-%d")


def _estado(c):
    """'vigente', 'vencida', 'convertida' o 'anulada' (vigente/vencida se calcula con la fecha)."""
    if c["estado"] != "abierta":
        return c["estado"]
    return "vigente" if date.today().isoformat() <= _vence(c) else "vencida"


def _obtener(cot_id):
    c = get_db().execute("SELECT * FROM cotizaciones WHERE id = ?", (cot_id,)).fetchone()
    if c is None:
        abort(404)
    return c


def _lineas(cot_id):
    return get_db().execute("SELECT * FROM cotizacion_lineas WHERE cotizacion_id = ? ORDER BY id",
                            (cot_id,)).fetchall()


def _telefono_whatsapp(tel):
    """'300 123 4567' -> '573001234567' (WhatsApp necesita el indicativo de Colombia)."""
    digitos = "".join(c for c in str(tel or "") if c.isdigit())
    if len(digitos) == 10 and digitos.startswith("3"):
        return "57" + digitos
    return digitos


def texto_whatsapp(c, lineas, config):
    """El mensaje que se manda por WhatsApp (texto simple, una línea por producto)."""
    from .formato import pesos
    negocio = config["nombre_comercial"] or config["razon_social"] or "Droguería"
    partes = [f"*{negocio}* · Cotización {c['numero']}",
              f"Válida hasta {_vence(c)[8:10]}/{_vence(c)[5:7]}/{_vence(c)[:4]}", ""]
    for l in lineas:
        nombre = l["descripcion"] + (f" ({l['presentacion']})" if l["presentacion"] else "")
        partes.append(f"• {l['cantidad']:g} x {nombre}: {pesos(l['total'])}")
    partes += ["", f"*Total: {pesos(c['total'])}*"]
    if c["notas"]:
        partes.append(c["notas"])
    return "\n".join(partes)


# ---------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------
@bp.route("/")
@login_required
def lista():
    filtro = request.args.get("filtro", "abiertas")
    q = (request.args.get("q") or "").strip()
    sql = "SELECT * FROM cotizaciones"
    cond, params = [], []
    if filtro == "abiertas":
        cond.append("estado = 'abierta'")
    elif filtro in ("convertida", "anulada"):
        cond.append("estado = ?")
        params.append(filtro)
    if q:
        cond.append("(numero LIKE ? OR cliente_nombre LIKE ? OR cliente_telefono LIKE ?)")
        params += [f"%{q}%"] * 3
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    filas = get_db().execute(sql + " ORDER BY id DESC LIMIT 300", params).fetchall()
    cotizaciones = [dict(c, estado_txt=_estado(c), vence=_vence(c)) for c in filas]
    return render_template("cotizaciones/lista.html", cotizaciones=cotizaciones, filtro=filtro, q=q)


# ---------------------------------------------------------------------
# Ver / imprimir (tirilla 58 u 80 mm, como el comprobante de venta)
# ---------------------------------------------------------------------
@bp.route("/<int:cot_id>")
@login_required
def ver(cot_id):
    c = _obtener(cot_id)
    lineas = _lineas(cot_id)
    config = obtener_config()
    from urllib.parse import quote
    whatsapp = (f"https://wa.me/{_telefono_whatsapp(c['cliente_telefono'])}?text=" if c["cliente_telefono"]
                else "https://wa.me/?text=") + quote(texto_whatsapp(c, lineas, config))
    return render_template("cotizaciones/ver.html", c=c, lineas=lineas, config=config,
                           estado=_estado(c), vence=_vence(c), whatsapp=whatsapp)


@bp.route("/<int:cot_id>/anular", methods=["POST"])
@login_required
def anular(cot_id):
    c = _obtener(cot_id)
    if c["estado"] != "abierta":
        flash("Esa cotización ya no está abierta.", "error")
        return redirect(url_for("cotizaciones.ver", cot_id=cot_id))
    db = get_db()
    db.execute("UPDATE cotizaciones SET estado = 'anulada', anulada_motivo = ?, actualizado_en = ? WHERE id = ?",
               ((request.form.get("motivo") or "").strip() or None, ahora(), cot_id))
    db.commit()
    registrar("cotizacion_anulada", "cotizaciones", cot_id, c["numero"])
    flash(f"Cotización {c['numero']} anulada.", "ok")
    return redirect(url_for("cotizaciones.lista"))


# ---------------------------------------------------------------------
# API para el POS
# ---------------------------------------------------------------------
@bp.route("/api/crear", methods=["POST"])
@login_required
def api_crear():
    """Guarda el carrito del POS como cotización.

    El carrito llega como en el cobro, pero cada línea trae también su precio
    (el que se ve en el carrito, que puede ser el normal o uno cambiado).
    """
    try:
        carrito = json.loads(request.form.get("carrito") or "[]")
    except (json.JSONDecodeError, TypeError):
        return jsonify({"ok": False, "error": "El carrito llegó dañado."}), 400
    if not isinstance(carrito, list) or not carrito:
        return jsonify({"ok": False, "error": "El carrito está vacío."}), 400
    try:
        validez = max(1, min(90, int(request.form.get("validez_dias") or VALIDEZ_DIAS)))
    except ValueError:
        validez = VALIDEZ_DIAS
    db = get_db()
    lineas, total = [], 0.0
    for it in carrito:
        try:
            cantidad = float(it.get("cantidad"))
            precio = float(it.get("precio"))
            desc = float(it.get("descuento_pct") or 0)
        except (TypeError, ValueError, AttributeError):
            return jsonify({"ok": False, "error": "Hay una línea con datos inválidos."}), 400
        if cantidad <= 0 or precio <= 0:
            return jsonify({"ok": False, "error": "Cada línea necesita cantidad y precio mayores a cero."}), 400
        unitario = round(precio * (1 - desc / 100), 2)
        if it.get("libre"):
            linea = {"producto_id": None, "presentacion_id": 0, "descripcion": str(it.get("descripcion") or "Venta libre"),
                     "presentacion": None, "iva_tarifa": float(it.get("iva_tarifa") or 0)}
        else:
            prod = db.execute("SELECT * FROM productos WHERE id = ?", (it.get("producto_id"),)).fetchone()
            if prod is None:
                return jsonify({"ok": False, "error": "Un producto del carrito ya no existe."}), 400
            pid_pres = int(it.get("presentacion_id") or 0)
            p = pres.presentacion_para_vender(prod["id"], pid_pres)
            linea = {"producto_id": prod["id"], "presentacion_id": pid_pres, "descripcion": prod["nombre"],
                     "presentacion": p["nombre"] if p and pid_pres != pres.PRINCIPAL else None,
                     "iva_tarifa": float(prod["iva_tarifa"] or 0) if prod["iva_tipo"] == "gravado" else 0}
        linea.update(cantidad=cantidad, precio_unitario=unitario, total=round(unitario * cantidad))
        total += linea["total"]
        lineas.append(linea)

    cliente_id = request.form.get("cliente_id", type=int)
    numero = _siguiente_numero(db)
    cur = db.execute(
        "INSERT INTO cotizaciones (numero, fecha, validez_dias, cliente_id, cliente_nombre, cliente_telefono, "
        "cliente_documento, notas, total, estado, usuario_id, usuario_nombre, creado_en) "
        "VALUES (?,?,?,?,?,?,?,?,?, 'abierta', ?, ?, ?)",
        (numero, ahora(), validez, cliente_id,
         (request.form.get("cliente_nombre") or "").strip() or None,
         (request.form.get("cliente_telefono") or "").strip() or None,
         (request.form.get("cliente_documento") or "").strip() or None,
         (request.form.get("notas") or "").strip() or None, total, g.user["id"], g.user["nombre"], ahora()))
    cot_id = cur.lastrowid
    for l in lineas:
        db.execute("INSERT INTO cotizacion_lineas (cotizacion_id, producto_id, presentacion_id, descripcion, "
                   "presentacion, cantidad, precio_unitario, iva_tarifa, total) VALUES (?,?,?,?,?,?,?,?,?)",
                   (cot_id, l["producto_id"], l["presentacion_id"], l["descripcion"], l["presentacion"],
                    l["cantidad"], l["precio_unitario"], l["iva_tarifa"], l["total"]))
    db.commit()
    registrar("cotizacion_creada", "cotizaciones", cot_id, f"{numero} total={total:.0f}")
    return jsonify({"ok": True, "id": cot_id, "numero": numero, "total": total,
                    "url": url_for("cotizaciones.ver", cot_id=cot_id)})


@bp.route("/api/<int:cot_id>")
@login_required
def api_cotizacion(cot_id):
    """Lo que necesita el POS para cargarla en una venta nueva."""
    c = _obtener(cot_id)
    estado = _estado(c)
    return jsonify({
        "ok": True, "id": c["id"], "numero": c["numero"], "estado": estado,
        "vigente": estado == "vigente",
        "cliente": {"nombre": c["cliente_nombre"] or "", "documento": c["cliente_documento"] or ""},
        "lineas": [{"producto_id": l["producto_id"], "presentacion_id": l["presentacion_id"],
                    "descripcion": l["descripcion"], "cantidad": l["cantidad"],
                    "precio": l["precio_unitario"], "iva_tarifa": l["iva_tarifa"]} for l in _lineas(cot_id)],
    })


def marcar_convertida(db, cot_id, venta_id):
    """La llama el cobro del POS (pos.api_cobrar) cuando se vende una cotización."""
    if not cot_id:
        return
    c = db.execute("SELECT id, numero, estado FROM cotizaciones WHERE id = ?", (cot_id,)).fetchone()
    if c and c["estado"] == "abierta":
        db.execute("UPDATE cotizaciones SET estado = 'convertida', venta_id = ?, actualizado_en = ? WHERE id = ?",
                   (venta_id, ahora(), cot_id))
        db.execute("UPDATE ventas SET cotizacion_id = ? WHERE id = ?", (cot_id, venta_id))
