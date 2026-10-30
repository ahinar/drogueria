"""
BANCOS: NEQUI Y DAVIVIENDA (versión 1.1.7)
=========================================

PARA QUÉ (para aprender):
    Antes el programa sabía cuánta plata había en EFECTIVO (caja del POS y caja
    menor), pero no en Nequi ni en Davivienda. Aquí se lleva el saldo de cada
    cuenta, para cuadrarlo contra lo que muestra la app del banco.

DE DÓNDE SALE CADA MOVIMIENTO (casi todo es AUTOMÁTICO):
    El programa ya guarda la "forma de pago" de casi todo. Si dice 'nequi' o
    'davivienda', esa plata entró o salió de esa cuenta:

        ENTRA                                   SALE
        - ventas del POS (y la parte de los     - gastos pagados por esa cuenta
          pagos mixtos)                         - devoluciones a clientes
        - abonos de cartera                     - pagos a proveedores
        - otros ingresos                        - salidas de la caja POS
        - entradas de la caja POS

    Por eso NO se copian datos: cada vez que se abre Bancos se SUMA todo desde el
    día de arranque (fecha_inicial = el día de la primera venta). Si se anula una
    venta o se corrige un gasto, el saldo se corrige solo.

    Lo único que se escribe a mano (tabla bancos_movimientos):
        - TRASLADOS: consignar efectivo de la caja menor, sacar plata del banco a la
          caja menor, o pasar de Nequi a Davivienda.
        - RETIRO / APORTE DEL DUEÑO: las cuentas también son personales. Lo
          personal NO es gasto de la droguería: así no daña la utilidad.

    CUADRAR: Fernando escribe el saldo que dice la app del banco. Si no coincide,
    escoge qué fue la diferencia:
        - "plata personal"   → retiro o aporte del dueño
        - "cobros del banco" → gasto "Gastos bancarios" (4×1000, cuota de manejo)
                               o, si sobra, otro ingreso "Intereses bancarios"
"""
from datetime import date, datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .formato import pesos
from . import formas_pago as fp   # versión 1.1.14: formas de pago y cuentas (con Daviplata) en un solo lugar

bp = Blueprint("bancos", __name__, url_prefix="/bancos")

# Cómo se llama cada movimiento que se escribe a mano
TIPOS_MANUALES = {
    "traslado_entrada": "Traslado (entra)",
    "traslado_salida": "Traslado (sale)",
    "aporte_dueno": "Aporte del dueño",
    "retiro_dueno": "Retiro del dueño",
}

# Lugares entre los que se puede trasladar plata
LUGARES = {"caja_menor": "Caja menor (efectivo)", **{c: fp.nombre(c) for c in fp.CLAVES_CUENTAS}}


# ---------------------------------------------------------------------------
# Leer las cuentas y sus movimientos
# ---------------------------------------------------------------------------
def cuentas(db=None):
    """Las cuentas activas (Nequi, Davivienda), cada una con su saldo de HOY."""
    db = db or get_db()
    filas = db.execute("SELECT * FROM cuentas_bancarias WHERE activa = 1 ORDER BY id").fetchall()
    return [dict(c, saldo=saldo(db, c)) for c in filas]


def cuenta_por_clave(db, clave):
    return db.execute("SELECT * FROM cuentas_bancarias WHERE clave = ?", (clave,)).fetchone()


