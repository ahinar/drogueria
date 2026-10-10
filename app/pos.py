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
from .formato import pesos
from .db import ahora, get_db
from . import presentaciones as pres
from .productos import IVA_TIPOS
from .utils_imagenes import eliminar_imagen, guardar_imagen

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
        "ventas_credito": _por_pago("credito")["total"] if _por_pago("credito") else 0,
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

    # Categorías de "otro ingreso" (recargas, arriendo...), para la ventana del POS
    categorias_ingreso = [dict(f) for f in db.execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'categoria_ingreso' AND activo = 1 "
        "ORDER BY nombre COLLATE NOCASE")]

    return render_template("pos/index.html", caja=caja, resumen=resumen,
                           categorias=categorias,
                           categorias_gasto=categorias_gasto,
                           categorias_ingreso=categorias_ingreso,
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
                f"El efectivo inicial ({pesos(total)}) supera el saldo de la caja menor "
                f"({pesos(saldo_cm)}). Marca la casilla 'Permitir sobregiro' para continuar.",
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
        flash(f"Caja {numero} abierta con {pesos(total)}. ¡A vender!", "ok")
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
# API · Otro ingreso (plata que entra y NO es una venta)
# ============================================================

FORMAS_INGRESO = ("efectivo", "nequi", "davivienda", "tarjeta", "transferencia")


@bp.route("/api/otro-ingreso", methods=["POST"])
@login_required
def api_otro_ingreso():
    """Registra un OTRO INGRESO desde el POS (comisión de recargas, arriendo...).

    Es el "espejo" del gasto:
    - Queda en la tabla otros_ingresos (sale en Contabilidad, en Utilidades
      y en el reporte de Ventas).
    - Si es en EFECTIVO, además entra a la caja abierta como un ingreso
      (caja_movimientos), para que el cierre de caja cuadre.
    """
    caja = _caja_abierta()
    if caja is None:
        return jsonify({"ok": False, "error": "No hay caja POS abierta."}), 400
    categoria_id = (request.form.get("categoria_id") or "").strip()
    descripcion = " ".join((request.form.get("descripcion") or "").split())[:200]
    forma_pago = (request.form.get("forma_pago") or "efectivo").strip().lower()
    try:
        monto = float((request.form.get("monto") or "0").replace(",", "."))
    except ValueError:
        return jsonify({"ok": False, "error": "Monto inválido."}), 400

    db = get_db()
    if not categoria_id.isdigit() or db.execute(
            "SELECT 1 FROM catalogos WHERE id = ? AND tipo = 'categoria_ingreso'",
            (int(categoria_id),)).fetchone() is None:
        return jsonify({"ok": False, "error": "Escoge una categoría."}), 400
    if len(descripcion) < 3:
        return jsonify({"ok": False, "error": "Escribe de qué es el ingreso."}), 400
    if monto <= 0:
        return jsonify({"ok": False, "error": "El monto debe ser mayor a cero."}), 400
    if forma_pago not in FORMAS_INGRESO:
        return jsonify({"ok": False, "error": "Forma de pago inválida."}), 400

    ingreso_id = db.execute(
        "INSERT INTO otros_ingresos (fecha, categoria_id, descripcion, monto, forma_pago, origen, "
        "caja_id, usuario_id, usuario_nombre, activo, creado_en) VALUES (?,?,?,?,?, 'pos', ?,?,?,1,?)",
        (ahora(), int(categoria_id), descripcion, monto, forma_pago, caja["id"],
         g.user["id"], g.user["nombre"], ahora()),
    ).lastrowid
    if forma_pago == "efectivo":
        db.execute(
            "INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, "
            "usuario_id, usuario_nombre, creado_en) VALUES (?,?, 'ingreso', 'efectivo', ?,?,?,?,?)",
            (caja["id"], ahora(), monto, f"Otro ingreso: {descripcion}",
             g.user["id"], g.user["nombre"], ahora()),
        )
    db.commit()
    registrar("otro_ingreso_desde_pos", "otros_ingresos", ingreso_id,
              f"monto={monto} forma_pago={forma_pago} · {descripcion}")
    return jsonify({"ok": True, "ingreso_id": ingreso_id})

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
            # Ventas a crédito: no entró plata (quedaron en Cartera). Solo informativo.
            "credito": {
                "ventas": resumen["ventas_credito"],
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

# "credito" = el cliente queda debiendo (ver app/cartera.py). No entra plata a la caja.
FORMAS_PAGO = ("efectivo", "nequi", "davivienda", "tarjeta", "credito")

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

def _usos_de(ids):
    """{producto_id: ['Fiebre', 'Gripa', ...]} para una lista de productos."""
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    resultado = {}
    for fila in get_db().execute(
            "SELECT pu.producto_id, c.nombre FROM productos_usos pu "
            f"JOIN catalogos c ON c.id = pu.catalogo_id WHERE pu.producto_id IN ({marcas}) "
            "ORDER BY c.nombre COLLATE NOCASE", ids):
        resultado.setdefault(fila["producto_id"], []).append(fila["nombre"])
    return resultado


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
        "p.control_especial, p.imagen, p.venta_defecto_unidad_id, "
        "COALESCE((SELECT SUM(l.cantidad_disponible) FROM lotes l "
        f"          WHERE l.producto_id = p.id AND {SQL_LOTE_VENDIBLE}), 0) AS stock "
        "FROM productos p WHERE p.activo = 1"
    )
    params = [hoy]

    # Cada palabra escrita debe aparecer en ALGUNO de estos lugares:
    #   nombre, código, código de barras, principio activo (texto o catálogo)
    #   o en los USOS del producto (nombre del uso o su descripción).
    # Así funciona el "buscador por síntoma": si el producto tiene el uso
    # "Gripa" con descripción "resfriado, congestión", escribir "resfriado"
    # lo encuentra.
    #   (también el código de barras de sus presentaciones: sobre, caja...)
    for palabra in q.split():
        sql += (" AND (p.nombre LIKE ? OR p.codigo LIKE ? OR p.codigo_barras LIKE ? "
                "OR p.principio_activo LIKE ? "
                "OR EXISTS (SELECT 1 FROM producto_presentaciones pp WHERE pp.producto_id = p.id "
                "           AND pp.codigo_barras = ?) "
                "OR EXISTS (SELECT 1 FROM catalogos pa WHERE pa.id = p.principio_id "
                "           AND pa.nombre LIKE ?) "
                "OR EXISTS (SELECT 1 FROM productos_usos pu "
                "           JOIN catalogos u ON u.id = pu.catalogo_id "
                "           WHERE pu.producto_id = p.id "
                "           AND (u.nombre LIKE ? OR u.descripcion LIKE ?)))")
        params += [f"%{palabra}%"] * 4 + [palabra] + [f"%{palabra}%"] * 3

    if cat.isdigit():
        sql += " AND p.id IN (SELECT producto_id FROM productos_categorias WHERE catalogo_id = ?)"
        params.append(int(cat))

    sql += " ORDER BY (stock > 0) DESC, p.nombre COLLATE NOCASE LIMIT 40"
    filas = get_db().execute(sql, params).fetchall()

    usos = _usos_de([f["id"] for f in filas])
    # Formas de vender cada producto: [unidad principal, sobre, caja...]
    presentaciones = pres.presentaciones_de([f["id"] for f in filas])
    productos = [{
        "id": f["id"], "codigo": f["codigo"], "codigo_barras": f["codigo_barras"],
        "nombre": f["nombre"], "concentracion": f["concentracion"],
        "precio": f["precio_venta"], "iva_tipo": f["iva_tipo"], "iva_tarifa": f["iva_tarifa"],
        "requiere_formula": bool(f["requiere_formula"]),
        "control_especial": bool(f["control_especial"]),
        "imagen": f["imagen"], "stock": f["stock"],
        "usos": usos.get(f["id"], []),     # para mostrar "Sirve para: ..." en la tarjeta
        "presentaciones": presentaciones.get(f["id"], []),
        # La que agrega el POS al tocar la tarjeta (0 = unidad de inventario)
        "presentacion_defecto": pres.id_por_defecto(presentaciones.get(f["id"], []),
                                                    f["venta_defecto_unidad_id"]),
    } for f in filas]

    # ¿Se escaneó un código de barras exacto? Puede ser el del producto o el de
    # una de sus presentaciones (ej: el código de la CAJA). En ese caso el POS
    # agrega directamente esa presentación, sin preguntar.
    exacto, presentacion_id = False, None
    if q and len(productos) == 1:
        for opcion in productos[0]["presentaciones"]:
            if opcion["codigo_barras"] == q:
                exacto, presentacion_id = True, opcion["id"]
                break
    return jsonify({"ok": True, "productos": productos, "exacto": exacto,
                    "presentacion_id": presentacion_id})

@bp.route("/api/producto/<int:producto_id>")
@login_required
def api_producto_info(producto_id):
    """Datos de un producto para la ventana "i" del POS. Solo LEE, no modifica nada.

    Devuelve en un solo paquete (JSON):
      - datos básicos y precios del producto
      - lotes que se pueden vender hoy (el que vence primero va primero)
      - cuántos lotes hay en otros estados (cuarentena, bloqueados, vencidos)
      - costo promedio y margen
      - las últimas 4 compras (recepciones aprobadas)
    """
    db = get_db()
    hoy = date.today().isoformat()

    p = db.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if p is None:
        return _json_error("El producto no existe.", 404)

    # ---- Lotes que se pueden vender hoy ----
    lotes = db.execute(
        "SELECT l.lote, l.vencimiento, l.cantidad_disponible, l.costo_unitario FROM lotes l "
        f"WHERE l.producto_id = ? AND {SQL_LOTE_VENDIBLE} "
        "ORDER BY (l.vencimiento IS NULL OR l.vencimiento = ''), l.vencimiento, l.id",
        (producto_id, hoy),
    ).fetchall()
    stock = sum(l["cantidad_disponible"] for l in lotes)

    # ---- Lotes con mercancía que NO se pueden vender (para avisar) ----
    otros = db.execute(
        "SELECT "
        " SUM(CASE WHEN estado = 'cuarentena' THEN 1 ELSE 0 END) AS cuarentena, "
        " SUM(CASE WHEN estado = 'bloqueado' THEN 1 ELSE 0 END) AS bloqueados, "
        " SUM(CASE WHEN estado = 'disponible' AND vencimiento IS NOT NULL AND vencimiento <> '' "
        "          AND vencimiento < ? THEN 1 ELSE 0 END) AS vencidos "
        "FROM lotes WHERE producto_id = ? AND cantidad_disponible > 0",
        (hoy, producto_id),
    ).fetchone()

    # ---- Últimas 4 compras (solo recepciones aprobadas y líneas aceptadas) ----
    compras = db.execute(
        "SELECT r.numero, r.fecha, COALESCE(pr.razon_social, 'Sin proveedor') AS proveedor, "
        "       rl.cantidad_recibida, rl.costo_unitario "
        "FROM recepcion_lineas rl "
        "JOIN recepciones r ON r.id = rl.recepcion_id "
        "LEFT JOIN proveedores pr ON pr.id = r.proveedor_id "
        "WHERE rl.producto_id = ? AND r.estado = 'aprobada' AND rl.resultado = 'aceptado' "
        "ORDER BY r.fecha DESC, r.id DESC, rl.id DESC LIMIT 4",
        (producto_id,),
    ).fetchall()

    # ---- Costo: promedio de los lotes vendibles, pesado por cantidad ----
    # Ej.: 5 unidades a $1.000 y 5 a $1.200 -> costo promedio $1.100.
    # Si no hay lotes con costo, se usa la última compra; si tampoco, el precio
    # de compra escrito en la ficha del producto.
    lotes_con_costo = [l for l in lotes if (l["costo_unitario"] or 0) > 0]
    if lotes_con_costo:
        unidades = sum(l["cantidad_disponible"] for l in lotes_con_costo)
        costo = sum(l["cantidad_disponible"] * l["costo_unitario"] for l in lotes_con_costo) / unidades
        costo_origen = "promedio de lotes"
    elif compras:
        costo, costo_origen = float(compras[0]["costo_unitario"] or 0), "última compra"
    else:
        costo, costo_origen = float(p["precio_compra"] or 0), "ficha del producto"

    # ---- Margen: se calcula sobre el precio SIN IVA (el IVA no es ganancia) ----
    precio = float(p["precio_venta"] or 0)
    tarifa = float(p["iva_tarifa"] or 0)
    precio_sin_iva = precio / (1 + tarifa / 100) if p["iva_tipo"] == "gravado" and tarifa > 0 else precio
    margen = precio_sin_iva - costo
    margen_pct = (margen / precio_sin_iva * 100) if precio_sin_iva > 0 else 0

    categorias = [f["catalogo_id"] for f in db.execute(
        "SELECT catalogo_id FROM productos_categorias WHERE producto_id = ?", (producto_id,))]
    principio = db.execute("SELECT nombre FROM catalogos WHERE id = ?",
                           (p["principio_id"],)).fetchone() if p["principio_id"] else None

    # Presentaciones (unidad, sobre, caja...) con el margen de CADA una:
    # costo de la presentación = costo de 1 unidad x factor
    lista_pres = []
    for opcion in pres.presentaciones_de([producto_id]).get(producto_id, []):
        sin_iva = (opcion["precio"] / (1 + tarifa / 100)
                   if p["iva_tipo"] == "gravado" and tarifa > 0 else opcion["precio"])
        costo_pres = costo * opcion["factor"]
        lista_pres.append({
            **opcion,
            "margen": round(sin_iva - costo_pres, 2),
            "margen_pct": round((sin_iva - costo_pres) / sin_iva * 100, 1) if sin_iva > 0 else 0,
        })

    return jsonify({"ok": True, "producto": {
        "id": p["id"], "codigo": p["codigo"], "codigo_barras": p["codigo_barras"],
        "nombre": p["nombre"], "concentracion": p["concentracion"], "imagen": p["imagen"],
        "precio": precio, "precio_maximo": p["precio_maximo"],
        "precio_sin_iva": round(precio_sin_iva, 2),
        "iva_tipo": p["iva_tipo"], "iva_tarifa": tarifa,
        "iva_valor": round(precio - precio_sin_iva, 2),
        "requiere_formula": bool(p["requiere_formula"]),
        "cadena_frio": bool(p["cadena_frio"]),
        "control_especial": bool(p["control_especial"]),
        "maneja_vencimiento": bool(p["maneja_vencimiento"]),
        "stock_minimo": p["stock_minimo"] or 0,
        "categorias": categorias,
        "usos": _usos_de([producto_id]).get(producto_id, []),
        "principio_activo": (principio["nombre"] if principio else None) or p["principio_activo"],
        "stock": stock,
        "presentaciones": lista_pres,
        "lotes": [{"lote": l["lote"], "vencimiento": l["vencimiento"],
                   "cantidad": l["cantidad_disponible"]} for l in lotes],
        "otros_lotes": {"cuarentena": otros["cuarentena"] or 0,
                        "bloqueados": otros["bloqueados"] or 0,
                        "vencidos": otros["vencidos"] or 0},
        "costo": round(costo, 2), "costo_origen": costo_origen,
        "margen": round(margen, 2), "margen_pct": round(margen_pct, 1),
        "compras": [{"numero": c["numero"], "fecha": c["fecha"], "proveedor": c["proveedor"],
                     "cantidad": c["cantidad_recibida"], "costo": c["costo_unitario"]}
                    for c in compras],
    }})


@bp.route("/api/producto/<int:producto_id>/editar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def api_producto_editar(producto_id):
    """Edición rápida de un producto desde el POS (ventana "Editar" encima de la "i").

    Solo cambia los campos de esta ventana; el resto de la ficha (registro
    sanitario, laboratorio, usos, etc.) queda igual y se edita en Productos.
    """
    db = get_db()
    p = db.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if p is None:
        return _json_error("El producto no existe.", 404)

    f = request.form

    def numero(campo):
        """Convierte '9.800' o '9800,50' en número. Devuelve None si está vacío o no es número."""
        texto = (f.get(campo) or "").strip().replace(" ", "")
        if not texto:
            return None
        # En Colombia el punto separa miles y la coma los decimales: 9.800,50 -> 9800.50
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif texto.count(".") == 1 and len(texto.split(".")[1]) == 3:
            texto = texto.replace(".", "")
        try:
            return float(texto)
        except ValueError:
            return "error"

    nombre = (f.get("nombre") or "").strip()
    codigo_barras = (f.get("codigo_barras") or "").strip() or None
    precio_venta = numero("precio_venta")
    precio_maximo = numero("precio_maximo")
    iva_tipo = (f.get("iva_tipo") or "").strip()
    iva_tarifa = numero("iva_tarifa")
    requiere_formula = 1 if f.get("requiere_formula") else 0
    control_especial = 1 if f.get("control_especial") else 0
    maneja_vencimiento = 1 if f.get("maneja_vencimiento") else 0
    categorias = sorted({int(x) for x in f.getlist("categorias") if x.isdigit()})

    # ---- Validaciones (si algo falla, no se guarda NADA) ----
    if not nombre:
        return _json_error("El nombre es obligatorio.")
    if precio_venta in (None, "error") or precio_venta <= 0:
        return _json_error("El precio de venta debe ser un número mayor a cero.")
    if precio_maximo == "error" or (precio_maximo is not None and precio_maximo < 0):
        return _json_error("El precio máximo no es válido.")
    if precio_maximo and precio_venta > precio_maximo + 0.01:
        return _json_error(f"El precio de venta ({pesos(precio_venta)}) no puede superar "
                           f"el precio máximo ({pesos(precio_maximo)}).")
    if iva_tipo not in IVA_TIPOS:
        return _json_error("Tipo de IVA no válido.")
    if iva_tipo == "gravado":
        if iva_tarifa in (None, "error") or not 0 < iva_tarifa <= 100:
            return _json_error("Escribe la tarifa de IVA (por ejemplo 19).")
    else:
        iva_tarifa = 0.0    # excluido y exento no llevan IVA
    if control_especial and not p["registro_sanitario"]:
        return _json_error("Un producto de control especial debe tener registro sanitario INVIMA "
                           "(complétalo en Productos).")
    if control_especial or p["cadena_frio"]:
        maneja_vencimiento = 1   # misma regla que el formulario completo de productos
    if codigo_barras and db.execute(
            "SELECT 1 FROM productos WHERE codigo_barras = ? AND id <> ?",
            (codigo_barras, producto_id)).fetchone():
        return _json_error("Ese código de barras ya lo tiene otro producto.")

    # ---- Foto: subir nueva, borrar o dejar igual ----
    ruta_imagen = p["imagen"]
    if f.get("imagen_accion") == "eliminar":
        ruta_imagen = None
    archivo = request.files.get("imagen")
    if archivo and archivo.filename:
        ruta_nueva, error = guardar_imagen(archivo, "productos", max_px=1200,
                                           max_bytes=5 * 1024 * 1024)
        if error:
            return _json_error(f"No se pudo subir la foto: {error}")
        ruta_imagen = ruta_nueva

    # ---- Anotar qué cambió (para la bitácora) ----
    antes = {"nombre": p["nombre"], "codigo_barras": p["codigo_barras"],
             "precio_venta": p["precio_venta"], "precio_maximo": p["precio_maximo"],
             "iva": f"{p['iva_tipo']} {p['iva_tarifa'] or 0:g}%",
             "requiere_formula": p["requiere_formula"], "control_especial": p["control_especial"],
             "maneja_vencimiento": p["maneja_vencimiento"], "imagen": p["imagen"]}
    despues = {"nombre": nombre, "codigo_barras": codigo_barras,
               "precio_venta": precio_venta, "precio_maximo": precio_maximo,
               "iva": f"{iva_tipo} {iva_tarifa:g}%",
               "requiere_formula": requiere_formula, "control_especial": control_especial,
               "maneja_vencimiento": maneja_vencimiento, "imagen": ruta_imagen}
    cambios = [f"{k}: {antes[k]} -> {despues[k]}" for k in antes if antes[k] != despues[k]]
    categorias_antes = sorted(r["catalogo_id"] for r in db.execute(
        "SELECT catalogo_id FROM productos_categorias WHERE producto_id = ?", (producto_id,)))
    if categorias_antes != categorias:
        cambios.append(f"categorias: {categorias_antes} -> {categorias}")

    db.execute(
        "UPDATE productos SET nombre=?, codigo_barras=?, precio_venta=?, precio_maximo=?, "
        "iva_tipo=?, iva_tarifa=?, requiere_formula=?, control_especial=?, "
        "maneja_vencimiento=?, imagen=?, actualizado_en=? WHERE id=?",
        (nombre, codigo_barras, precio_venta, precio_maximo, iva_tipo, iva_tarifa,
         requiere_formula, control_especial, maneja_vencimiento, ruta_imagen, ahora(), producto_id),
    )
    db.execute("DELETE FROM productos_categorias WHERE producto_id = ?", (producto_id,))
    for cid in categorias:
        db.execute("INSERT OR IGNORE INTO productos_categorias (producto_id, catalogo_id) "
                   "VALUES (?, ?)", (producto_id, cid))
    db.commit()

    # La foto vieja se borra del disco solo DESPUÉS de guardar bien
    if p["imagen"] and p["imagen"] != ruta_imagen:
        eliminar_imagen(p["imagen"])

    registrar("producto_editado", "productos", producto_id,
              "desde POS · " + ("; ".join(cambios) if cambios else "sin cambios"))
    return jsonify({"ok": True, "cambios": len(cambios)})


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
    # ---- VENTA A CRÉDITO: necesita un cliente registrado y activo ----
    cliente_credito, saldo_previo = None, 0.0
    if forma_pago == "credito":
        from . import cartera
        cliente_credito = db.execute("SELECT * FROM clientes WHERE id = ? AND activo = 1",
                                     (request.form.get("cliente_id", type=int),)).fetchone()
        if cliente_credito is None:
            return _json_error("Para vender a crédito escoge un cliente registrado (Cartera → Nuevo cliente).")
        saldo_previo = cartera.saldo(cliente_credito["id"])     # lo que ya debía
        cliente_nombre = cliente_credito["nombre"]
        cliente_doc = cliente_credito["documento"]

    hoy = date.today().isoformat()
    cambios_precio = []   # textos para la bitácora si el cajero cambió algún precio
    ventas_libres = []    # textos para la bitácora de cada línea de venta libre

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
            # ---- VENTA LIBRE: algo que no está en el inventario ----
            # (una inyectología, una toma de presión...). No descuenta stock.
            if isinstance(item, dict) and item.get("libre"):
                base, descuento, iva_valor, total_linea, texto = _guardar_linea_libre(db, venta_id, item)
                ventas_libres.append(texto)
                sum_subtotal += base
                sum_descuento += descuento
                sum_iva += iva_valor
                sum_total += total_linea
                continue
            try:
                producto_id = int(item.get("producto_id"))
                # 0 = unidad principal; otro número = sobre, caja... (producto_presentaciones)
                presentacion_id = int(item.get("presentacion_id") or 0)
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
            # ---- PRESENTACIÓN: unidad, sobre, caja... ----
            # El precio y el precio máximo salen de la presentación elegida.
            # "factor" dice cuántas unidades del inventario se descuentan por
            # cada una que se vende (1 caja x 100 -> 100 unidades).
            presentacion = pres.presentacion_para_vender(producto_id, presentacion_id)
            if presentacion is None:
                raise _VentaError(f"{nombre}: esa presentación ya no existe. "
                                  "Quítalo del carrito y agrégalo de nuevo.")
            factor = float(presentacion["factor"])
            if presentacion_id != pres.PRINCIPAL:
                nombre = f"{nombre} ({presentacion['nombre']})"
            precio = presentacion["precio"]
            if precio <= 0:
                raise _VentaError(f"{nombre}: no tiene precio de venta.")

            # ---- CAMBIO DE PRECIO AL VENDER (Opción B) ----
            # Por defecto el precio SIEMPRE es el que está en la base de datos
            # (el navegador no puede imponerlo). Solo si el cajero cambió el
            # precio a propósito, llegan dos campos especiales:
            #   precio_nuevo  -> el precio que escribió
            #   motivo_precio -> por qué lo cambió (obligatorio)
            # Cualquier otro campo de precio que mande el navegador se ignora.
            precio_original = precio
            motivo_precio = None
            if item.get("precio_nuevo") not in (None, ""):
                try:
                    precio_nuevo = float(item.get("precio_nuevo"))
                except (TypeError, ValueError):
                    raise _VentaError(f"{nombre}: el precio nuevo no es válido.")
                if precio_nuevo <= 0:
                    raise _VentaError(f"{nombre}: el precio nuevo debe ser mayor a cero.")
                # Solo cuenta como "cambio" si de verdad es distinto (más de 1 centavo)
                if abs(precio_nuevo - precio_original) > 0.01:
                    motivo_precio = str(item.get("motivo_precio") or "").strip()
                    if len(motivo_precio) < 3:
                        raise _VentaError(f"{nombre}: indica el motivo del cambio de precio.")
                    # Los medicamentos tienen un precio máximo regulado: nunca se supera.
                    tope = presentacion["precio_maximo"]
                    if tope > 0 and precio_nuevo > tope + 0.01:
                        raise _VentaError(
                            f"{nombre}: el precio ({pesos(precio_nuevo)}) supera el precio "
                            f"máximo permitido ({pesos(tope)}).")
                    precio = precio_nuevo
                    cambios_precio.append(
                        f"{prod['codigo']} {nombre}: {pesos(precio_original)} -> "
                        f"{pesos(precio_nuevo)} (motivo: {motivo_precio})")

            lotes = db.execute(
                "SELECT l.id, l.lote, l.vencimiento, l.cantidad_disponible FROM lotes l "
                f"WHERE l.producto_id = ? AND {SQL_LOTE_VENDIBLE} "
                "ORDER BY (l.vencimiento IS NULL OR l.vencimiento = ''), l.vencimiento, l.id",
                (producto_id, hoy),
            ).fetchall()
            # Unidades del inventario que salen: cantidad vendida x factor.
            # Si en esta venta hay otra línea del mismo producto (ej: 1 caja y
            # 5 sueltas), sus unidades YA se restaron de los lotes más abajo
            # (dentro de esta misma transacción), así que "disponible" ya lo refleja.
            unidades = round(cantidad * factor, 4)
            disponible = sum(l["cantidad_disponible"] for l in lotes)
            if unidades > disponible + 1e-9:
                if factor == 1:
                    raise _VentaError(f"{nombre}: solo hay {_fmt_cant(disponible)} disponible(s) "
                                      f"y pediste {_fmt_cant(cantidad)}.")
                raise _VentaError(f"{nombre}: pediste {_fmt_cant(cantidad)} = "
                                  f"{_fmt_cant(unidades)} unidades y solo hay "
                                  f"{_fmt_cant(max(disponible, 0))}.")

            pendiente = unidades
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
                "presentacion, presentacion_id, factor, cantidad, precio_unitario, descuento_linea, "
                "iva_tipo, iva_tarifa, subtotal, iva_valor, total, lotes_json, "
                "precio_original, motivo_precio) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (venta_id, producto_id, prod["codigo"], prod["nombre"], presentacion["nombre"],
                 presentacion_id or None, factor, cantidad, precio, descuento,
                 prod["iva_tipo"], tarifa, base, iva_valor, total_linea,
                 json.dumps(asignaciones, ensure_ascii=False),
                 precio_original, motivo_precio),
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
                raise _VentaError(f"El efectivo recibido ({pesos(recibido)}) no alcanza para "
                                  f"el total ({pesos(sum_total)}).")
            cambio = recibido - sum_total
        elif forma_pago == "credito":
            # No se recibe plata: queda debiendo. Si tiene cupo, no puede pasarse.
            if cliente_credito["cupo"] is not None and saldo_previo + sum_total > cliente_credito["cupo"] + 0.5:
                disponible = max(cliente_credito["cupo"] - saldo_previo, 0)
                raise _VentaError(
                    f"{cliente_credito['nombre']} no tiene cupo suficiente: debe {pesos(saldo_previo)}, "
                    f"su cupo es {pesos(cliente_credito['cupo'])} y le quedan {pesos(disponible)} disponibles.")
            recibido, cambio = 0.0, 0.0
            db.execute("UPDATE ventas SET cliente_id = ? WHERE id = ?", (cliente_credito["id"], venta_id))
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
    # Opción B: cualquiera puede cambiar el precio, pero SIEMPRE queda registrado.
    for texto in cambios_precio:
        registrar("venta_precio_modificado", "ventas", venta_id,
                  f"{consecutivo} · {texto}")
    for texto in ventas_libres:
        registrar("venta_libre", "ventas", venta_id, f"{consecutivo} · {texto}")
    return jsonify({"ok": True, "venta_id": venta_id, "consecutivo": consecutivo,
                    "total": sum_total, "cambio": cambio,
                    "url_comprobante": url_for("pos.comprobante", venta_id=venta_id)})

# Tarifas de IVA que se pueden escoger en una venta libre (0 = sin IVA)
TARIFAS_LIBRE = (0, 5, 19)


def _guardar_linea_libre(db, venta_id, item):
    """Guarda una línea de VENTA LIBRE y devuelve (base, descuento, iva, total, texto).

    Lo que manda el navegador:
      descripcion  -> qué se vendió (ej: "Inyectología")
      precio       -> precio de CADA UNA, con IVA incluido
      cantidad, descuento_pct
      iva_tarifa   -> 0, 5 o 19
      costo        -> (opcional) cuánto le cuesta a la droguería cada una
    Aquí el precio SÍ lo pone el cajero (no hay un precio guardado con qué
    compararlo), por eso no se pide motivo; todo queda en la bitácora.
    """
    descripcion = " ".join(str(item.get("descripcion") or "").split())[:120]
    if len(descripcion) < 3:
        raise _VentaError("Venta libre: escribe qué se está vendiendo (mínimo 3 letras).")
    try:
        precio = float(item.get("precio"))
        cantidad = round(float(item.get("cantidad")), 4)
        desc_pct = float(item.get("descuento_pct") or 0)
        tarifa = float(item.get("iva_tarifa") or 0)
        costo_txt = item.get("costo")
        costo = float(costo_txt) if costo_txt not in (None, "") else None
    except (TypeError, ValueError):
        raise _VentaError(f"{descripcion}: hay un dato inválido en la venta libre.")
    if precio <= 0:
        raise _VentaError(f"{descripcion}: el precio debe ser mayor a cero.")
    if cantidad <= 0:
        raise _VentaError(f"{descripcion}: la cantidad debe ser mayor a cero.")
    if not 0 <= desc_pct <= 100:
        raise _VentaError("El descuento debe estar entre 0 y 100 %.")
    if tarifa not in TARIFAS_LIBRE:
        raise _VentaError(f"{descripcion}: la tarifa de IVA debe ser 0, 5 o 19 %.")
    if costo is not None and costo < 0:
        raise _VentaError(f"{descripcion}: el costo no puede ser negativo.")

    # Mismas cuentas que una línea normal (ver más abajo en api_cobrar)
    bruto = cantidad * precio
    descuento = _a_pesos(bruto * desc_pct / 100)
    total_linea = _a_pesos(bruto) - descuento
    if tarifa > 0:
        base = _a_pesos(total_linea / (1 + tarifa / 100))
        iva_valor = total_linea - base
    else:
        base, iva_valor = total_linea, 0

    db.execute(
        "INSERT INTO venta_lineas (venta_id, producto_id, producto_codigo, producto_nombre, "
        "presentacion, factor, cantidad, precio_unitario, descuento_linea, iva_tipo, iva_tarifa, "
        "subtotal, iva_valor, total, lotes_json, precio_original, es_libre, costo_libre) "
        "VALUES (?, NULL, 'LIBRE', ?, NULL, 1, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, 1, ?)",
        (venta_id, descripcion, cantidad, precio, descuento,
         "gravado" if tarifa > 0 else "excluido", tarifa, base, iva_valor, total_linea,
         precio, costo),
    )
    texto = f"{descripcion}: {_fmt_cant(cantidad)} x {pesos(precio)} = {pesos(total_linea)}"
    return base, descuento, iva_valor, total_linea, texto


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
    # Si fue a crédito, mostramos cuánto debe en total el cliente (ver app/cartera.py)
    saldo_cliente = None
    if venta["forma_pago"] == "credito" and venta["cliente_id"]:
        from . import cartera
        saldo_cliente = cartera.saldo(venta["cliente_id"])
    return render_template("pos/comprobante.html", venta=venta, lineas=lineas,
                           config=obtener_config(), saldo_cliente=saldo_cliente)

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
        # Si ya tuvo una devolución, anularla devolvería esas unidades dos veces
        if db.execute("SELECT 1 FROM devoluciones WHERE venta_id = ?", (venta_id,)).fetchone():
            raise _VentaError("Esa venta tiene una devolución registrada; no se puede anular.")
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
