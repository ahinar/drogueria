"""
CARTERA (cuentas por cobrar): ventas a CRÉDITO a clientes registrados.

Cómo funciona, en palabras sencillas:
    1. El jefe registra al cliente (nombre, cédula, teléfono) y, si quiere,
       le pone un CUPO: hasta cuánto puede deber.
    2. En el POS, al cobrar, se escoge la forma de pago "Crédito" y el
       cliente. No entra plata a la caja: queda debiendo.
    3. Cuando el cliente paga (todo o una parte) se registra un ABONO
       (AB-0001). Si paga en efectivo, la plata entra a la caja abierta.
    4. Aquí se ve cuánto debe cada uno, desde cuándo, y su estado de cuenta.

DE DÓNDE SALE EL SALDO de un cliente:
      ventas a crédito (completadas, no anuladas)
    − devoluciones de esas ventas que se descontaron de la deuda
    − abonos (no anulados)
    = saldo. Si da negativo, el cliente tiene "saldo a favor".

ANTIGÜEDAD (¿desde cuándo debe?): los abonos pagan primero las ventas más
viejas (eso se llama FIFO: lo primero que entra es lo primero que sale).
Así se sabe qué ventas siguen pendientes y cuántos días llevan.
"""
from datetime import date, datetime

from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template,
                   request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .configuracion import obtener_config
from .db import ahora, get_db
from .formato import pesos

bp = Blueprint("cartera", __name__, url_prefix="/cartera")

JEFES = ("administrador", "director_tecnico")
FORMAS_ABONO = {"efectivo": "Efectivo", "nequi": "Nequi", "davivienda": "Davivienda",
                "transferencia": "Transferencia", "tarjeta": "Tarjeta"}
# Estas formas quedan en el cierre de caja (caja_movimientos) si hay caja abierta
FORMAS_EN_CAJA = ("efectivo", "nequi", "davivienda")
# Grupos de antigüedad: (texto, desde día, hasta día)
RANGOS = [("0 a 30 días", 0, 30), ("31 a 60 días", 31, 60), ("61 a 90 días", 61, 90), ("Más de 90 días", 91, 10 ** 6)]
DIAS_VENCIDA = 30   # desde aquí la deuda se considera "vencida" (sale en las alertas)


class CarteraError(Exception):
    """Error de negocio (ej: 'el cliente solo debe $5.000'). El mensaje se muestra tal cual."""


# ======================================================================
# 1. CÁLCULOS
# ======================================================================

def _dia(fecha_texto):
    """'2026-10-10 09:44:00' -> date(2026, 10, 10)"""
    return datetime.strptime(fecha_texto[:10], "%Y-%m-%d").date()