# Cada pedazo de esta consulta saca los movimientos de UNA tabla, todos con las mismas
# columnas: fecha, entra, sale, concepto, ref (qué es) y ref_id (para abrirlo).
# Después se juntan con UNION ALL ("pegar una lista debajo de la otra").
# :c es la clave de la cuenta ('nequi' o 'davivienda').
_PARTES = [
    # 1. Ventas del POS pagadas completas por esta cuenta
    "SELECT v.fecha, v.total AS entra, 0 AS sale, 'Venta ' || v.consecutivo AS concepto, "
    "'venta' AS ref, v.id AS ref_id FROM ventas v "
    "WHERE v.estado = 'completada' AND v.forma_pago = :c",
    # 2. La parte de esta cuenta en las ventas con pago MIXTO
    "SELECT v.fecha, vp.monto, 0, 'Venta ' || v.consecutivo || ' (parte del pago mixto)', 'venta', v.id "
    "FROM venta_pagos vp JOIN ventas v ON v.id = vp.venta_id "
    "WHERE v.estado = 'completada' AND v.forma_pago = 'mixto' AND vp.forma_pago = :c",
    # 3. Abonos de cartera (fiado) que pagaron por esta cuenta
    "SELECT a.fecha, a.monto, 0, 'Abono ' || a.numero || ' · ' || COALESCE(cl.nombre, ''), 'abono', a.cliente_id "
    "FROM cartera_abonos a LEFT JOIN clientes cl ON cl.id = a.cliente_id "
    "WHERE a.anulado = 0 AND a.forma_pago = :c",
    # 4. Devoluciones: la plata que se le devolvió al cliente por esta cuenta
    "SELECT d.fecha, 0, d.total, 'Devolución ' || d.numero, 'devolucion', d.id "
    "FROM devoluciones d WHERE d.tipo = 'cliente' AND d.forma_reembolso = :c",
    # 5. Otros ingresos (comisiones, arriendos...)
    "SELECT i.fecha, i.monto, 0, 'Otro ingreso: ' || i.descripcion, 'otro_ingreso', i.id "
    "FROM otros_ingresos i WHERE i.activo = 1 AND i.forma_pago = :c",
    # 6. Gastos pagados por esta cuenta
    "SELECT gs.fecha, 0, gs.monto, 'Gasto: ' || gs.descripcion, 'gasto', gs.id "
    "FROM gastos gs WHERE gs.activo = 1 AND gs.forma_pago = :c",
    # 7. Entradas y salidas hechas a mano en la caja del POS por esta cuenta
    #    (solo las 'manual': los abonos y devoluciones ya salieron arriba)
    "SELECT m.fecha, CASE WHEN m.tipo = 'ingreso' THEN m.monto ELSE 0 END, "
    "CASE WHEN m.tipo = 'salida' THEN m.monto ELSE 0 END, 'Caja POS: ' || COALESCE(m.motivo, 'movimiento'), "
    "'caja', m.caja_id FROM caja_movimientos m WHERE m.origen = 'manual' AND m.forma_pago = :c",
    # 8. Pagos a proveedores hechos desde esta cuenta (app/cuentas_pagar.py)
    "SELECT p.fecha, 0, p.monto, 'Pago a ' || pr.razon_social || ' · factura ' || "
    "COALESCE(r.factura_numero, r.remision_numero, r.numero), 'pago_proveedor', p.recepcion_id "
    "FROM pagos_proveedores p JOIN proveedores pr ON pr.id = p.proveedor_id "
    "JOIN recepciones r ON r.id = p.recepcion_id WHERE p.anulado = 0 AND p.origen = :c",
    # 9. Lo escrito a mano en Bancos: traslados y plata del dueño
    "SELECT b.fecha, CASE WHEN b.tipo IN ('traslado_entrada', 'aporte_dueno') THEN b.monto ELSE 0 END, "
    "CASE WHEN b.tipo IN ('traslado_salida', 'retiro_dueno') THEN b.monto ELSE 0 END, "
    "CASE b.tipo WHEN 'traslado_entrada' THEN 'Traslado (entra)' WHEN 'traslado_salida' THEN 'Traslado (sale)' "
    "WHEN 'aporte_dueno' THEN 'Aporte del dueño' ELSE 'Retiro del dueño' END "
    "|| COALESCE(': ' || b.descripcion, ''), 'banco', b.id "
    "FROM bancos_movimientos b JOIN cuentas_bancarias cb ON cb.id = b.cuenta_id "
    "WHERE b.anulado = 0 AND cb.clave = :c",
]
_UNION = " UNION ALL ".join(_PARTES)


def movimientos(db, cuenta, desde=None, hasta=None):
    """Lista de movimientos de una cuenta (lo más viejo primero).

    desde / hasta: fechas 'AAAA-MM-DD' (hasta = sin incluir ese día). Nunca antes
    de la fecha de arranque de la cuenta.
    """
    desde = max(desde or cuenta["fecha_inicial"], cuenta["fecha_inicial"])
    sql = f"SELECT * FROM ({_UNION}) WHERE fecha >= :desde"
    params = {"c": cuenta["clave"], "desde": desde}
    if hasta:
        sql += " AND fecha < :hasta"
        params["hasta"] = hasta
    return [dict(f) for f in db.execute(sql + " ORDER BY fecha, ref_id", params).fetchall()]


