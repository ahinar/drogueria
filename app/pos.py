"""Punto de venta (POS): cajas, ventas, movimientos, gastos y cobro."""
import json
from datetime import date, datetime

from flask import (Blueprint, abort, flash, g, jsonify, redirect,
                   render_template, request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .caja_menor import registrar_movimiento as _cm_mov
from .caja_menor import saldo_actual as _cm_saldo
from .configuracion import obtener_config
from .db import ahora, get_db

bp = Blueprint("pos", __name__, url_prefix="/pos")

# Denominaciones del peso colombiano (2026)
BILLETES_CO = [100000, 50000, 20000, 10000, 5000, 2000]
MONEDAS_CO = [1000, 500, 200, 100, 50]
DENOMINACIONES_CO = BILLETES_CO + MONEDAS_CO

def _parsear_denominaciones():
    """Lee el JSON de denominaciones del formulario y devuelve (total, detalle_str)."""
    try:
        raw = request.form.get("denominaciones", "{}")
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    detalle = {}
    total = 0
    for valor in DENOMINACIONES_CO:
        try:
            cantidad = int(data.get(str(valor), 0) or 0)
        except (ValueError, TypeError):
            cantidad = 0
        if cantidad > 0:
            subtotal = valor * cantidad
            total += subtotal
            detalle[str(valor)] = {"cantidad": cantidad, "subtotal": subtotal}
    return total, json.dumps(detalle, ensure_ascii=False)

def _caja_abierta():
    return get_db().execute(
        "SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1"
    ).fetchone()

def _siguiente_numero_caja():
    db = get_db()
    fila = db.execute(
        "SELECT numero FROM cajas ORDER BY CAST(numero AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return "1001"
    try:
        return str(int(fila["numero"]) + 1)
    except ValueError:
        return "1001"

def _siguiente_consecutivo_venta():
    db = get_db()
    fila = db.execute(
        "SELECT consecutivo FROM ventas ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return "V-0001"
    try:
        n = int(fila["consecutivo"].split("-")[1]) + 1
    except (ValueError, IndexError):
        return "V-0001"
    return f"V-{n:04d}"

def _resumen_caja(caja):
    """Devuelve el resumen completo del turno: ventas, movimientos, totales por forma de pago."""
    db = get_db()

    ventas_por_pago = db.execute(
        "SELECT forma_pago, COUNT(*) AS n, COALESCE(SUM(total), 0) AS total "
        "FROM ventas WHERE caja_id = ? AND estado = 'completada' "
        "GROUP BY forma_pago",
        (caja["id"],),
    ).fetchall()

    total_ventas_n = sum(p["n"] for p in ventas_por_pago)
    total_ventas = sum(p["total"] for p in ventas_por_pago)

    movs = db.execute(
        "SELECT * FROM caja_movimientos WHERE caja_id = ? ORDER BY id DESC",
        (caja["id"],),
    ).fetchall()

    ingresos_efectivo = sum(m["monto"] for m in movs if m["tipo"] == "ingreso" and m["forma_pago"] == "efectivo")
    salidas_efectivo = sum(m["monto"] for m in movs if m["tipo"] == "salida" and m["forma_pago"] == "efectivo")
    ingresos_nequi = sum(m["monto"] for m in movs if m["tipo"] == "ingreso" and m["forma_pago"] == "nequi")
    salidas_nequi = sum(m["monto"] for m in movs if m["tipo"] == "salida" and m["forma_pago"] == "nequi")
    ingresos_davivienda = sum(m["monto"] for m in movs if m["tipo"] == "ingreso" and m["forma_pago"] == "davivienda")
    salidas_davivienda = sum(m["monto"] for m in movs if m["tipo"] == "salida" and m["forma_pago"] == "davivienda")

    def _por_pago(nombre):
        return next((p for p in ventas_por_pago if p["forma_pago"] == nombre), None)

    v_efectivo = _por_pago("efectivo")
    v_nequi = _por_pago("nequi")
    v_davivienda = _por_pago("davivienda")
    v_tarjeta = _por_pago("tarjeta")

    efectivo_esperado = (caja["efectivo_inicial"] or 0) + \
                        (v_efectivo["total"] if v_efectivo else 0) + \
                        ingresos_efectivo - salidas_efectivo

    return {
        "n_ventas": total_ventas_n,
        "total_ventas": total_ventas,
        "por_pago": ventas_por_pago,
        "movimientos": movs,
        "efectivo_inicial": caja["efectivo_inicial"] or 0,
        "ventas_efectivo": v_efectivo["total"] if v_efectivo else 0,
        "ventas_nequi": v_nequi["total"] if v_nequi else 0,
        "ventas_davivienda": v_davivienda["total"] if v_davivienda else 0,
        "ventas_tarjeta": v_tarjeta["total"] if v_tarjeta else 0,
        "ingresos_efectivo": ingresos_efectivo,
        "salidas_efectivo": salidas_efectivo,
        "ingresos_nequi": ingresos_nequi,
        "salidas_nequi": salidas_nequi,
        "ingresos_davivienda": ingresos_davivienda,
        "salidas_davivienda": salidas_davivienda,
        "efectivo_esperado": efectivo_esperado,
    }

# ============================================================
# Rutas
# ============================================================

@bp.route("/")
@login_required
def index():
    caja = _caja_abierta()
    if caja is None:
        return redirect(url_for("pos.abrir_caja"))

    db = get_db()
    resumen = db.execute(
        "SELECT COUNT(*) AS n_ventas, COALESCE(SUM(total), 0) AS total "
        "FROM ventas WHERE caja_id = ? AND estado = 'completada'",
        (caja["id"],),
    ).fetchone()

    categorias = db.execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'categoria' AND activo = 1 "
        "ORDER BY nombre COLLATE NOCASE"
    ).fetchall()

    categorias_gasto = db.execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'categoria_gasto' AND activo = 1 "
        "ORDER BY nombre COLLATE NOCASE"
    ).fetchall()

    return render_template("pos/index.html", caja=caja, resumen=resumen,
                           categorias=categorias,
                           categorias_gasto=categorias_gasto,
                           saldo_caja_menor=_cm_saldo(db))

@bp.route("/abrir-caja", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico", "auxiliar")
def abrir_caja():
    if _caja_abierta():
        flash("Ya hay una caja abierta. Ciérrala antes de abrir otra.", "error")
        return redirect(url_for("pos.index"))

    db = get_db()
    saldo_cm = _cm_saldo(db)

    if request.method == "POST":
        total, detalle_json = _parsear_denominaciones()
        if total == 0:
            try:
                total = float((request.form.get("efectivo_inicial") or "0").replace(",", "."))
            except ValueError:
                total = 0
        observaciones = request.form.get("observaciones_apertura", "").strip() or None
        confirmar_sobregiro = request.form.get("confirmar_sobregiro") == "1"

        # Aviso si el efectivo inicial supera el saldo de la caja menor
        if total > saldo_cm + 0.01 and not confirmar_sobregiro:
            flash(
                f"El efectivo inicial (${total:,.0f}) supera el saldo de la caja menor "
                f"(${saldo_cm:,.0f}). Marca la casilla 'Permitir sobregiro' para continuar.",
                "error"
            )
            return render_template(
                "pos/abrir_caja.html",
                numero_sugerido=_siguiente_numero_caja(),
                saldo_caja_menor=saldo_cm,
            )

        numero = _siguiente_numero_caja()
        cur = db.execute(
            "INSERT INTO cajas (numero, abierta_en, abierta_por, abierta_por_nombre, "
            "efectivo_inicial, observaciones_apertura, detalle_apertura, estado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'abierta')",
            (numero, ahora(), g.user["id"], g.user["nombre"], total, observaciones,
             detalle_json),
        )
        caja_id = cur.lastrowid

        # Registrar movimiento en caja menor (apertura_pos)
        if total > 0:
            mov_id = _cm_mov(db, "apertura_pos", total,
                             motivo=f"Apertura caja POS #{numero}", caja_id=caja_id)
            db.execute("UPDATE cajas SET caja_menor_apertura_id = ? WHERE id = ?",
                       (mov_id, caja_id))

        db.commit()
        registrar("caja_abierta", "cajas", caja_id,
                  f"numero={numero} efectivo_inicial={total} saldo_cm_antes={saldo_cm}")
        flash(f"Caja {numero} abierta con ${total:,.0f}. ¡A vender!", "ok")
        return redirect(url_for("pos.index"))

    return render_template(
        "pos/abrir_caja.html",
        numero_sugerido=_siguiente_numero_caja(),
        saldo_caja_menor=saldo_cm,
    )

# ============================================================
# API · Movimientos de caja (ingresos / salidas)
# ============================================================

@bp.route("/api/movimiento", methods=["POST"])
@login_required
def api_movimiento():
    caja = _caja_abierta()
    if caja is None:
        return jsonify({"ok": False, "error": "No hay caja abierta."}), 400

    tipo = request.form.get("tipo", "").strip().lower()
    forma_pago = request.form.get("forma_pago", "efectivo").strip().lower()
    motivo = request.form.get("motivo", "").strip() or None

    if tipo not in ("ingreso", "salida"):
        return jsonify({"ok": False, "error": "Tipo inválido."}), 400
    if forma_pago not in ("efectivo", "nequi", "davivienda", "tarjeta"):
        return jsonify({"ok": False, "error": "Forma de pago inválida."}), 400

    try:
        monto = float((request.form.get("monto") or "0").replace(",", "."))
    except ValueError:
        return jsonify({"ok": False, "error": "Monto inválido."}), 400

    if monto <= 0:
        return jsonify({"ok": False, "error": "El monto debe ser mayor a cero."}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, "
        "usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
        (caja["id"], ahora(), tipo, forma_pago, monto, motivo,
         g.user["id"], g.user["nombre"], ahora()),
    )
    db.commit()
    registrar(f"caja_{tipo}", "caja_movimientos", cur.lastrowid,
              f"monto={monto} forma_pago={forma_pago} motivo={motivo}")

    return jsonify({"ok": True, "id": cur.lastrowid})

# ============================================================
# API · Gasto desde el POS
# ============================================================

@bp.route("/api/gasto", methods=["POST"])
@login_required
def api_gasto():
    """Registra un gasto desde el POS. Puede afectar la caja POS o la caja menor.

    Reglas:
    - Si origen = 'pos' y forma_pago = 'efectivo': se genera una salida de caja
      (afecta el cierre del día).
    - Si origen = 'caja_menor': se genera un movimiento en la caja menor.
    - Si forma_pago es distinta de efectivo, no afecta el efectivo físico.
    """
    categoria_id = (request.form.get("categoria_id") or "").strip()
    descripcion = (request.form.get("descripcion") or "").strip()
    monto_txt = (request.form.get("monto") or "0").strip().replace(",", ".")
    forma_pago = (request.form.get("forma_pago") or "efectivo").strip().lower()
    origen = (request.form.get("origen") or "pos").strip().lower()
    comprobante = (request.form.get("comprobante") or "").strip() or None

    if not categoria_id.isdigit():
        return jsonify({"ok": False, "error": "Selecciona una categoría."}), 400
    if not descripcion:
        return jsonify({"ok": False, "error": "Escribe una descripción."}), 400
    try:
        monto = float(monto_txt)
    except ValueError:
        return jsonify({"ok": False, "error": "Monto inválido."}), 400
    if monto <= 0:
        return jsonify({"ok": False, "error": "El monto debe ser mayor a cero."}), 400
    if forma_pago not in ("efectivo", "nequi", "davivienda", "tarjeta", "transferencia"):
        return jsonify({"ok": False, "error": "Forma de pago inválida."}), 400
    if origen not in ("pos", "caja_menor", "ninguna"):
        return jsonify({"ok": False, "error": "Origen inválido."}), 400

    db = get_db()
    caja = _caja_abierta()
    if origen == "pos" and caja is None:
        return jsonify({"ok": False, "error": "No hay caja POS abierta."}), 400

    caja_id_ref = caja["id"] if caja else None
    if origen == "ninguna":
        caja_id_ref = None

    cur = db.execute(
        "INSERT INTO gastos (fecha, categoria_id, descripcion, monto, forma_pago, "
        "comprobante, origen, caja_id, usuario_id, usuario_nombre, activo, creado_en) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
        (ahora(), int(categoria_id), descripcion, monto, forma_pago,
         comprobante, origen, caja_id_ref, g.user["id"], g.user["nombre"], ahora()),
    )
    gasto_id = cur.lastrowid

    # Salida de efectivo desde la caja POS
    if origen == "pos" and forma_pago == "efectivo":
        db.execute(
            "INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, "
            "usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
            (caja["id"], ahora(), "salida", "efectivo", monto,
             f"Gasto: {descripcion}", g.user["id"], g.user["nombre"], ahora()),
        )
    # Salida de la caja menor
    elif origen == "caja_menor":
        _cm_mov(db, "gasto", monto, motivo=descripcion,
                caja_id=caja_id_ref, gasto_id=gasto_id)

    db.commit()
    registrar("gasto_desde_pos", "gastos", gasto_id,
              f"monto={monto} origen={origen} forma_pago={forma_pago}")

    return jsonify({"ok": True, "gasto_id": gasto_id})

# ============================================================
# API · Cierre de caja
# ============================================================

@bp.route("/api/resumen-caja")
@login_required
def api_resumen_caja():
    caja = _caja_abierta()
    if caja is None:
        return jsonify({"ok": False, "error": "No hay caja abierta."}), 400

    resumen = _resumen_caja(caja)
    return jsonify({
        "ok": True,
        "caja": {
            "id": caja["id"],
            "numero": caja["numero"],
            "abierta_en": caja["abierta_en"],
            "efectivo_inicial": caja["efectivo_inicial"] or 0,
        },
        "resumen": {
            "n_ventas": resumen["n_ventas"],
            "total_ventas": resumen["total_ventas"],
            "efectivo": {
                "inicial": resumen["efectivo_inicial"],
                "ventas": resumen["ventas_efectivo"],
                "ingresos": resumen["ingresos_efectivo"],
                "salidas": resumen["salidas_efectivo"],
                "esperado": resumen["efectivo_esperado"],
            },
            "nequi": {
                "ventas": resumen["ventas_nequi"],
                "ingresos": resumen["ingresos_nequi"],
                "salidas": resumen["salidas_nequi"],
            },
            "davivienda": {
                "ventas": resumen["ventas_davivienda"],
                "ingresos": resumen["ingresos_davivienda"],
                "salidas": resumen["salidas_davivienda"],
            },
            "tarjeta": {
                "ventas": resumen["ventas_tarjeta"],
            },
        },
    })

@bp.route("/api/cerrar-caja", methods=["POST"])
@login_required
def api_cerrar_caja():
    caja = _caja_abierta()
    if caja is None:
        return jsonify({"ok": False, "error": "No hay caja abierta."}), 400

    resumen = _resumen_caja(caja)

    total, detalle_json = _parsear_denominaciones()
    if total == 0:
        try:
            total = float((request.form.get("efectivo_contado") or "0").replace(",", "."))
        except ValueError:
            total = 0

    observaciones = request.form.get("observaciones_cierre", "").strip() or None
    diferencia = total - resumen["efectivo_esperado"]

    db = get_db()
    db.execute(
        "UPDATE cajas SET cerrada_en = ?, cerrada_por = ?, cerrada_por_nombre = ?, "
        "efectivo_contado = ?, diferencia = ?, observaciones_cierre = ?, "
        "detalle_cierre = ?, estado = 'cerrada' WHERE id = ?",
        (ahora(), g.user["id"], g.user["nombre"], total, diferencia,
         observaciones, detalle_json, caja["id"]),
    )

    # Devolver el efectivo contado a la caja menor
    if total > 0:
        mov_id = _cm_mov(db, "cierre_pos", total,
                         motivo=f"Cierre caja POS #{caja['numero']}",
                         caja_id=caja["id"])
        db.execute("UPDATE cajas SET caja_menor_cierre_id = ? WHERE id = ?",
                   (mov_id, caja["id"]))

    db.commit()
    registrar("caja_cerrada", "cajas", caja["id"],
              f"numero={caja['numero']} contado={total} esperado={resumen['efectivo_esperado']} "
              f"diferencia={diferencia}")

    return jsonify({"ok": True, "caja_id": caja["id"], "diferencia": diferencia})

@bp.route("/cierre/<int:caja_id>")
@login_required
def cierre_confirmacion(caja_id):
    caja = get_db().execute("SELECT * FROM cajas WHERE id = ?", (caja_id,)).fetchone()
    if caja is None:
        abort(404)
    return render_template("pos/cierre_confirmacion.html", caja=caja)

@bp.route("/api/caja-abierta")
@login_required
def api_caja_abierta():
    caja = _caja_abierta()
    if caja is None:
        return jsonify({"ok": True, "caja": None})
    return jsonify({"ok": True, "caja": {
        "id": caja["id"],
        "numero": caja["numero"],
        "abierta_en": caja["abierta_en"],
        "efectivo_inicial": caja["efectivo_inicial"],
    }})

# ============================================================
# VENTAS (carrito): buscar productos, cobrar, comprobante, anular
# ============================================================

FORMAS_PAGO = ("efectivo", "nequi", "davivienda", "tarjeta")

class _VentaError(Exception):
    """Error de negocio al cobrar (ej: 'no hay stock'). El mensaje se le muestra al cajero."""

def _a_pesos(valor):
    """Redondea al peso entero más cercano (0.5 sube)."""
    return int(valor + 0.5) if valor >= 0 else -int(-valor + 0.5)

def _fmt_cant(n):
    """Muestra 3.0 como '3' y 2.5 como '2.5'."""
    return str(int(n)) if float(n).is_integer() else str(round(n, 2))

def _json_error(mensaje, codigo=400):
    return jsonify({"ok": False, "error": mensaje}), codigo

SQL_LOTE_VENDIBLE = (
    "l.estado = 'disponible' AND l.cantidad_disponible > 0 "
    "AND (l.vencimiento IS NULL OR l.vencimiento = '' OR l.vencimiento >= ?)"
)

@bp.route("/api/productos")
@login_required
def api_productos():
    """Busca productos para el POS. Devuelve hasta 40, con su stock vendible."""
    q = (request.args.get("q") or "").strip()
    cat = (request.args.get("cat") or "").strip()
    hoy = date.today().isoformat()

    sql = (
        "SELECT p.id, p.codigo, p.codigo_barras, p.nombre, p.concentracion, "
        "p.precio_venta, p.iva_tipo, p.iva_tarifa, p.requiere_formula, "
        "p.control_especial, p.imagen, "
        "COALESCE((SELECT SUM(l.cantidad_disponible) FROM lotes l "
        f"          WHERE l.producto_id = p.id AND {SQL_LOTE_VENDIBLE}), 0) AS stock "
        "FROM productos p WHERE p.activo = 1"
    )
    params = [hoy]

    for palabra in q.split():
        sql += (" AND (p.nombre LIKE ? OR p.codigo LIKE ? OR p.codigo_barras LIKE ? "
                "OR p.principio_activo LIKE ?)")
        params += [f"%{palabra}%"] * 4

    if cat.isdigit():
        sql += " AND p.id IN (SELECT producto_id FROM productos_categorias WHERE catalogo_id = ?)"
        params.append(int(cat))

    sql += " ORDER BY (stock > 0) DESC, p.nombre COLLATE NOCASE LIMIT 40"
    filas = get_db().execute(sql, params).fetchall()

    productos = [{
        "id": f["id"], "codigo": f["codigo"], "codigo_barras": f["codigo_barras"],
        "nombre": f["nombre"], "concentracion": f["concentracion"],
        "precio": f["precio_venta"], "iva_tipo": f["iva_tipo"], "iva_tarifa": f["iva_tarifa"],
        "requiere_formula": bool(f["requiere_formula"]),
        "control_especial": bool(f["control_especial"]),
        "imagen": f["imagen"], "stock": f["stock"],
    } for f in filas]

    exacto = bool(q) and len(productos) == 1 and productos[0]["codigo_barras"] == q
    return jsonify({"ok": True, "productos": productos, "exacto": exacto})

@bp.route("/api/cobrar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico", "auxiliar")
def api_cobrar():
    """Registra una venta completa. O se guarda TODO, o no se guarda NADA."""
    caja = _caja_abierta()
    if caja is None:
        return _json_error("No hay caja abierta.")

    try:
        carrito = json.loads(request.form.get("carrito", "[]"))
    except (json.JSONDecodeError, TypeError):
        return _json_error("El carrito llegó dañado. Intenta de nuevo.")
    if not isinstance(carrito, list) or not carrito:
        return _json_error("El carrito está vacío.")

    forma_pago = (request.form.get("forma_pago") or "").strip().lower()
    if forma_pago not in FORMAS_PAGO:
        return _json_error("Forma de pago inválida.")

    cliente_nombre = (request.form.get("cliente_nombre") or "").strip() or "Consumidor final"
    cliente_doc = (request.form.get("cliente_documento") or "").strip() or None
    observaciones = (request.form.get("observaciones") or "").strip() or None

    db = get_db()
    hoy = date.today().isoformat()

    db.execute("BEGIN IMMEDIATE")
    try:
        consecutivo = _siguiente_consecutivo_venta()
        cur = db.execute(
            "INSERT INTO ventas (consecutivo, fecha, caja_id, cliente_nombre, cliente_documento, "
            "subtotal, descuento, iva, total, forma_pago, observaciones, usuario_id, "
            "usuario_nombre, estado, creado_en) "
            "VALUES (?,?,?,?,?,0,0,0,0,?,?,?,?,'completada',?)",
            (consecutivo, ahora(), caja["id"], cliente_nombre, cliente_doc, forma_pago,
             observaciones, g.user["id"], g.user["nombre"], ahora()),
        )
        venta_id = cur.lastrowid

        sum_subtotal = sum_descuento = sum_iva = sum_total = 0

        for item in carrito:
            try:
                producto_id = int(item.get("producto_id"))
                cantidad = round(float(item.get("cantidad")), 4)
                desc_pct = float(item.get("descuento_pct") or 0)
            except (TypeError, ValueError, AttributeError):
                raise _VentaError("Hay una línea del carrito con datos inválidos.")
            if cantidad <= 0:
                raise _VentaError("La cantidad de cada producto debe ser mayor a cero.")
            if not 0 <= desc_pct <= 100:
                raise _VentaError("El descuento debe estar entre 0 y 100 %.")

            prod = db.execute(
                "SELECT * FROM productos WHERE id = ? AND activo = 1", (producto_id,)
            ).fetchone()
            if prod is None:
                raise _VentaError("Uno de los productos ya no existe o está inactivo.")
            nombre = prod["nombre"]
            if prod["control_especial"]:
                raise _VentaError(f"{nombre}: es de control especial y todavía no se puede "
                                  "vender desde el POS (falta el libro de control).")
            precio = float(prod["precio_venta"] or 0)
            if precio <= 0:
                raise _VentaError(f"{nombre}: no tiene precio de venta.")

            lotes = db.execute(
                "SELECT l.id, l.lote, l.vencimiento, l.cantidad_disponible FROM lotes l "
                f"WHERE l.producto_id = ? AND {SQL_LOTE_VENDIBLE} "
                "ORDER BY (l.vencimiento IS NULL OR l.vencimiento = ''), l.vencimiento, l.id",
                (producto_id, hoy),
            ).fetchall()
            disponible = sum(l["cantidad_disponible"] for l in lotes)
            if cantidad > disponible + 1e-9:
                raise _VentaError(f"{nombre}: solo hay {_fmt_cant(disponible)} disponible(s) "
                                  f"y pediste {_fmt_cant(cantidad)}.")

            pendiente = cantidad
            asignaciones = []
            for l in lotes:
                if pendiente <= 1e-9:
                    break
                toma = round(min(pendiente, l["cantidad_disponible"]), 4)
                asignaciones.append({"lote_id": l["id"], "lote": l["lote"],
                                     "vencimiento": l["vencimiento"], "cantidad": toma})
                pendiente -= toma

            bruto = cantidad * precio
            descuento = _a_pesos(bruto * desc_pct / 100)
            total_linea = _a_pesos(bruto) - descuento
            tarifa = float(prod["iva_tarifa"] or 0)
            if prod["iva_tipo"] == "gravado" and tarifa > 0:
                base = _a_pesos(total_linea / (1 + tarifa / 100))
                iva_valor = total_linea - base
            else:
                base, iva_valor = total_linea, 0

            db.execute(
                "INSERT INTO venta_lineas (venta_id, producto_id, producto_codigo, producto_nombre, "
                "presentacion, factor, cantidad, precio_unitario, descuento_linea, iva_tipo, "
                "iva_tarifa, subtotal, iva_valor, total, lotes_json) "
                "VALUES (?,?,?,?,'Unidad',1,?,?,?,?,?,?,?,?,?)",
                (venta_id, producto_id, prod["codigo"], nombre, cantidad, precio, descuento,
                 prod["iva_tipo"], tarifa, base, iva_valor, total_linea,
                 json.dumps(asignaciones, ensure_ascii=False)),
            )

            for a in asignaciones:
                db.execute(
                    "UPDATE lotes SET cantidad_disponible = cantidad_disponible - ?, "
                    "actualizado_en = ? WHERE id = ?",
                    (a["cantidad"], ahora(), a["lote_id"]),
                )
                db.execute(
                    "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, "
                    "cantidad, referencia, referencia_id, usuario_id, usuario_nombre, creado_en) "
                    "VALUES (?,?,?, 'venta', ?, ?, ?, ?, ?, ?)",
                    (ahora(), a["lote_id"], producto_id, -a["cantidad"], f"Venta {consecutivo}",
                     venta_id, g.user["id"], g.user["nombre"], ahora()),
                )

            sum_subtotal += base
            sum_descuento += descuento
            sum_iva += iva_valor
            sum_total += total_linea

        if forma_pago == "efectivo":
            recibido_txt = (request.form.get("monto_recibido") or "").strip()
            try:
                recibido = float(recibido_txt.replace(",", ".")) if recibido_txt else float(sum_total)
            except ValueError:
                raise _VentaError("El monto recibido no es válido.")
            if recibido + 1e-9 < sum_total:
                raise _VentaError(f"El efectivo recibido (${recibido:,.0f}) no alcanza para "
                                  f"el total (${sum_total:,.0f}).")
            cambio = recibido - sum_total
        else:
            recibido, cambio = float(sum_total), 0.0

        db.execute(
            "UPDATE ventas SET subtotal = ?, descuento = ?, iva = ?, total = ?, "
            "monto_recibido = ?, cambio = ? WHERE id = ?",
            (sum_subtotal, sum_descuento, sum_iva, sum_total, recibido, cambio, venta_id),
        )
        db.commit()
    except _VentaError as e:
        db.rollback()
        return _json_error(str(e))
    except Exception:
        db.rollback()
        raise

    registrar("venta_creada", "ventas", venta_id,
              f"consecutivo={consecutivo} total={sum_total} forma_pago={forma_pago}")
    return jsonify({"ok": True, "venta_id": venta_id, "consecutivo": consecutivo,
                    "total": sum_total, "cambio": cambio,
                    "url_comprobante": url_for("pos.comprobante", venta_id=venta_id)})

def _venta_o_404(venta_id):
    venta = get_db().execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    if venta is None:
        abort(404)
    return venta

@bp.route("/venta/<int:venta_id>")
@login_required
def comprobante(venta_id):
    """Comprobante de venta (interno, sin valor tributario), listo para imprimir."""
    venta = _venta_o_404(venta_id)
    lineas = get_db().execute(
        "SELECT * FROM venta_lineas WHERE venta_id = ? ORDER BY id", (venta_id,)
    ).fetchall()
    return render_template("pos/comprobante.html", venta=venta, lineas=lineas,
                           config=obtener_config())

@bp.route("/venta/ultima")
@login_required
def ultima_venta():
    """Atajo para 'Reimprimir último'."""
    fila = get_db().execute("SELECT id FROM ventas ORDER BY id DESC LIMIT 1").fetchone()
    if fila is None:
        flash("Todavía no hay ventas.", "error")
        return redirect(url_for("pos.index"))
    return redirect(url_for("pos.comprobante", venta_id=fila["id"]))

@bp.route("/ventas")
@login_required
def ventas_lista():
    db = get_db()
    caja = _caja_abierta() or db.execute(
        "SELECT * FROM cajas ORDER BY id DESC LIMIT 1").fetchone()
    ventas = []
    if caja is not None:
        ventas = db.execute(
            "SELECT * FROM ventas WHERE caja_id = ? ORDER BY id DESC", (caja["id"],)
        ).fetchall()
    return render_template("pos/ventas.html", ventas=ventas, caja=caja)

@bp.route("/venta/<int:venta_id>/anular", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def anular_venta(venta_id):
    """Anula una venta: devuelve las unidades a los MISMOS lotes de donde salieron."""
    venta = _venta_o_404(venta_id)
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("Debes escribir el motivo de la anulación.", "error")
        return redirect(url_for("pos.ventas_lista"))

    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        venta = db.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
        caja = db.execute("SELECT estado FROM cajas WHERE id = ?", (venta["caja_id"],)).fetchone()
        if venta["estado"] != "completada":
            raise _VentaError("Esa venta ya está anulada.")
        if caja["estado"] != "abierta":
            raise _VentaError("Esa venta pertenece a una caja ya cerrada; no se puede anular.")

        lineas = db.execute("SELECT * FROM venta_lineas WHERE venta_id = ?", (venta_id,)).fetchall()
        for linea in lineas:
            for a in json.loads(linea["lotes_json"] or "[]"):
                db.execute(
                    "UPDATE lotes SET cantidad_disponible = cantidad_disponible + ?, "
                    "actualizado_en = ? WHERE id = ?",
                    (a["cantidad"], ahora(), a["lote_id"]),
                )
                db.execute(
                    "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, "
                    "cantidad, referencia, referencia_id, usuario_id, usuario_nombre, "
                    "observaciones, creado_en) VALUES (?,?,?, 'devolucion', ?, ?, ?, ?, ?, ?, ?)",
                    (ahora(), a["lote_id"], linea["producto_id"], a["cantidad"],
                     f"Anulación {venta['consecutivo']}", venta_id, g.user["id"],
                     g.user["nombre"], motivo, ahora()),
                )
        db.execute(
            "UPDATE ventas SET estado = 'anulada', motivo_anulacion = ?, anulada_en = ?, "
            "anulada_por = ?, anulada_por_nombre = ? WHERE id = ?",
            (motivo, ahora(), g.user["id"], g.user["nombre"], venta_id),
        )
        db.commit()
    except _VentaError as e:
        db.rollback()
        flash(str(e), "error")
        return redirect(url_for("pos.ventas_lista"))
    except Exception:
        db.rollback()
        raise

    registrar("venta_anulada", "ventas", venta_id,
              f"consecutivo={venta['consecutivo']} motivo={motivo}")
    flash(f"Venta {venta['consecutivo']} anulada. El inventario fue devuelto.", "ok")
    return redirect(url_for("pos.ventas_lista"))

@bp.route("/cerrar-caja")
@login_required
def cerrar_caja():
    """Redirige al POS (el cierre ahora es un modal)."""
    return redirect(url_for("pos.index"))
