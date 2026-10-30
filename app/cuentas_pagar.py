"""
CUENTAS POR PAGAR A PROVEEDORES (versión 1.1.7)
==============================================

PARA QUÉ (para aprender):
    Es como la Cartera, pero al revés: la Cartera es lo que los CLIENTES le deben
    a la droguería; esto es lo que la droguería les debe a los PROVEEDORES.

    Cada recepción (factura) queda en uno de estos estados (recepciones.pago_estado):
        pendiente   → se debe. Vence en pago_vence (fecha + plazo del proveedor)
        pagada      → ya se pagó (el pago queda en la tabla pagos_proveedores)
        por_revisar → recepciones de ANTES de esta versión: Fernando las revisa una
                      por una y dice si ya estaban pagadas o si se deben
        no_aplica   → recepción rechazada o sin valor

    Fernando siempre paga la factura COMPLETA (sin abonos), así que un pago = una factura.

¿POR QUÉ UN PAGO A PROVEEDOR NO ES UN GASTO?
    Comprar mercancía no es gastar: la plata se vuelve inventario. El costo entra a
    la utilidad cuando se VENDE ("Costo de lo vendido"). Si el pago también se
    contara como gasto, la misma mercancía se restaría dos veces. Por eso el pago
    solo SACA PLATA de donde se pagó (caja menor, caja del POS, Nequi o Davivienda)
    y aparece en el flujo de caja, pero no en la utilidad.

DE DÓNDE SALE LA PLATA (se pregunta cada vez):
    caja_menor → movimiento "Pago a proveedor" en la caja menor
    caja_pos   → salida de efectivo en la caja del POS abierta
    nequi / davivienda → baja el saldo de esa cuenta (app/bancos.py lo suma solo)
    otro       → plata de otro lado (bolsillo, otra cuenta): no mueve ninguna caja
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .formato import pesos
from . import formas_pago as fp   # versión 1.1.14: formas de pago y cuentas (con Daviplata) en un solo lugar

bp = Blueprint("cuentas_pagar", __name__, url_prefix="/cuentas-por-pagar")

ORIGENES = {
    "caja_menor": "Caja menor (efectivo)",
    "caja_pos": "Caja del POS (efectivo)",
    **{c: fp.nombre(c) for c in fp.CLAVES_CUENTAS},       # Nequi, Davivienda, Daviplata
    "otro": "Otro (bolsillo u otra cuenta: no mueve cajas)",
}

# Para facturas viejas ("por revisar") que ya se habían pagado NO se ofrece caja menor
# ni caja del POS: esa plata salió hace días y descontarla hoy dañaría el saldo de hoy.
ORIGENES_ANTIGUOS = fp.CLAVES_CUENTAS + ("otro",)


# ---------------------------------------------------------------------------
# Cálculos que usan otras partes del programa
# ---------------------------------------------------------------------------
def total_de_lineas(lineas):
    """Valor a pagar de una recepción = cantidad × costo con IVA de las líneas NO rechazadas.

    lineas: las de recepciones._leer_lineas_formulario (cantidad y costo por unidad de inventario).
    """
    return round(sum(l["cantidad_recibida"] * (l["costo_con_iva"] or 0)
                     for l in lineas if l["resultado"] != "rechazado"), 2)


def vence_sugerido(fecha_texto, plazo_dias):
    """Fecha de vencimiento = fecha de la factura + plazo del proveedor ('AAAA-MM-DD')."""
    try:
        dia = datetime.strptime((fecha_texto or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        dia = date.today()
    return (dia + timedelta(days=int(plazo_dias or 0))).isoformat()


def resumen(db=None):
    """Totales para el dashboard: cuánto se debe, cuánto está vencido y lo que vence pronto."""
    db = db or get_db()
    hoy = date.today().isoformat()
    en_7 = (date.today() + timedelta(days=7)).isoformat()
    f = db.execute(
        "SELECT COALESCE(SUM(total_pagar), 0) AS total, COUNT(*) AS n, "
        "       COALESCE(SUM(CASE WHEN pago_vence < :hoy THEN total_pagar END), 0) AS vencido, "
        "       COUNT(CASE WHEN pago_vence < :hoy THEN 1 END) AS n_vencidas, "
        "       COALESCE(SUM(CASE WHEN pago_vence >= :hoy AND pago_vence <= :en7 THEN total_pagar END), 0) AS pronto, "
        "       COUNT(CASE WHEN pago_vence >= :hoy AND pago_vence <= :en7 THEN 1 END) AS n_pronto "
        "FROM recepciones WHERE pago_estado = 'pendiente'", {"hoy": hoy, "en7": en_7}).fetchone()
    revisar = db.execute("SELECT COUNT(*) n, COALESCE(SUM(total_pagar), 0) t FROM recepciones "
                         "WHERE pago_estado = 'por_revisar'").fetchone()
    return dict(f, por_revisar=revisar["n"], por_revisar_total=revisar["t"])


def saldos_origen(db):
    """Cuánta plata hay en cada lugar, para mostrarlo al escoger de dónde pagar."""
    from .bancos import cuenta_por_clave, saldo
    from .caja_menor import saldo_actual
    from .pos import _resumen_caja
    caja = db.execute("SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1").fetchone()
    saldos = {"caja_menor": saldo_actual(db),
              "caja_pos": _resumen_caja(caja)["efectivo_esperado"] if caja else None}
    for clave in fp.CLAVES_CUENTAS:
        c = cuenta_por_clave(db, clave)
        saldos[clave] = saldo(db, c) if c else None
    return saldos, caja


def registrar_pago(db, rec, monto, fecha, origen, observaciones=None):
    """Registra el pago COMPLETO de una factura y saca la plata de donde se pagó.

    rec = fila de recepciones (con proveedor_id). No hace commit.
    Devuelve (pago_id, None) o (None, "mensaje de error").
    """
    if origen not in ORIGENES:
        return None, "Escoge de dónde salió la plata."
    if not monto or monto <= 0:
        return None, "El valor del pago debe ser mayor a cero."
    factura = rec["factura_numero"] or rec["remision_numero"] or rec["numero"]
    prov = db.execute("SELECT razon_social FROM proveedores WHERE id = ?", (rec["proveedor_id"],)).fetchone()
    texto = f"Pago factura {factura} · {prov['razon_social'] if prov else 'proveedor'}"
    caja_id = caja_menor_mov_id = caja_mov_id = None
    if origen == "caja_menor":
        caja_menor_mov_id = db.execute(
            "INSERT INTO caja_menor_movimientos (fecha, tipo, monto, motivo, usuario_id, usuario_nombre, creado_en) "
            "VALUES (?, 'pago_proveedor', ?, ?, ?, ?, ?)",
            (fecha, monto, texto, g.user["id"], g.user["nombre"], ahora())).lastrowid
    elif origen == "caja_pos":
        caja = db.execute("SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1").fetchone()
        if caja is None:
            return None, "No hay caja del POS abierta: escoge otro lugar de donde salió la plata."
        caja_id = caja["id"]
        caja_mov_id = db.execute(
            "INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, usuario_id, "
            "usuario_nombre, creado_en, origen) VALUES (?,?, 'salida', 'efectivo', ?,?,?,?,?, 'proveedor')",
            (caja_id, fecha, monto, texto, g.user["id"], g.user["nombre"], ahora())).lastrowid
    pago_id = db.execute(
        "INSERT INTO pagos_proveedores (recepcion_id, proveedor_id, fecha, monto, origen, caja_id, caja_menor_mov_id, "
        "caja_mov_id, observaciones, usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (rec["id"], rec["proveedor_id"], fecha, monto, origen, caja_id, caja_menor_mov_id, caja_mov_id,
         observaciones, g.user["id"], g.user["nombre"], ahora())).lastrowid
    db.execute("UPDATE recepciones SET pago_estado = 'pagada' WHERE id = ?", (rec["id"],))
    return pago_id, None


def _recepcion(db, rec_id):
    rec = db.execute("SELECT r.*, p.razon_social AS proveedor_nombre, p.plazo_dias FROM recepciones r "
                     "JOIN proveedores p ON p.id = r.proveedor_id WHERE r.id = ?", (rec_id,)).fetchone()
    if rec is None:
        abort(404)
    return rec


def _dias(vence):
    """Días que faltan para el vencimiento (negativo = vencida hace tantos días)."""
    try:
        return (datetime.strptime(vence, "%Y-%m-%d").date() - date.today()).days
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@roles_required("administrador", "director_tecnico")
def index():
    db = get_db()
    ver = request.args.get("ver", "por_pagar")
    proveedor = request.args.get("proveedor", "").strip()
    base = ("SELECT r.*, p.razon_social AS proveedor_nombre, p.plazo_dias FROM recepciones r "
            "JOIN proveedores p ON p.id = r.proveedor_id WHERE r.pago_estado = ?")
    params = []
    filtro = ""
    if proveedor:
        filtro = " AND r.proveedor_id = ?"
        params.append(int(proveedor))
    pendientes = [dict(f, dias=_dias(f["pago_vence"])) for f in db.execute(
        base + filtro + " ORDER BY r.pago_vence, r.fecha", ("pendiente", *params))]
    por_revisar = [dict(f, vence_sug=vence_sugerido(f["fecha"], f["plazo_dias"] or 30)) for f in db.execute(
        base + filtro + " ORDER BY r.fecha", ("por_revisar", *params))]
    pagos = db.execute(
        "SELECT pp.*, p.razon_social AS proveedor_nombre, r.numero, r.factura_numero, r.remision_numero, r.fecha AS fecha_factura "
        "FROM pagos_proveedores pp JOIN proveedores p ON p.id = pp.proveedor_id JOIN recepciones r ON r.id = pp.recepcion_id "
        "WHERE 1 = 1" + (" AND pp.proveedor_id = ?" if proveedor else "") +
        " ORDER BY pp.fecha DESC, pp.id DESC LIMIT 200", params).fetchall()
    # Lo que se debe, agrupado por proveedor (la tablita de la derecha)
    por_proveedor = db.execute(
        "SELECT p.id, p.razon_social, COUNT(*) n, SUM(r.total_pagar) total, "
        "       SUM(CASE WHEN r.pago_vence < date('now', 'localtime') THEN r.total_pagar ELSE 0 END) vencido "
        "FROM recepciones r JOIN proveedores p ON p.id = r.proveedor_id WHERE r.pago_estado = 'pendiente' "
        "GROUP BY p.id ORDER BY total DESC").fetchall()
    proveedores = db.execute("SELECT DISTINCT p.id, p.razon_social FROM proveedores p JOIN recepciones r "
                             "ON r.proveedor_id = p.id ORDER BY p.razon_social COLLATE ES").fetchall()
    return render_template("cuentas_pagar/index.html", ver=ver, pendientes=pendientes, por_revisar=por_revisar,
                           pagos=pagos, por_proveedor=por_proveedor, r=resumen(db), origenes=ORIGENES,
                           origenes_antiguos=ORIGENES_ANTIGUOS, proveedores=proveedores, proveedor=proveedor,
                           hoy=date.today().isoformat())


@bp.route("/pagar/<int:rec_id>", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def pagar(rec_id):
    """Registrar el pago de una factura: cuánto, cuándo y de dónde salió la plata."""
    from .bancos import fecha_de_form, monto_de_form
    db = get_db()
    rec = _recepcion(db, rec_id)
    if rec["pago_estado"] == "pagada":
        flash("Esa factura ya está pagada.", "error")
        return redirect(url_for("cuentas_pagar.index", ver="pagadas"))
    if request.method == "POST":
        monto = monto_de_form(request.form.get("monto"))
        fecha = fecha_de_form(request.form.get("fecha"))
        origen = request.form.get("origen", "")
        if fecha is None:
            flash("La fecha del pago no es válida (no puede ser del futuro).", "error")
        else:
            pago_id, error = registrar_pago(db, rec, monto, fecha, origen,
                                            (request.form.get("observaciones") or "").strip() or None)
            if error:
                flash(error, "error")
            else:
                db.commit()
                registrar("pago_proveedor", "pagos_proveedores", pago_id,
                          f"recepcion={rec['numero']} monto={monto} origen={origen}")
                flash(f"Pago registrado: {pesos(monto)} a {rec['proveedor_nombre']} desde {ORIGENES[origen]}.", "ok")
                return redirect(url_for("cuentas_pagar.index"))
    saldos, caja = saldos_origen(db)
    return render_template("cuentas_pagar/pagar.html", rec=rec, dias=_dias(rec["pago_vence"]),
                           origenes=ORIGENES, saldos=saldos, caja=caja, hoy=date.today().isoformat())


@bp.route("/revisar/<int:rec_id>", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def revisar(rec_id):
    """Facturas de antes de la 1.1.7: decir si ya estaban pagadas o si se deben."""
    from .bancos import fecha_de_form
    db = get_db()
    rec = _recepcion(db, rec_id)
    if rec["pago_estado"] != "por_revisar":
        flash("Esa factura ya se había revisado.", "error")
        return redirect(url_for("cuentas_pagar.index", ver="por_revisar"))
    accion = request.form.get("accion")
    if accion == "pendiente":
        vence = (request.form.get("vence") or "").strip()
        try:
            datetime.strptime(vence, "%Y-%m-%d")
        except ValueError:
            flash("Escribe la fecha en que vence la factura.", "error")
            return redirect(url_for("cuentas_pagar.index", ver="por_revisar"))
        db.execute("UPDATE recepciones SET pago_estado = 'pendiente', pago_vence = ? WHERE id = ?", (vence, rec_id))
        texto = f"queda como «se debe», vence el {vence}"
    elif accion == "pagada":
        origen = request.form.get("origen", "")
        fecha = fecha_de_form(request.form.get("fecha"))
        if origen not in ORIGENES_ANTIGUOS or fecha is None:
            flash("Escoge cómo se pagó y una fecha válida.", "error")
            return redirect(url_for("cuentas_pagar.index", ver="por_revisar"))
        _, error = registrar_pago(db, rec, rec["total_pagar"], fecha, origen, "Revisión de facturas anteriores")
        if error:
            flash(error, "error")
            return redirect(url_for("cuentas_pagar.index", ver="por_revisar"))
        texto = f"queda como pagada ({ORIGENES[origen]})"
    elif accion == "no_aplica":
        db.execute("UPDATE recepciones SET pago_estado = 'no_aplica' WHERE id = ?", (rec_id,))
        texto = "queda como «no hay que pagarla»"
    else:
        abort(400)
    db.commit()
    registrar("cxp_revisada", "recepciones", rec_id, f"{rec['numero']} {texto}")
    flash(f"Factura {rec['factura_numero'] or rec['numero']} de {rec['proveedor_nombre']} {texto}.", "ok")
    return redirect(url_for("cuentas_pagar.index", ver="por_revisar"))


@bp.route("/<int:rec_id>/vence", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def cambiar_vence(rec_id):
    """Cambiar la fecha de vencimiento de una factura que se debe."""
    db = get_db()
    rec = _recepcion(db, rec_id)
    vence = (request.form.get("vence") or "").strip()
    try:
        datetime.strptime(vence, "%Y-%m-%d")
    except ValueError:
        flash("Fecha no válida.", "error")
        return redirect(url_for("cuentas_pagar.index"))
    db.execute("UPDATE recepciones SET pago_vence = ? WHERE id = ? AND pago_estado = 'pendiente'", (vence, rec_id))
    db.commit()
    registrar("cxp_vence", "recepciones", rec_id, f"{rec['numero']} vence={vence}")
    flash("Fecha de vencimiento cambiada.", "ok")
    return redirect(url_for("cuentas_pagar.index"))


@bp.route("/pago/<int:pago_id>/anular", methods=["POST"])
@login_required
@roles_required("administrador")
def anular(pago_id):
    """Anular un pago: la factura vuelve a «se debe» y la plata vuelve a donde salió."""
    db = get_db()
    p = db.execute("SELECT * FROM pagos_proveedores WHERE id = ?", (pago_id,)).fetchone()
    if p is None or p["anulado"]:
        abort(404)
    motivo = (request.form.get("motivo") or "").strip() or "Anulado"
    texto = f"Anulación pago a proveedor (recepción {p['recepcion_id']})"
    if p["origen"] == "caja_menor":
        db.execute("INSERT INTO caja_menor_movimientos (fecha, tipo, monto, motivo, usuario_id, usuario_nombre, creado_en) "
                   "VALUES (?, 'aporte', ?, ?, ?, ?, ?)", (ahora(), p["monto"], texto, g.user["id"], g.user["nombre"], ahora()))
    elif p["origen"] == "caja_pos":
        caja = db.execute("SELECT * FROM cajas WHERE id = ? AND estado = 'abierta'", (p["caja_id"],)).fetchone()
        if caja is not None:          # la caja sigue abierta: la plata vuelve a esa caja
            db.execute("INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, usuario_id, "
                       "usuario_nombre, creado_en, origen) VALUES (?,?, 'ingreso', 'efectivo', ?,?,?,?,?, 'proveedor')",
                       (caja["id"], ahora(), p["monto"], texto, g.user["id"], g.user["nombre"], ahora()))
        else:                         # la caja ya se cerró: la plata vuelve a la caja menor
            db.execute("INSERT INTO caja_menor_movimientos (fecha, tipo, monto, motivo, usuario_id, usuario_nombre, "
                       "creado_en) VALUES (?, 'aporte', ?, ?, ?, ?, ?)",
                       (ahora(), p["monto"], texto, g.user["id"], g.user["nombre"], ahora()))
    # Nequi, Davivienda u otro: no hay que hacer nada más (Bancos ya no lo cuenta al estar anulado)
    db.execute("UPDATE pagos_proveedores SET anulado = 1, anulado_motivo = ?, anulado_en = ?, anulado_por_nombre = ? "
               "WHERE id = ?", (motivo, ahora(), g.user["nombre"], pago_id))
    rec = db.execute("SELECT r.*, p.plazo_dias FROM recepciones r JOIN proveedores p ON p.id = r.proveedor_id "
                     "WHERE r.id = ?", (p["recepcion_id"],)).fetchone()
    db.execute("UPDATE recepciones SET pago_estado = 'pendiente', pago_vence = COALESCE(pago_vence, ?) WHERE id = ?",
               (vence_sugerido(rec["fecha"], rec["plazo_dias"]), rec["id"]))
    db.commit()
    registrar("pago_proveedor_anulado", "pagos_proveedores", pago_id, f"monto={p['monto']} motivo={motivo}")
    flash("Pago anulado: la factura vuelve a «por pagar».", "ok")
    return redirect(url_for("cuentas_pagar.index"))
