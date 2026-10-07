"""Punto de venta (POS): cajas, ventas, movimientos y cobro."""
import json
from datetime import datetime

from flask import (Blueprint, abort, flash, g, jsonify, redirect,
                   render_template, request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
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

    # Ventas
    ventas_por_pago = db.execute(
        "SELECT forma_pago, COUNT(*) AS n, COALESCE(SUM(total), 0) AS total "
        "FROM ventas WHERE caja_id = ? AND estado = 'completada' "
        "GROUP BY forma_pago",
        (caja["id"],),
    ).fetchall()

    total_ventas_n = sum(p["n"] for p in ventas_por_pago)
    total_ventas = sum(p["total"] for p in ventas_por_pago)

    # Movimientos
    movs = db.execute(
        "SELECT * FROM caja_movimientos WHERE caja_id = ? ORDER BY id DESC",
        (caja["id"],),
    ).fetchall()

    # Totales de movimientos por forma de pago
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

    # Total efectivo esperado en caja
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

    return render_template("pos/index.html", caja=caja, resumen=resumen,
                           categorias=categorias)


@bp.route("/abrir-caja", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico", "auxiliar")
def abrir_caja():
    if _caja_abierta():
        flash("Ya hay una caja abierta. Ciérrala antes de abrir otra.", "error")
        return redirect(url_for("pos.index"))

    if request.method == "POST":
        total, detalle_json = _parsear_denominaciones()
        if total == 0:
            try:
                total = float((request.form.get("efectivo_inicial") or "0").replace(",", "."))
            except ValueError:
                total = 0
        observaciones = request.form.get("observaciones_apertura", "").strip() or None

        db = get_db()
        numero = _siguiente_numero_caja()
        cur = db.execute(
            "INSERT INTO cajas (numero, abierta_en, abierta_por, abierta_por_nombre, "
            "efectivo_inicial, observaciones_apertura, detalle_apertura, estado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'abierta')",
            (numero, ahora(), g.user["id"], g.user["nombre"], total, observaciones,
             detalle_json),
        )
        db.commit()
        registrar("caja_abierta", "cajas", cur.lastrowid,
                  f"numero={numero} efectivo_inicial={total}")
        flash(f"Caja {numero} abierta con ${total:,.0f}. ¡A vender!", "ok")
        return redirect(url_for("pos.index"))

    return render_template("pos/abrir_caja.html", numero_sugerido=_siguiente_numero_caja())


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

    # Leer efectivo contado
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


# Mantener ruta vieja para compatibilidad con el botón del template
@bp.route("/cerrar-caja")
@login_required
def cerrar_caja():
    """Redirige al POS (el cierre ahora es un modal)."""
    return redirect(url_for("pos.index"))