def estado_de_cuenta(cliente_id, hoy=None):
    """Todo lo de un cliente: saldo, ventas pendientes (con días) y movimientos.

    Devuelve un diccionario con:
      saldo        -> lo que debe hoy (negativo = saldo a favor)
      pendientes   -> ventas que aún no termina de pagar, la más vieja primero
      movimientos  -> ventas, devoluciones y abonos en orden, con el saldo acumulado
      dias_mayor   -> días de la venta pendiente más vieja (0 si no debe)
    """
    hoy = hoy or date.today()
    db = get_db()
    ventas = db.execute(
        "SELECT id, consecutivo, fecha, total FROM ventas "
        "WHERE cliente_id = ? AND forma_pago = 'credito' AND estado = 'completada' "
        "ORDER BY fecha, id", (cliente_id,)).fetchall()
    # Devoluciones de esas ventas que se descontaron de la deuda (no se devolvió plata)
    devoluciones = db.execute(
        "SELECT d.id, d.numero, d.fecha, d.total, d.venta_id, v.consecutivo "
        "FROM devoluciones d JOIN ventas v ON v.id = d.venta_id "
        "WHERE d.tipo = 'cliente' AND d.forma_reembolso = 'credito' AND v.cliente_id = ? "
        "AND v.estado = 'completada' ORDER BY d.fecha, d.id", (cliente_id,)).fetchall()
    abonos = db.execute(
        "SELECT * FROM cartera_abonos WHERE cliente_id = ? AND anulado = 0 ORDER BY fecha, id",
        (cliente_id,)).fetchall()

    # ---- Valor real de cada venta (lo vendido menos lo devuelto) ----
    devuelto = {}
    for d in devoluciones:
        devuelto[d["venta_id"]] = devuelto.get(d["venta_id"], 0) + d["total"]

    # ---- FIFO: los abonos pagan primero las ventas más viejas ----
    por_repartir = sum(a["monto"] for a in abonos)
    pendientes = []
    for v in ventas:
        valor = v["total"] - devuelto.get(v["id"], 0)
        pagado = min(valor, max(por_repartir, 0))
        por_repartir -= pagado
        falta = round(valor - pagado, 2)
        if falta > 0.5:     # medio peso de tolerancia por redondeos
            dias = (hoy - _dia(v["fecha"])).days
            pendientes.append({"venta_id": v["id"], "consecutivo": v["consecutivo"], "fecha": v["fecha"],
                               "valor": valor, "pagado": pagado, "pendiente": falta, "dias": dias})

    # ---- Movimientos en orden de fecha, con saldo acumulado (como un extracto) ----
    movs = [{"fecha": v["fecha"], "tipo": "venta", "documento": v["consecutivo"], "venta_id": v["id"],
             "cargo": v["total"], "abono": 0} for v in ventas]
    movs += [{"fecha": d["fecha"], "tipo": "devolucion", "documento": f"{d['numero']} (venta {d['consecutivo']})",
              "devolucion_id": d["id"], "cargo": 0, "abono": d["total"]} for d in devoluciones]
    movs += [{"fecha": a["fecha"], "tipo": "abono", "documento": a["numero"], "abono_id": a["id"],
              "forma": FORMAS_ABONO.get(a["forma_pago"], a["forma_pago"]),
              "cargo": 0, "abono": a["monto"]} for a in abonos]
    movs.sort(key=lambda m: m["fecha"])
    saldo = 0.0
    for m in movs:
        saldo += m["cargo"] - m["abono"]
        m["saldo"] = saldo

    return {"saldo": round(saldo, 2), "pendientes": pendientes, "movimientos": movs,
            "dias_mayor": max((p["dias"] for p in pendientes), default=0),
            "total_ventas": sum(v["total"] for v in ventas),
            "total_abonos": sum(a["monto"] for a in abonos)}


def saldo(cliente_id):
    """Lo que debe hoy el cliente (atajo)."""
    return estado_de_cuenta(cliente_id)["saldo"]


def disponible(cliente):
    """Cuánto más le podemos fiar. None = sin límite (no tiene cupo)."""
    if cliente["cupo"] is None:
        return None
    return cliente["cupo"] - saldo(cliente["id"])


def resumen(hoy=None, todos=False, q=""):
    """Cartera completa: un renglón por cliente y los totales por antigüedad."""
    hoy = hoy or date.today()
    db = get_db()
    sql = "SELECT * FROM clientes WHERE 1 = 1"
    params = []
    if not todos:
        sql += " AND activo = 1"
    if q:
        sql += " AND (nombre LIKE ? OR documento LIKE ? OR telefono LIKE ?)"
        params += [f"%{q}%"] * 3
    clientes = db.execute(sql + " ORDER BY nombre COLLATE NOCASE", params).fetchall()

    filas = []
    rangos = [{"texto": t, "total": 0.0} for t, _, _ in RANGOS]
    for c in clientes:
        e = estado_de_cuenta(c["id"], hoy)
        if not todos and not q and abs(e["saldo"]) < 0.5:
            continue          # por defecto solo se ven los que deben (o tienen saldo a favor)
        for p in e["pendientes"]:
            for i, (_, desde, hasta) in enumerate(RANGOS):
                if desde <= p["dias"] <= hasta:
                    rangos[i]["total"] += p["pendiente"]
        filas.append({"cliente": c, "saldo": e["saldo"], "dias_mayor": e["dias_mayor"],
                      "disponible": (c["cupo"] - e["saldo"]) if c["cupo"] is not None else None,
                      "vencida": e["dias_mayor"] > DIAS_VENCIDA})
    filas.sort(key=lambda f: -f["saldo"])
    return {"filas": filas, "rangos": rangos,
            "total": sum(f["saldo"] for f in filas if f["saldo"] > 0),
            "vencida": sum(r["total"] for r in rangos[1:]),
            "n_deudores": sum(1 for f in filas if f["saldo"] > 0.5)}


def clientes_con_cartera_vencida(hoy=None):
    """Para las alertas de Inicio: clientes con una venta pendiente de más de 30 días."""
    salida = []
    for c in get_db().execute(
            "SELECT DISTINCT c.* FROM clientes c JOIN ventas v ON v.cliente_id = c.id "
            "WHERE v.forma_pago = 'credito' AND v.estado = 'completada'"):
        e = estado_de_cuenta(c["id"], hoy)
        if e["dias_mayor"] > DIAS_VENCIDA:
            salida.append({"cliente": c, "saldo": e["saldo"], "dias": e["dias_mayor"]})
    return sorted(salida, key=lambda x: -x["dias"])