def ultimos(db, cuenta, n=6):
    """Los n movimientos más recientes de una cuenta (el más nuevo primero)."""
    return [dict(f) for f in db.execute(
        f"SELECT * FROM ({_UNION}) WHERE fecha >= :desde ORDER BY fecha DESC, ref_id DESC LIMIT :n",
        {"c": cuenta["clave"], "desde": cuenta["fecha_inicial"], "n": n}).fetchall()]


def saldo(db, cuenta, hasta=None):
    """Saldo de una cuenta: lo que había al arrancar + lo que entró − lo que salió.

    hasta = 'AAAA-MM-DD' para el saldo ANTES de ese día (sin hasta: el saldo de hoy).
    """
    sql = f"SELECT COALESCE(SUM(entra), 0) - COALESCE(SUM(sale), 0) FROM ({_UNION}) WHERE fecha >= :desde"
    params = {"c": cuenta["clave"], "desde": cuenta["fecha_inicial"]}
    if hasta:
        sql += " AND fecha < :hasta"
        params["hasta"] = hasta
    return float(cuenta["saldo_inicial"] or 0) + float(db.execute(sql, params).fetchone()[0] or 0)


def transferencias_sin_cuenta(db):
    """Gastos, ingresos y abonos con forma de pago 'Transferencia' (sin decir a qué cuenta).

    Esos no pueden sumarse a Nequi ni a Davivienda: se avisa para corregirlos.
    """
    inicio = db.execute("SELECT MIN(fecha_inicial) FROM cuentas_bancarias").fetchone()[0] or "0000"
    fila = db.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(monto), 0) total FROM ("
        " SELECT monto FROM gastos WHERE activo = 1 AND forma_pago = 'transferencia' AND fecha >= :d"
        " UNION ALL SELECT monto FROM otros_ingresos WHERE activo = 1 AND forma_pago = 'transferencia' AND fecha >= :d"
        " UNION ALL SELECT monto FROM cartera_abonos WHERE anulado = 0 AND forma_pago = 'transferencia' AND fecha >= :d)",
        {"d": inicio}).fetchone()
    return {"n": fila["n"], "total": fila["total"]}


# ---------------------------------------------------------------------------
# Ayudas para guardar
# ---------------------------------------------------------------------------
def fecha_de_form(texto):
    """Fecha escrita en el formulario ('AAAA-MM-DD') → 'AAAA-MM-DD HH:MM:SS'.

    Vacía u hoy → la hora de ahora. Un día anterior → a mediodía de ese día.
    Devuelve None si está mal escrita o es del futuro.
    """
    texto = (texto or "").strip()
    if not texto or texto == date.today().isoformat():
        return ahora()
    try:
        dia = datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return None
    if dia > date.today():
        return None
    return f"{dia.isoformat()} 12:00:00"


def monto_de_form(texto):
    """'150.000' o '150000,50' → 150000.0 (None si no es un número mayor a cero)."""
    texto = (texto or "").strip().replace("$", "").replace(" ", "")
    if "," in texto:                         # 150.000,50 → 150000.50
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") >= 1 and len(texto.split(".")[-1]) == 3:
        texto = texto.replace(".", "")       # 150.000 → 150000 (punto de miles)
    try:
        valor = float(texto)
    except ValueError:
        return None
    return valor if valor > 0 else None


def _mov_banco(db, cuenta, tipo, monto, fecha, descripcion, traslado_ref=None, caja_menor_mov_id=None):
    """Guarda un movimiento escrito a mano en una cuenta. Devuelve su id."""
    return db.execute(
        "INSERT INTO bancos_movimientos (cuenta_id, fecha, tipo, monto, descripcion, traslado_ref, "
        "caja_menor_mov_id, usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cuenta["id"], fecha, tipo, monto, descripcion, traslado_ref, caja_menor_mov_id,
         g.user["id"], g.user["nombre"], ahora())).lastrowid


