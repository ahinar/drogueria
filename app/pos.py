"""Punto de venta (POS): cajas, ventas, movimientos, gastos y cobro."""
import json
import logging

from flask import (Blueprint, abort, flash, g, jsonify, redirect,
                   render_template, request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .caja_menor import registrar_movimiento as _cm_mov
from .caja_menor import saldo_actual as _cm_saldo
from .configuracion import obtener_config
from .formato import pesos
from . import formas_pago as fp        # versión 1.1.14: la lista de formas de pago (con Daviplata)
from .db import ahora, get_db
from .utiles import siguiente_numero   # versión 1.1.15: ayudas comunes (app/utiles.py)

log = logging.getLogger("drogueria")   # el diario de errores (fervifarma.log)

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
    return siguiente_numero(get_db(), "ventas", "V", columna="consecutivo")

def _resumen_caja(caja):
    """Devuelve el resumen completo del turno: ventas, movimientos, totales por forma de pago."""
    db = get_db()

    # Ventas por forma de pago. Las ventas con PAGO MIXTO se "parten": su parte en
    # efectivo suma en Efectivo, la de Nequi en Nequi... (tabla venta_pagos).
    # Así el efectivo esperado del cierre cuadra con los billetes del cajón.
    ventas_por_pago = db.execute(
        "SELECT forma_pago, COUNT(*) AS n, COALESCE(SUM(total), 0) AS total FROM ("
        "  SELECT forma_pago, total FROM ventas "
        "  WHERE caja_id = ? AND estado = 'completada' AND forma_pago <> 'mixto' "
        "  UNION ALL "
        "  SELECT vp.forma_pago, vp.monto AS total FROM venta_pagos vp "
        "  JOIN ventas v ON v.id = vp.venta_id "
        "  WHERE v.caja_id = ? AND v.estado = 'completada' AND v.forma_pago = 'mixto'"
        ") GROUP BY forma_pago",
        (caja["id"], caja["id"]),
    ).fetchall()

    # Número de ventas: se cuentan las ventas (una mixta cuenta UNA vez, no una por parte)
    total_ventas_n = db.execute(
        "SELECT COUNT(*) FROM ventas WHERE caja_id = ? AND estado = 'completada'", (caja["id"],)).fetchone()[0]
    total_ventas = sum(p["total"] for p in ventas_por_pago)

    movs = db.execute(
        "SELECT * FROM caja_movimientos WHERE caja_id = ? ORDER BY id DESC",
        (caja["id"],),
    ).fetchall()

    def _movido(tipo, forma):
        """Suma de las entradas ('ingreso') o salidas ('salida') a mano de una forma de pago."""
        return sum(m["monto"] for m in movs if m["tipo"] == tipo and m["forma_pago"] == forma)

    def _vendido(forma):
        fila = next((p for p in ventas_por_pago if p["forma_pago"] == forma), None)
        return fila["total"] if fila else 0

    resumen = {
        "n_ventas": total_ventas_n,
        "total_ventas": total_ventas,
        "por_pago": ventas_por_pago,
        "movimientos": movs,
        "efectivo_inicial": caja["efectivo_inicial"] or 0,
        "ventas_tarjeta": _vendido("tarjeta"),
        "ventas_credito": _vendido("credito"),
        # Versión 1.1.14: una línea por cuenta (Nequi, Davivienda, Daviplata...), sacada
        # de formas_pago.CUENTAS. Así el cierre de caja muestra todas sin cambiar código.
        "cuentas": [],
    }
    # Efectivo y cada cuenta: ventas_X, ingresos_X y salidas_X (ej. ventas_nequi)
    for forma in ("efectivo",) + fp.CLAVES_CUENTAS:
        resumen[f"ventas_{forma}"] = _vendido(forma)
        resumen[f"ingresos_{forma}"] = _movido("ingreso", forma)
        resumen[f"salidas_{forma}"] = _movido("salida", forma)
        if forma != "efectivo":
            resumen["cuentas"].append({"clave": forma, "nombre": fp.nombre(forma),
                                       "ventas": resumen[f"ventas_{forma}"],
                                       "ingresos": resumen[f"ingresos_{forma}"],
                                       "salidas": resumen[f"salidas_{forma}"]})
    # Billetes que deberían estar en el cajón al cerrar
    resumen["efectivo_esperado"] = (resumen["efectivo_inicial"] + resumen["ventas_efectivo"]
                                    + resumen["ingresos_efectivo"] - resumen["salidas_efectivo"])
    return resumen

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
        "ORDER BY nombre COLLATE ES"
    ).fetchall()

    categorias_gasto = db.execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'categoria_gasto' AND activo = 1 "
        "ORDER BY nombre COLLATE ES"
    ).fetchall()

    # Categorías de "otro ingreso" (recargas, arriendo...), para la ventana del POS
    categorias_ingreso = [dict(f) for f in db.execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'categoria_ingreso' AND activo = 1 "
        "ORDER BY nombre COLLATE ES")]

    config = obtener_config()
    # Unidades de medida para la ventana "Editar producto" (presentaciones, versión 1.1.12)
    from .nombres import orden_unidades
    unidades = orden_unidades(db.execute(
        "SELECT id, nombre, cantidad FROM unidades_medida WHERE activo = 1").fetchall())
    # Ventas rápidas (versión 1.1.13): fotocopias, dulcería... para los botones de «+ Venta libre»
    from .ventas_rapidas import lista_activas
    return render_template("pos/index.html", caja=caja, resumen=resumen, unidades=unidades,
                           ventas_rapidas=lista_activas(db),
                           cajon_modo=config.get("cajon_modo") or "no",
                           tirilla_modo=config.get("tirilla_modo") or "navegador",
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
    if forma_pago not in fp.FORMAS_CAJA:
        return jsonify({"ok": False, "error": "Forma de pago inválida."}), 400

    try:
        monto = float((request.form.get("monto") or "0").replace(",", "."))
    except ValueError:
        return jsonify({"ok": False, "error": "Monto inválido."}), 400

    if monto <= 0:
        return jsonify({"ok": False, "error": "El monto debe ser mayor a cero."}), 400

    # Versión 1.1.14 (botón «Movimiento de plata»): de dónde viene o a dónde va el efectivo.
    #   dueno       -> plata personal del dueño: retiro (sale) o aporte (entra). No es gasto
    #                  ni ingreso del negocio; Utilidades muestra los retiros aparte.
    #   caja_menor  -> la plata pasa a la caja menor (sale) o viene de ella (entra), y queda
    #                  registrada TAMBIÉN allá, para que su saldo cuadre solo.
    #   nequi, davivienda, daviplata -> se consignó en (sale) o se sacó de (entra) esa
    #                  cuenta: queda como traslado en Bancos.
    #   vacío       -> no se dijo (como antes).
    lugar = (request.form.get("lugar") or "").strip().lower() or None
    if lugar and lugar not in ("dueno", "caja_menor") + fp.CLAVES_CUENTAS:
        return jsonify({"ok": False, "error": "No se sabe a dónde va la plata."}), 400
    if lugar and forma_pago != "efectivo":
        return jsonify({"ok": False, "error": "Escoger a dónde va solo aplica para el efectivo."}), 400
    if not motivo and lugar:
        motivo = _texto_lugar(tipo, lugar, caja)

    db = get_db()
    cur = db.execute(
        "INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, lugar, "
        "usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (caja["id"], ahora(), tipo, forma_pago, monto, motivo, lugar,
         g.user["id"], g.user["nombre"], ahora()),
    )
    texto = _texto_lugar(tipo, lugar, caja) if lugar else None
    if lugar == "caja_menor":
        # 'aporte' = entra a la caja menor ; 'apertura_pos' = sale de la caja menor hacia el POS
        _cm_mov(db, "aporte" if tipo == "salida" else "apertura_pos", monto, texto, caja_id=caja["id"])
    elif lugar in fp.CLAVES_CUENTAS:
        from .bancos import _mov_banco, cuenta_por_clave
        cuenta = cuenta_por_clave(db, lugar)
        if cuenta is None:
            db.rollback()
            return jsonify({"ok": False, "error": f"No existe la cuenta {fp.nombre(lugar)} en Bancos."}), 400
        _mov_banco(db, cuenta, "traslado_entrada" if tipo == "salida" else "traslado_salida",
                   monto, ahora(), texto, f"POS-{cur.lastrowid}")
    db.commit()
    registrar(f"caja_{tipo}", "caja_movimientos", cur.lastrowid,
              f"monto={monto} forma_pago={forma_pago} lugar={lugar} motivo={motivo}")

    return jsonify({"ok": True, "id": cur.lastrowid})