# ======================================================================
# 2. ABONOS
# ======================================================================

def _numero_texto(texto):
    """'15.000' -> 15000 ; '15000' -> 15000 ; '2,5' -> 2.5 ; vacío -> 0 ; basura -> None.
    Los puntos solo se quitan cuando son de miles (grupos de 3 cifras)."""
    import re
    t = str(texto if texto is not None else "").strip() or "0"
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "")
    try:
        return round(float(t.replace(",", ".")), 2)
    except ValueError:
        return None


def _numero_abono(db):
    fila = db.execute("SELECT numero FROM cartera_abonos ORDER BY id DESC LIMIT 1").fetchone()
    n = int(fila["numero"].split("-")[1]) + 1 if fila else 1
    return f"AB-{n:04d}"


def registrar_abono(cliente_id, monto_texto, forma, observaciones=""):
    """Guarda un abono y devuelve su id. Lanza CarteraError si algo no cuadra."""
    db = get_db()
    cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if cliente is None:
        raise CarteraError("Ese cliente no existe.")
    monto = _numero_texto(monto_texto)
    if monto is None:
        raise CarteraError("El monto no es válido.")
    if monto <= 0:
        raise CarteraError("El abono debe ser mayor a cero.")
    if forma not in FORMAS_ABONO:
        raise CarteraError("Escoge cómo pagó el cliente.")
    debe = saldo(cliente_id)
    if debe <= 0.5:
        raise CarteraError(f"{cliente['nombre']} no tiene deuda pendiente.")
    if monto > debe + 0.5:
        raise CarteraError(f"{cliente['nombre']} solo debe {pesos(debe)}. No se puede abonar más.")

    caja = db.execute("SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1").fetchone()
    if forma == "efectivo" and caja is None:
        raise CarteraError("Para recibir efectivo abre la caja del POS: la plata entra ahí.")

    db.execute("BEGIN IMMEDIATE")
    try:
        numero = _numero_abono(db)
        # La plata entra a la caja (efectivo, Nequi o Davivienda) si hay una abierta
        en_caja = caja is not None and forma in FORMAS_EN_CAJA
        abono_id = db.execute(
            "INSERT INTO cartera_abonos (numero, cliente_id, fecha, monto, forma_pago, caja_id, observaciones, "
            "usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (numero, cliente_id, ahora(), monto, forma, caja["id"] if en_caja else None,
             (observaciones or "").strip() or None, g.user["id"], g.user["nombre"], ahora())).lastrowid
        if en_caja:
            db.execute(
                "INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, usuario_id, "
                "usuario_nombre, creado_en) VALUES (?,?, 'ingreso', ?,?,?,?,?,?)",
                (caja["id"], ahora(), forma, monto, f"Abono {numero} · {cliente['nombre']}",
                 g.user["id"], g.user["nombre"], ahora()))
        db.commit()
    except Exception:
        db.rollback()
        raise
    registrar("abono_cartera", "cartera_abonos", abono_id,
              f"{numero} cliente={cliente['nombre']} monto={monto} forma={forma}")
    return abono_id


# ======================================================================
# 3. PANTALLAS (solo administrador y director técnico)
# ======================================================================

@bp.route("/")
@login_required
@roles_required(*JEFES)
def index():
    q = request.args.get("q", "").strip()
    todos = request.args.get("ver") == "todos"
    return render_template("cartera/index.html", r=resumen(todos=todos, q=q), q=q, todos=todos,
                           dias_vencida=DIAS_VENCIDA)


def _leer_cliente():
    cupo_txt = (request.form.get("cupo") or "").strip()
    cupo = _numero_texto(cupo_txt) if cupo_txt else None    # vacío = sin límite
    if cupo_txt and cupo is None:
        cupo = -1    # para que la validación lo marque
    return {
        "nombre": " ".join((request.form.get("nombre") or "").split()),
        "documento": (request.form.get("documento") or "").strip() or None,
        "telefono": (request.form.get("telefono") or "").strip() or None,
        "direccion": (request.form.get("direccion") or "").strip() or None,
        "cupo": cupo,
        "observaciones": (request.form.get("observaciones") or "").strip() or None,
        "activo": 1 if request.form.get("activo", "1") == "1" else 0,
    }