def _mov_caja_menor(db, tipo, monto, fecha, motivo):
    """Movimiento en la caja menor con la fecha escogida (no siempre es hoy)."""
    return db.execute(
        "INSERT INTO caja_menor_movimientos (fecha, tipo, monto, motivo, usuario_id, usuario_nombre, creado_en) "
        "VALUES (?,?,?,?,?,?,?)", (fecha, tipo, monto, motivo, g.user["id"], g.user["nombre"], ahora())).lastrowid


def _volver(clave=None):
    destino = request.form.get("volver")
    if destino == "cuenta" and clave:
        return redirect(url_for("bancos.cuenta", clave=clave))
    return redirect(url_for("bancos.index"))


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@roles_required("administrador", "director_tecnico")
def index():
    """Resumen: saldo de cada cuenta + caja menor y los formularios de traslado."""
    from .caja_menor import saldo_actual
    db = get_db()
    lista = cuentas(db)
    mes_ini = date.today().replace(day=1).isoformat()
    for c in lista:
        del_mes = movimientos(db, c, desde=mes_ini)
        c["entra_mes"] = sum(m["entra"] for m in del_mes)
        c["sale_mes"] = sum(m["sale"] for m in del_mes)
        c["ultimos"] = ultimos(db, c)
    caja_menor = saldo_actual(db)
    return render_template(
        "bancos/index.html", cuentas=lista, caja_menor=caja_menor,
        total=caja_menor + sum(c["saldo"] for c in lista), lugares=LUGARES,
        sin_cuenta=transferencias_sin_cuenta(db), hoy=date.today().isoformat())