def _texto_lugar(tipo, lugar, caja):
    """Explicación corta del movimiento, para la caja, Bancos y la bitácora."""
    if lugar == "dueno":
        return "Plata que se lleva el dueño" if tipo == "salida" else "Plata que pone el dueño"
    destino = "la caja menor" if lugar == "caja_menor" else fp.nombre(lugar)
    if tipo == "salida":
        return f"De la caja del POS #{caja['numero']} a {destino}"
    return f"De {destino} a la caja del POS #{caja['numero']}"

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
    if forma_pago not in fp.FORMAS_MOVIMIENTO:
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
            "usuario_id, usuario_nombre, creado_en, origen) VALUES (?,?,?,?,?,?,?,?,?, 'gasto')",
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

FORMAS_INGRESO = fp.FORMAS_MOVIMIENTO          # efectivo, las cuentas, tarjeta y transferencia


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
            "usuario_id, usuario_nombre, creado_en, origen) VALUES (?,?, 'ingreso', 'efectivo', ?,?,?,?,?, 'otro_ingreso')",
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
            # Nequi, Davivienda, Daviplata... (versión 1.1.14: la lista sale de formas_pago.py)
            "cuentas": resumen["cuentas"],
            **{c["clave"]: {"ventas": c["ventas"], "ingresos": c["ingresos"], "salidas": c["salidas"]}
               for c in resumen["cuentas"]},
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

    # Versión 1.1.6: el sobrante (ingreso) o faltante (gasto) queda en la contabilidad
    from .cajas import registrar_diferencia
    registrar_diferencia(db, caja["id"])

    db.commit()
    registrar("caja_cerrada", "cajas", caja["id"],
              f"numero={caja['numero']} contado={total} esperado={resumen['efectivo_esperado']} "
              f"diferencia={diferencia}")

    # 1.1.16: mini resumen al celular por Telegram (si está configurado). Va en segundo
    # plano y nunca hace fallar el cierre: si algo sale mal, solo queda en el log.
    try:
        from . import telegram
        if telegram.activo("cierre_caja"):
            telegram.enviar(telegram.mensaje_cierre_caja(db, caja["id"]), "cierre_caja")
    except Exception:
        log.exception("No se pudo armar el aviso de cierre de caja para Telegram")
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
# Versión 1.1.14: las listas salen de app/formas_pago.py (ahí está Daviplata).
FORMAS_PAGO = fp.FORMAS_VENTA
# En un pago MIXTO se pueden combinar estas (el crédito no: o se fía todo o nada)
FORMAS_MIXTO = fp.FORMAS_MIXTO
NOMBRES_PAGO = {**fp.NOMBRES, "credito": "Crédito", "mixto": "Mixto"}   # nombres cortos para la tirilla