def _validar_cliente(datos, cliente_id=None):
    errores = []
    if len(datos["nombre"]) < 3:
        errores.append("Escribe el nombre del cliente (mínimo 3 letras).")
    if datos["cupo"] is not None and datos["cupo"] < 0:
        errores.append("El cupo debe ser un número mayor o igual a cero (o déjalo vacío: sin límite).")
    if datos["documento"]:
        otro = get_db().execute("SELECT id, nombre FROM clientes WHERE documento = ? AND id != ?",
                                (datos["documento"], cliente_id or 0)).fetchone()
        if otro:
            errores.append(f"Ya hay un cliente con ese documento: {otro['nombre']}.")
    return errores


@bp.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
@roles_required(*JEFES)
def cliente_nuevo():
    datos = None
    if request.method == "POST":
        datos = _leer_cliente()
        errores = _validar_cliente(datos)
        if not errores:
            db = get_db()
            nuevo_id = db.execute(
                "INSERT INTO clientes (nombre, documento, telefono, direccion, cupo, observaciones, activo, "
                "creado_en) VALUES (?,?,?,?,?,?,?,?)",
                (datos["nombre"], datos["documento"], datos["telefono"], datos["direccion"], datos["cupo"],
                 datos["observaciones"], datos["activo"], ahora())).lastrowid
            db.commit()
            registrar("cliente_creado", "clientes", nuevo_id, f"{datos['nombre']} cupo={datos['cupo']}")
            flash(f"Cliente {datos['nombre']} registrado.", "ok")
            return redirect(url_for("cartera.cliente_ver", cliente_id=nuevo_id))
        for e in errores:
            flash(e, "error")
    return render_template("cartera/cliente_form.html", cliente=datos, editando=False)


@bp.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required(*JEFES)
def cliente_editar(cliente_id):
    cliente = _cliente_o_404(cliente_id)
    if request.method == "POST":
        datos = _leer_cliente()
        errores = _validar_cliente(datos, cliente_id)
        if not errores:
            db = get_db()
            db.execute(
                "UPDATE clientes SET nombre=?, documento=?, telefono=?, direccion=?, cupo=?, observaciones=?, "
                "activo=?, actualizado_en=? WHERE id=?",
                (datos["nombre"], datos["documento"], datos["telefono"], datos["direccion"], datos["cupo"],
                 datos["observaciones"], datos["activo"], ahora(), cliente_id))
            db.commit()
            registrar("cliente_editado", "clientes", cliente_id,
                      f"cupo {cliente['cupo']} -> {datos['cupo']}" if cliente["cupo"] != datos["cupo"] else "")
            flash("Cliente actualizado.", "ok")
            return redirect(url_for("cartera.cliente_ver", cliente_id=cliente_id))
        for e in errores:
            flash(e, "error")
        cliente = dict(datos, id=cliente_id)
    return render_template("cartera/cliente_form.html", cliente=cliente, editando=True)


def _cliente_o_404(cliente_id):
    c = get_db().execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if c is None:
        abort(404)
    return c


@bp.route("/clientes/<int:cliente_id>")
@login_required
@roles_required(*JEFES)
def cliente_ver(cliente_id):
    """Estado de cuenta del cliente (se puede imprimir) y formulario de abono."""
    cliente = _cliente_o_404(cliente_id)
    e = estado_de_cuenta(cliente_id)
    anulados = get_db().execute(
        "SELECT * FROM cartera_abonos WHERE cliente_id = ? AND anulado = 1 ORDER BY id DESC",
        (cliente_id,)).fetchall()
    return render_template("cartera/estado.html", c=cliente, e=e, anulados=anulados, formas=FORMAS_ABONO,
                           disponible=(cliente["cupo"] - e["saldo"]) if cliente["cupo"] is not None else None,
                           config=obtener_config(), hoy=date.today())


@bp.route("/clientes/<int:cliente_id>/abonar", methods=["POST"])
@login_required
@roles_required(*JEFES)
def abonar(cliente_id):
    try:
        abono_id = registrar_abono(cliente_id, request.form.get("monto"), request.form.get("forma_pago"),
                                   request.form.get("observaciones"))
    except CarteraError as e:
        flash(str(e), "error")
        return redirect(url_for("cartera.cliente_ver", cliente_id=cliente_id))
    flash("Abono registrado. Puedes imprimir el recibo.", "ok")
    return redirect(url_for("cartera.recibo", abono_id=abono_id))