@bp.route("/<clave>")
@login_required
@roles_required("administrador", "director_tecnico")
def cuenta(clave):
    """El "extracto" de una cuenta: movimientos del mes con el saldo después de cada uno."""
    db = get_db()
    c = cuenta_por_clave(db, clave)
    if c is None:
        abort(404)
    c = dict(c)
    mes = request.args.get("mes", date.today().strftime("%Y-%m"))
    # Meses desde que arrancó la cuenta hasta hoy (para escoger)
    meses = []
    a, m = int(c["fecha_inicial"][:4]), int(c["fecha_inicial"][5:7])
    hoy = date.today()
    while (a, m) <= (hoy.year, hoy.month):
        meses.append(f"{a:04d}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    meses.reverse()
    if mes == "todo":
        desde, hasta = None, None
    else:
        try:
            a, m = int(mes[:4]), int(mes[5:7])
            desde = f"{a:04d}-{m:02d}-01"
            hasta = f"{a + 1:04d}-01-01" if m == 12 else f"{a:04d}-{m + 1:02d}-01"
        except ValueError:
            abort(404)
    # Saldo al empezar el período: lo de antes. Después se va sumando fila por fila.
    inicial = saldo(db, c, hasta=desde) if desde and desde > c["fecha_inicial"] else float(c["saldo_inicial"] or 0)
    filas = movimientos(db, c, desde=desde, hasta=hasta)
    corrido = inicial
    for f in filas:
        corrido += f["entra"] - f["sale"]
        f["saldo"] = corrido
    c["saldo"] = saldo(db, c)
    return render_template("bancos/cuenta.html", c=c, filas=list(reversed(filas)), inicial=inicial,
                           final=corrido, mes=mes, meses=meses, hoy=date.today().isoformat(),
                           entra=sum(f["entra"] for f in filas), sale=sum(f["sale"] for f in filas))


@bp.route("/<clave>/arranque", methods=["POST"])
@login_required
@roles_required("administrador")
def arranque(clave):
    """Saldo inicial y fecha de arranque de una cuenta."""
    db = get_db()
    c = cuenta_por_clave(db, clave)
    if c is None:
        abort(404)
    texto = (request.form.get("saldo_inicial") or "0").strip()
    valor = 0.0 if texto in ("", "0") else monto_de_form(texto.lstrip("-"))
    if valor is None:
        flash("Escribe el saldo inicial como un número (ej. 250000).", "error")
        return redirect(url_for("bancos.cuenta", clave=clave))
    if texto.startswith("-"):
        valor = -valor                       # una cuenta puede arrancar en rojo (sobregiro)
    fecha = (request.form.get("fecha_inicial") or c["fecha_inicial"]).strip()
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        flash("La fecha de arranque no es válida.", "error")
        return redirect(url_for("bancos.cuenta", clave=clave))
    db.execute("UPDATE cuentas_bancarias SET saldo_inicial = ?, fecha_inicial = ?, actualizado_en = ? WHERE id = ?",
               (valor, fecha, ahora(), c["id"]))
    db.commit()
    registrar("banco_arranque", "cuentas_bancarias", c["id"], f"{c['nombre']} saldo_inicial={valor} desde={fecha}")
    flash(f"{c['nombre']}: arranca el {fecha} con {pesos(valor)}.", "ok")
    return redirect(url_for("bancos.cuenta", clave=clave))


@bp.route("/traslado", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def traslado():
    """Mover plata: caja menor ↔ banco, o de un banco al otro."""
    db = get_db()
    origen, destino = request.form.get("origen"), request.form.get("destino")
    monto = monto_de_form(request.form.get("monto"))
    fecha = fecha_de_form(request.form.get("fecha"))
    nota = (request.form.get("descripcion") or "").strip() or None
    if origen not in LUGARES or destino not in LUGARES or origen == destino:
        flash("Escoge de dónde sale y a dónde llega la plata (deben ser distintos).", "error")
        return _volver(origen)
    if monto is None or fecha is None:
        flash("Revisa el valor y la fecha del traslado.", "error")
        return _volver(origen)
    texto = f"{LUGARES[origen]} → {LUGARES[destino]}" + (f" · {nota}" if nota else "")
    ref = f"T-{ahora().replace(' ', 'T')}-{g.user['id']}"     # une las dos partes del traslado
    cm_id = None
    if "caja_menor" in (origen, destino):
        cm_id = _mov_caja_menor(db, "a_banco" if origen == "caja_menor" else "de_banco", monto, fecha, texto)
    for lado, tipo in ((origen, "traslado_salida"), (destino, "traslado_entrada")):
        if lado != "caja_menor":
            _mov_banco(db, cuenta_por_clave(db, lado), tipo, monto, fecha, texto, ref, cm_id)
    db.commit()
    registrar("banco_traslado", "bancos_movimientos", None, f"{texto} monto={monto}")
    flash(f"Traslado registrado: {pesos(monto)} de {LUGARES[origen]} a {LUGARES[destino]}.", "ok")
    return _volver(origen if origen != "caja_menor" else destino)


@bp.route("/dueno", methods=["POST"])
@login_required
@roles_required("administrador")
def dueno():
    """Plata personal: el dueño saca (retiro) o mete (aporte) plata de/a la cuenta."""
    db = get_db()
    clave = request.form.get("cuenta", "")
    c = cuenta_por_clave(db, clave)
    if c is None:
        abort(404)
    tipo = request.form.get("tipo")
    monto = monto_de_form(request.form.get("monto"))
    fecha = fecha_de_form(request.form.get("fecha"))
    nota = (request.form.get("descripcion") or "").strip() or None
    if tipo not in ("retiro_dueno", "aporte_dueno") or monto is None or fecha is None:
        flash("Revisa el tipo, el valor y la fecha.", "error")
        return _volver(clave)
    _mov_banco(db, c, tipo, monto, fecha, nota)
    db.commit()
    registrar(f"banco_{tipo}", "bancos_movimientos", None, f"{c['nombre']} monto={monto} {nota or ''}")
    flash(f"{TIPOS_MANUALES[tipo]} registrado en {c['nombre']}: {pesos(monto)}.", "ok")
    return _volver(clave)


@bp.route("/cuadrar", methods=["POST"])
@login_required
@roles_required("administrador")
def cuadrar():
    """Comparar con la app del banco y registrar la diferencia como Fernando diga."""
    from .cajas import _categoria                     # busca (o crea) una categoría por nombre
    db = get_db()
    clave = request.form.get("cuenta", "")
    c = cuenta_por_clave(db, clave)
    if c is None:
        abort(404)
    texto = (request.form.get("saldo_app") or "").strip()
    real = 0.0 if texto in ("0", "$0") else monto_de_form(texto.lstrip("-"))
    if real is None:
        flash("Escribe el saldo que muestra la app del banco.", "error")
        return _volver(clave)
    if texto.startswith("-"):
        real = -real
    programa = saldo(db, c)
    diferencia = round(real - programa, 2)
    if abs(diferencia) < 1:
        flash(f"✔ {c['nombre']} cuadra: {pesos(real)}.", "ok")
        return _volver(clave)
    explicacion = request.form.get("explicacion")
    fecha = ahora()
    if explicacion == "dueno":
        tipo = "aporte_dueno" if diferencia > 0 else "retiro_dueno"
        _mov_banco(db, c, tipo, abs(diferencia), fecha, "Cuadre con la app del banco")
        que = TIPOS_MANUALES[tipo]
    elif explicacion == "banco":
        if diferencia < 0:        # el banco cobró: gasto "Gastos bancarios"
            db.execute(
                "INSERT INTO gastos (fecha, categoria_id, descripcion, monto, forma_pago, observaciones, "
                "usuario_id, usuario_nombre, activo, creado_en, origen) VALUES (?,?,?,?,?,?,?,?,1,?, 'general')",
                (fecha, _categoria(db, "categoria_gasto", "Gastos bancarios"),
                 f"Cobros de {c['nombre']} (cuadre: 4×1000, cuota de manejo…)", -diferencia, clave,
                 "Registrado al cuadrar con la app del banco", g.user["id"], g.user["nombre"], ahora()))
            que = "gasto «Gastos bancarios»"
        else:                     # el banco abonó: otro ingreso "Intereses bancarios"
            db.execute(
                "INSERT INTO otros_ingresos (fecha, categoria_id, descripcion, monto, forma_pago, origen, "
                "observaciones, usuario_id, usuario_nombre, activo, creado_en) VALUES (?,?,?,?,?, 'ninguna', ?,?,?,1,?)",
                (fecha, _categoria(db, "categoria_ingreso", "Intereses bancarios"),
                 f"Abono de {c['nombre']} (cuadre)", diferencia, clave,
                 "Registrado al cuadrar con la app del banco", g.user["id"], g.user["nombre"], ahora()))
            que = "otro ingreso «Intereses bancarios»"
    else:
        flash(f"La diferencia es {'+' if diferencia > 0 else '−'}{pesos(abs(diferencia))}: escoge qué fue.", "error")
        return _volver(clave)
    db.commit()
    registrar("banco_cuadre", "cuentas_bancarias", c["id"],
              f"{c['nombre']} app={real} programa={programa} diferencia={diferencia} → {que}")
    flash(f"{c['nombre']} cuadrado. La diferencia ({'+' if diferencia > 0 else '−'}{pesos(abs(diferencia))}) "
          f"quedó como {que}.", "ok")
    return _volver(clave)


@bp.route("/movimiento/<int:mov_id>/anular", methods=["POST"])
@login_required
@roles_required("administrador")
def anular(mov_id):
    """Anula un movimiento escrito a mano (si es traslado, las dos partes y la caja menor)."""
    db = get_db()
    m = db.execute("SELECT b.*, cb.clave FROM bancos_movimientos b JOIN cuentas_bancarias cb ON cb.id = b.cuenta_id "
                   "WHERE b.id = ?", (mov_id,)).fetchone()
    if m is None or m["anulado"]:
        abort(404)
    ids = [m["id"]]
    if m["traslado_ref"]:
        ids = [f["id"] for f in db.execute("SELECT id FROM bancos_movimientos WHERE traslado_ref = ?",
                                           (m["traslado_ref"],))]
    db.execute(f"UPDATE bancos_movimientos SET anulado = 1, anulado_en = ?, anulado_por_nombre = ? "
               f"WHERE id IN ({','.join('?' * len(ids))})", (ahora(), g.user["nombre"], *ids))
    if m["caja_menor_mov_id"]:
        # La caja menor no se borra: se registra el movimiento contrario
        cm = db.execute("SELECT * FROM caja_menor_movimientos WHERE id = ?", (m["caja_menor_mov_id"],)).fetchone()
        if cm is not None:
            _mov_caja_menor(db, "de_banco" if cm["tipo"] == "a_banco" else "a_banco", cm["monto"], ahora(),
                            f"Anulación: {cm['motivo'] or 'traslado'}")
    db.commit()
    registrar("banco_anulado", "bancos_movimientos", mov_id, f"{m['tipo']} monto={m['monto']}")
    flash("Movimiento anulado.", "ok")
    return redirect(url_for("bancos.cuenta", clave=m["clave"]))