class _VentaError(Exception):
    """Error de negocio al cobrar (ej: 'no hay stock'). El mensaje se le muestra al cajero."""


def _pagos_mixtos(formulario, total):
    """PAGO MIXTO (versión 1.1.3): reparte el total entre varias formas de pago.

    El POS manda en "pagos" cuánto entra por cada cuenta (Nequi, Davivienda, Daviplata) y Tarjeta, por
    ejemplo {"nequi": 20000}. Lo que falta para el total es EFECTIVO.
    "monto_recibido" = billetes que entregó el cliente para la parte en efectivo
    (sirve para calcular el cambio).

    Devuelve (partes, recibido, cambio):
        partes = [("efectivo", 15000), ("nequi", 20000)]
    o lanza _VentaError con un mensaje claro para el cajero.
    """
    try:
        datos = json.loads(formulario.get("pagos") or "{}")
        if not isinstance(datos, dict):
            raise ValueError
    except (ValueError, TypeError):
        raise _VentaError("Los valores del pago mixto llegaron dañados. Intenta de nuevo.")

    otros = []
    for forma in fp.FORMAS_MIXTO_OTRAS:
        texto = str(datos.get(forma) or "0").strip().replace(",", ".")
        try:
            monto = float(texto or 0)
        except ValueError:
            raise _VentaError(f"El valor de {NOMBRES_PAGO[forma]} no es válido.")
        if monto < 0:
            raise _VentaError(f"El valor de {NOMBRES_PAGO[forma]} no puede ser negativo.")
        if monto > 0:
            otros.append((forma, round(monto, 2)))

    suma_otros = sum(m for _f, m in otros)
    if suma_otros > total + 0.5:
        raise _VentaError(f"Lo que entra por las cuentas o la tarjeta ({pesos(suma_otros)}) "
                          f"es más que el total de la venta ({pesos(total)}).")
    efectivo = round(total - suma_otros, 2)
    if efectivo < 0.5:                       # diferencias de centavos: no hay parte en efectivo
        efectivo = 0
    partes = ([("efectivo", efectivo)] if efectivo else []) + otros
    if len(partes) < 2:
        raise _VentaError("Para un pago mixto usa al menos dos formas de pago "
                          "(por ejemplo una parte por Nequi y el resto en efectivo).")

    recibido_txt = (formulario.get("monto_recibido") or "").strip()
    try:
        recibido = float(recibido_txt.replace(",", ".")) if recibido_txt else float(efectivo)
    except ValueError:
        raise _VentaError("El efectivo recibido no es válido.")
    if recibido + 1e-9 < efectivo:
        raise _VentaError(f"El efectivo recibido ({pesos(recibido)}) no alcanza para la parte "
                          f"en efectivo ({pesos(efectivo)}).")
    return partes, recibido, recibido - efectivo

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

@bp.route("/cerrar-caja")
@login_required
def cerrar_caja():
    """Redirige al POS (el cierre ahora es un modal)."""
    return redirect(url_for("pos.index"))


# ============================================================
# Las demás partes del POS (versión 1.1.15): se importan al final para que sus rutas
# queden registradas en este mismo blueprint (bp). Ver pos_productos.py y pos_ventas.py.
# ============================================================
from . import pos_productos, pos_ventas  # noqa: E402,F401