@bp.route("/abonos/<int:abono_id>/recibo")
@login_required
def recibo(abono_id):
    """Recibo del abono en tirilla de 80 mm (como el comprobante de venta)."""
    a = get_db().execute(
        "SELECT a.*, c.nombre AS cliente_nombre, c.documento AS cliente_documento "
        "FROM cartera_abonos a JOIN clientes c ON c.id = a.cliente_id WHERE a.id = ?", (abono_id,)).fetchone()
    if a is None:
        abort(404)
    return render_template("cartera/recibo.html", a=a, saldo=saldo(a["cliente_id"]), formas=FORMAS_ABONO,
                           config=obtener_config())


@bp.route("/abonos/<int:abono_id>/anular", methods=["POST"])
@login_required
@roles_required(*JEFES)
def anular_abono(abono_id):
    """Anula un abono mal registrado. Si su plata entró a una caja que sigue
    abierta, se saca de nuevo (salida), para que el cierre cuadre."""
    db = get_db()
    a = db.execute("SELECT * FROM cartera_abonos WHERE id = ?", (abono_id,)).fetchone()
    if a is None:
        abort(404)
    motivo = (request.form.get("motivo") or "").strip()
    if a["anulado"]:
        flash("Ese abono ya estaba anulado.", "error")
    elif len(motivo) < 3:
        flash("Escribe el motivo de la anulación.", "error")
    else:
        caja = db.execute("SELECT * FROM cajas WHERE id = ? AND estado = 'abierta'", (a["caja_id"],)).fetchone() \
            if a["caja_id"] else None
        db.execute("UPDATE cartera_abonos SET anulado = 1, anulado_motivo = ?, anulado_en = ?, "
                   "anulado_por_nombre = ? WHERE id = ?", (motivo, ahora(), g.user["nombre"], abono_id))
        if caja is not None:
            db.execute(
                "INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, usuario_id, "
                "usuario_nombre, creado_en) VALUES (?,?, 'salida', ?,?,?,?,?,?)",
                (caja["id"], ahora(), a["forma_pago"], a["monto"], f"Anulación abono {a['numero']}",
                 g.user["id"], g.user["nombre"], ahora()))
        db.commit()
        registrar("abono_anulado", "cartera_abonos", abono_id, f"{a['numero']} motivo={motivo}")
        if a["caja_id"] and caja is None:
            flash(f"Abono {a['numero']} anulado. Ojo: su plata entró a una caja que ya se cerró; "
                  "revisa el cuadre de ese día.", "ok")
        else:
            flash(f"Abono {a['numero']} anulado.", "ok")
    return redirect(url_for("cartera.cliente_ver", cliente_id=a["cliente_id"]))


# ======================================================================
# 4. API PARA EL POS (cualquier usuario con sesión)
# ======================================================================

@bp.route("/api/clientes")
@login_required
def api_clientes():
    """Buscar clientes activos (nombre, documento o teléfono). Con ?con_saldo=1
    solo devuelve los que deben (para registrar un abono)."""
    q = request.args.get("q", "").strip()
    sql, params = "SELECT * FROM clientes WHERE activo = 1", []
    if q:
        sql += " AND (nombre LIKE ? OR documento LIKE ? OR telefono LIKE ?)"
        params += [f"%{q}%"] * 3
    salida = []
    for c in get_db().execute(sql + " ORDER BY nombre COLLATE NOCASE LIMIT 200", params):
        debe = saldo(c["id"])
        if request.args.get("con_saldo") and debe <= 0.5:
            continue
        salida.append({"id": c["id"], "nombre": c["nombre"], "documento": c["documento"] or "",
                       "telefono": c["telefono"] or "", "saldo": debe, "cupo": c["cupo"],
                       "disponible": (c["cupo"] - debe) if c["cupo"] is not None else None})
        if len(salida) >= 30:
            break
    return jsonify({"ok": True, "clientes": salida})


@bp.route("/api/abono", methods=["POST"])
@login_required
def api_abono():
    """Abono desde el POS (menú → Abono de cartera)."""
    cliente_id = request.form.get("cliente_id", type=int)
    try:
        abono_id = registrar_abono(cliente_id, request.form.get("monto"), request.form.get("forma_pago"),
                                   request.form.get("observaciones"))
    except CarteraError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    a = get_db().execute("SELECT numero, cliente_id FROM cartera_abonos WHERE id = ?", (abono_id,)).fetchone()
    return jsonify({"ok": True, "numero": a["numero"], "saldo": saldo(a["cliente_id"]),
                    "url_recibo": url_for("cartera.recibo", abono_id=abono_id)})
