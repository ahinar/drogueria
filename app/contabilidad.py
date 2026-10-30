"""Contabilidad básica: gastos, utilidades, estado de resultados (por fases)."""
from datetime import date, datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from . import formas_pago as fp   # versión 1.1.14: formas de pago y cuentas (con Daviplata) en un solo lugar

bp = Blueprint("contabilidad", __name__, url_prefix="/contabilidad")


# ============================================================
# Utilidades
# ============================================================

def _categorias_gasto():
    return get_db().execute(
        "SELECT id, nombre FROM catalogos "
        "WHERE tipo = 'categoria_gasto' AND activo = 1 "
        "ORDER BY nombre COLLATE ES"
    ).fetchall()


def _proveedores():
    return get_db().execute(
        "SELECT id, nit, razon_social FROM proveedores WHERE activo = 1 "
        "ORDER BY razon_social COLLATE ES"
    ).fetchall()


# ============================================================
# Dashboard
# ============================================================

@bp.route("/")
@login_required
@roles_required("administrador", "director_tecnico")
def index():
    """DASHBOARD DE CONTABILIDAD (versión 1.1.6).

    Todo sale de datos reales del programa. Los números grandes (ingresos, costo,
    gastos y utilidad) salen del MISMO cálculo de Reportes → Utilidades
    (app/utilidades.py), para que las dos pantallas siempre coincidan.
    ?mes=AAAA-MM escoge el mes (por defecto, el actual).
    """
    from . import utilidades
    mes = request.args.get("mes", "").strip() or None
    datos = _datos_dashboard(get_db(), mes)
    return render_template("contabilidad/index.html", d=datos,
                           meses=utilidades.meses_disponibles(), mes=datos["periodo"]["mes"])


def _datos_dashboard(db, mes=None):
    """Arma todo lo que muestra el dashboard. Cada parte está explicada abajo."""
    from datetime import timedelta
    from . import cartera, cuentas_pagar, utilidades
    from .alertas import calcular_alertas
    from .cajas import resumen_sesion
    from .configuracion import obtener_config

    per = utilidades.periodos(mes)
    desde, hasta = per["actual"]["desde"], per["actual"]["hasta"]
    act = utilidades.calcular(desde, hasta)
    ant = utilidades.calcular(per["anterior"]["desde"], per["anterior"]["hasta"])
    var = utilidades.variacion
    ini, fin = desde.isoformat(), (hasta + timedelta(days=1)).isoformat()

    # ---- 1. Las cuatro tarjetas (sin IVA, igual que en Utilidades) ----
    def ingresos(r):           # ventas netas (sin IVA y sin devoluciones) + otros ingresos
        return r["ventas"] - r["devoluciones"] + r["total_otros_ingresos"]
    tarjetas = [
        {"clave": "ingresos", "titulo": "Ingresos del período", "valor": ingresos(act),
         "var": var(ingresos(act), ingresos(ant)), "detalle": f"{act['n_ventas']} venta{'' if act['n_ventas'] == 1 else 's'} · sin IVA",
         "url": url_for("reportes.ventas_ver"), "bueno_si_sube": True},
        {"clave": "costo", "titulo": "Costo de lo vendido", "valor": act["costo"],
         "var": var(act["costo"], ant["costo"]), "detalle": "lo que costó la mercancía vendida",
         "url": url_for("reportes.utilidades_ver", mes=per["mes"] or None), "bueno_si_sube": False},
        {"clave": "gastos", "titulo": "Gastos", "valor": act["total_gastos"],
         "var": var(act["total_gastos"], ant["total_gastos"]), "detalle": "arriendo, servicios, nómina…",
         "url": url_for("contabilidad.gastos_lista"), "bueno_si_sube": False},
        {"clave": "utilidad", "titulo": "Utilidad neta", "valor": act["utilidad_neta"],
         "var": var(act["utilidad_neta"], ant["utilidad_neta"]),
         # El margen solo tiene sentido si hubo ventas de verdad: con ventas casi en cero
         # daría números absurdos (ej. −699.383 %), y entonces no se muestra.
         "detalle": (f"margen {act['margen_neto']:.1f} % sobre las ventas".replace(".", ",")
                     if act["ventas"] > 0 and abs(act["margen_neto"]) <= 100 else "ingresos − costo − gastos"),
         "url": url_for("reportes.utilidades_ver", mes=per["mes"] or None), "bueno_si_sube": True},
    ]

    # ---- 2. Flujo de caja por día: plata que ENTRA y que SALE ----
    # Entra: ventas cobradas (no a crédito), abonos de cartera y otros ingresos.
    # Sale: gastos. (Las compras a proveedores van aparte, en "Compras del período".)
    dias = {}
    d = desde
    while d <= hasta:
        dias[d.isoformat()] = {"entradas": 0.0, "salidas": 0.0}
        d += timedelta(days=1)
    consultas_entrada = (
        "SELECT substr(fecha, 1, 10) AS dia, SUM(total) AS t FROM ventas "
        "WHERE estado = 'completada' AND forma_pago <> 'credito' AND fecha >= ? AND fecha < ? GROUP BY dia",
        "SELECT substr(fecha, 1, 10) AS dia, SUM(monto) AS t FROM cartera_abonos "
        "WHERE anulado = 0 AND fecha >= ? AND fecha < ? GROUP BY dia",
        "SELECT substr(fecha, 1, 10) AS dia, SUM(monto) AS t FROM otros_ingresos "
        "WHERE activo = 1 AND fecha >= ? AND fecha < ? GROUP BY dia",
    )
    for sql in consultas_entrada:
        for f in db.execute(sql, (ini, fin)):
            if f["dia"] in dias:
                dias[f["dia"]]["entradas"] += f["t"] or 0
    # Sale: gastos y (desde la versión 1.1.7) los pagos a proveedores
    for sql in ("SELECT substr(fecha, 1, 10) AS dia, SUM(monto) AS t FROM gastos "
                "WHERE activo = 1 AND fecha >= ? AND fecha < ? GROUP BY dia",
                "SELECT substr(fecha, 1, 10) AS dia, SUM(monto) AS t FROM pagos_proveedores "
                "WHERE anulado = 0 AND fecha >= ? AND fecha < ? GROUP BY dia"):
        for f in db.execute(sql, (ini, fin)):
            if f["dia"] in dias:
                dias[f["dia"]]["salidas"] += f["t"] or 0
    saldo, flujo = 0.0, []
    for dia, v in dias.items():
        saldo += v["entradas"] - v["salidas"]
        flujo.append({"dia": dia[8:10] + "/" + dia[5:7], "entradas": round(v["entradas"]),
                      "salidas": round(v["salidas"]), "saldo": round(saldo)})

    # ---- 3. Distribución de gastos por categoría (la "dona") ----
    gastos_cat = [{"categoria": c["categoria"], "total": c["total"]} for c in act["gastos"]]

    # ---- 4. Ventas vs. gastos de los últimos 6 meses ----
    meses_barras = []
    primero = desde.replace(day=1)
    for i in range(5, -1, -1):
        m_ini = primero
        for _ in range(i):
            m_ini = (m_ini - timedelta(days=1)).replace(day=1)
        m_fin = (m_ini.replace(day=28) + timedelta(days=4)).replace(day=1)
        v = db.execute("SELECT COALESCE(SUM(vl.subtotal), 0) FROM venta_lineas vl JOIN ventas v ON v.id = vl.venta_id "
                       "WHERE v.estado = 'completada' AND v.fecha >= ? AND v.fecha < ?",
                       (m_ini.isoformat(), m_fin.isoformat())).fetchone()[0]
        g_ = db.execute("SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE activo = 1 AND fecha >= ? AND fecha < ?",
                        (m_ini.isoformat(), m_fin.isoformat())).fetchone()[0]
        meses_barras.append({"mes": utilidades.MESES[m_ini.month][:3].capitalize(), "ventas": round(v), "gastos": round(g_)})

    # ---- 5. Últimos movimientos (ventas, gastos, otros ingresos y abonos) ----
    movimientos = [dict(f) for f in db.execute(
        "SELECT * FROM ("
        "  SELECT fecha, 'Venta ' || consecutivo AS concepto, 'Ventas' AS categoria, 'ingreso' AS tipo, total AS valor, "
        "         forma_pago AS detalle FROM ventas WHERE estado = 'completada' "
        "  UNION ALL SELECT g.fecha, g.descripcion, COALESCE(c.nombre, 'Gasto'), 'egreso', g.monto, g.forma_pago "
        "         FROM gastos g LEFT JOIN catalogos c ON c.id = g.categoria_id WHERE g.activo = 1 "
        "  UNION ALL SELECT i.fecha, i.descripcion, COALESCE(c.nombre, 'Otro ingreso'), 'ingreso', i.monto, i.forma_pago "
        "         FROM otros_ingresos i LEFT JOIN catalogos c ON c.id = i.categoria_id WHERE i.activo = 1 "
        "  UNION ALL SELECT a.fecha, 'Abono ' || a.numero || ' · ' || COALESCE(cl.nombre, ''), 'Cartera', 'ingreso', "
        "         a.monto, a.forma_pago FROM cartera_abonos a LEFT JOIN clientes cl ON cl.id = a.cliente_id "
        "         WHERE a.anulado = 0"
        "  UNION ALL SELECT pp.fecha, 'Pago a ' || pr.razon_social, 'Proveedores', 'egreso', pp.monto, pp.origen "
        "         FROM pagos_proveedores pp JOIN proveedores pr ON pr.id = pp.proveedor_id WHERE pp.anulado = 0"
        ") ORDER BY fecha DESC LIMIT 8")]

    # ---- 6. Cartera, compras del período e IVA ----
    car = cartera.resumen()
    compras = db.execute(
        "SELECT COALESCE(SUM(COALESCE(rl.costo_con_iva, rl.costo_unitario) * rl.cantidad_recibida), 0) AS total, "
        "       COUNT(DISTINCT r.id) AS n "
        "FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id "
        "WHERE rl.resultado <> 'rechazado' AND r.fecha >= ? AND r.fecha < ?", (ini, fin)).fetchone()
    declara = obtener_config().get("declara_iva") == "si"
    iva = None
    if declara:
        # IVA cobrado en ventas − IVA pagado en compras = IVA estimado a pagar (orientativo)
        pagado = db.execute(
            "SELECT COALESCE(SUM((COALESCE(rl.costo_con_iva, 0) - COALESCE(rl.costo_sin_iva, 0)) * rl.cantidad_recibida), 0) "
            "FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id "
            "WHERE rl.resultado <> 'rechazado' AND r.fecha >= ? AND r.fecha < ?", (ini, fin)).fetchone()[0]
        iva = {"cobrado": act["iva"], "pagado": pagado, "estimado": act["iva"] - pagado}

    # ---- 7. Últimas sesiones de caja (con su diferencia en color) ----
    cajas = [resumen_sesion(db, c) for c in db.execute("SELECT * FROM cajas ORDER BY abierta_en DESC, id DESC LIMIT 5").fetchall()]

    # ---- 8. Alertas que tienen que ver con plata e inventario ----
    claves = ("cxp_vencidas", "lotes_vencidos", "lotes_por_vencer", "agotados", "cartera_vencida", "caja_vieja",
              "precio_maximo")
    alertas = [a for a in calcular_alertas(g.user["rol"]) if a["clave"] in claves][:4]

    return {
        "periodo": per, "actual": act, "tarjetas": tarjetas,
        "flujo": flujo, "gastos_cat": gastos_cat, "meses_barras": meses_barras,
        "movimientos": movimientos, "cartera": car,
        "compras": {"total": compras["total"], "n": compras["n"]},
        "declara_iva": declara, "iva": iva,
        "cajas": cajas, "alertas": alertas,
        # Versión 1.1.7: lo que se les debe a proveedores y la plata en bancos + caja menor
        "cxp": cuentas_pagar.resumen(db),
        "plata": _plata_disponible(db),
    }


def _plata_disponible(db):
    """Caja menor + Nequi + Davivienda (ver app/bancos.py)."""
    from .bancos import cuentas
    from .caja_menor import saldo_actual
    lista = cuentas(db)
    cm = saldo_actual(db)
    return {"total": cm + sum(c["saldo"] for c in lista), "caja_menor": cm,
            "cuentas": [{"nombre": c["nombre"], "saldo": c["saldo"]} for c in lista]}


# ============================================================
# Sesiones de caja (versión 1.1.6)
# ============================================================

@bp.route("/cajas")
@login_required
@roles_required("administrador", "director_tecnico")
def cajas():
    """Listado de todas las veces que se abrió la caja del POS, con su cuadre.

    Filtros: ?desde=AAAA-MM-DD&hasta=AAAA-MM-DD&usuario=Nombre
    """
    from .cajas import resumen_sesion
    db = get_db()
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    usuario = request.args.get("usuario", "").strip()
    sql, params = "SELECT * FROM cajas WHERE 1 = 1", []
    if desde:
        sql += " AND abierta_en >= ?"
        params.append(desde)
    if hasta:
        sql += " AND abierta_en < date(?, '+1 day')"
        params.append(hasta)
    if usuario:
        sql += " AND (abierta_por_nombre = ? OR cerrada_por_nombre = ?)"
        params += [usuario, usuario]
    filas = [resumen_sesion(db, c) for c in db.execute(sql + " ORDER BY abierta_en DESC, id DESC LIMIT 300", params).fetchall()]
    cerradas = [f for f in filas if f["diferencia"] is not None]
    totales = {
        "ventas": sum(f["total_ventas"] for f in filas),
        "faltantes": sum(f["diferencia"] for f in cerradas if f["diferencia"] < 0),
        "sobrantes": sum(f["diferencia"] for f in cerradas if f["diferencia"] > 0),
        "por_forma": {k: sum(f["por_forma"][k] for f in filas)
                      for k in ("efectivo",) + fp.CLAVES_CUENTAS + ("tarjeta", "credito")},
    }
    totales["neto"] = totales["faltantes"] + totales["sobrantes"]
    usuarios = [r[0] for r in db.execute(
        "SELECT DISTINCT nombre FROM (SELECT abierta_por_nombre AS nombre FROM cajas "
        "UNION SELECT cerrada_por_nombre FROM cajas) WHERE nombre IS NOT NULL ORDER BY nombre COLLATE ES")]
    return render_template("contabilidad/cajas.html", filas=filas, totales=totales, usuarios=usuarios,
                           desde=desde, hasta=hasta, usuario=usuario)


@bp.route("/cajas/<int:caja_id>")
@login_required
@roles_required("administrador", "director_tecnico")
def caja_detalle(caja_id):
    """Detalle de UNA sesión de caja: cuadre, ventas del turno y movimientos de efectivo."""
    from .cajas import resumen_sesion
    db = get_db()
    caja = db.execute("SELECT * FROM cajas WHERE id = ?", (caja_id,)).fetchone()
    if caja is None:
        abort(404)
    ventas = db.execute("SELECT * FROM ventas WHERE caja_id = ? ORDER BY id", (caja_id,)).fetchall()
    return render_template("contabilidad/caja_detalle.html", r=resumen_sesion(db, caja), ventas=ventas)


# ============================================================
# Lista de gastos
# ============================================================

@bp.route("/gastos/")
@login_required
@roles_required("administrador", "director_tecnico")
def gastos_lista():
    db = get_db()
    q = request.args.get("q", "").strip()
    cat_id = request.args.get("categoria", type=int)
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    filtro = request.args.get("filtro", "activos")

    cond, params = [], []
    if filtro == "activos":
        cond.append("g.activo = 1")
    elif filtro == "inactivos":
        cond.append("g.activo = 0")

    if q:
        cond.append("(g.descripcion LIKE ? OR g.comprobante LIKE ? OR c.nombre LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]

    if cat_id:
        cond.append("g.categoria_id = ?")
        params.append(cat_id)

    if desde:
        cond.append("g.fecha >= ?")
        params.append(desde + " 00:00:00")
    if hasta:
        cond.append("g.fecha <= ?")
        params.append(hasta + " 23:59:59")

    where = ("WHERE " + " AND ".join(cond)) if cond else ""

    filas = db.execute(
        f"SELECT g.*, c.nombre AS categoria_nombre, "
        f"       p.razon_social AS proveedor_nombre "
        f"FROM gastos g "
        f"LEFT JOIN catalogos c ON c.id = g.categoria_id "
        f"LEFT JOIN proveedores p ON p.id = g.proveedor_id "
        f"{where} "
        f"ORDER BY g.fecha DESC, g.id DESC LIMIT 1000",
        params,
    ).fetchall()

    total_filtro = sum((f["monto"] or 0) for f in filas)

    return render_template(
        "contabilidad/gastos_lista.html",
        filas=filas,
        categorias=_categorias_gasto(),
        q=q,
        cat_id=cat_id,
        desde=desde,
        hasta=hasta,
        filtro=filtro,
        total_filtro=total_filtro,
    )


# ============================================================
# Nuevo / Editar gasto
# ============================================================

def _leer_form():
    def cat(campo):
        v = request.form.get(campo, "").strip()
        try:
            return int(v) if v else None
        except ValueError:
            return None

    def num(campo, defecto=0.0):
        v = request.form.get(campo, "").strip().replace(",", ".")
        try:
            return float(v) if v else defecto
        except ValueError:
            return defecto

    return {
        "fecha": request.form.get("fecha", "").strip(),
        "categoria_id": cat("categoria_id"),
        "descripcion": request.form.get("descripcion", "").strip(),
        "monto": num("monto", 0.0),
        "forma_pago": request.form.get("forma_pago", "efectivo").strip(),
        "proveedor_id": cat("proveedor_id"),
        "comprobante": request.form.get("comprobante", "").strip() or None,
        "observaciones": request.form.get("observaciones", "").strip() or None,
    }


def _validar(datos):
    errores = []
    if not datos["fecha"]:
        errores.append("La fecha es obligatoria.")
    if not datos["categoria_id"]:
        errores.append("Debes seleccionar una categoría.")
    if not datos["descripcion"]:
        errores.append("La descripción es obligatoria.")
    if datos["monto"] <= 0:
        errores.append("El monto debe ser mayor a cero.")
    if datos["forma_pago"] not in fp.FORMAS_MOVIMIENTO:
        errores.append("Forma de pago inválida.")
    return errores


@bp.route("/gastos/nuevo", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def gastos_nuevo():
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            fecha_completa = datos["fecha"] + " " + datetime.now().strftime("%H:%M:%S")
            db = get_db()
            cur = db.execute(
                "INSERT INTO gastos (fecha, categoria_id, descripcion, monto, forma_pago, "
                "proveedor_id, comprobante, observaciones, usuario_id, usuario_nombre, activo, creado_en) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                (fecha_completa, datos["categoria_id"], datos["descripcion"], datos["monto"],
                 datos["forma_pago"], datos["proveedor_id"], datos["comprobante"],
                 datos["observaciones"], g.user["id"], g.user["nombre"], ahora()),
            )
            db.commit()
            registrar("gasto_creado", "gastos", cur.lastrowid,
                      f"monto={datos['monto']} categoria={datos['categoria_id']}")
            flash("Gasto registrado.", "ok")
            return redirect(url_for("contabilidad.gastos_lista"))
        for e in errores:
            flash(e, "error")

    return render_template(
        "contabilidad/gastos_form.html",
        gasto=None,
        categorias=_categorias_gasto(),
        proveedores=_proveedores(),
        hoy=date.today().isoformat(),
    )


@bp.route("/gastos/<int:gasto_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def gastos_editar(gasto_id):
    db = get_db()
    gasto = db.execute("SELECT * FROM gastos WHERE id = ?", (gasto_id,)).fetchone()
    if gasto is None:
        abort(404)

    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            fecha_completa = datos["fecha"] + " " + datetime.now().strftime("%H:%M:%S")
            db.execute(
                "UPDATE gastos SET fecha=?, categoria_id=?, descripcion=?, monto=?, "
                "forma_pago=?, proveedor_id=?, comprobante=?, observaciones=?, actualizado_en=? "
                "WHERE id=?",
                (fecha_completa, datos["categoria_id"], datos["descripcion"], datos["monto"],
                 datos["forma_pago"], datos["proveedor_id"], datos["comprobante"],
                 datos["observaciones"], ahora(), gasto_id),
            )
            db.commit()
            registrar("gasto_editado", "gastos", gasto_id,
                      f"monto={datos['monto']}")
            flash("Gasto actualizado.", "ok")
            return redirect(url_for("contabilidad.gastos_lista"))
        for e in errores:
            flash(e, "error")

    return render_template(
        "contabilidad/gastos_form.html",
        gasto=gasto,
        categorias=_categorias_gasto(),
        proveedores=_proveedores(),
        hoy=date.today().isoformat(),
    )


@bp.route("/gastos/<int:gasto_id>/anular", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def gastos_anular(gasto_id):
    db = get_db()
    gasto = db.execute("SELECT * FROM gastos WHERE id = ?", (gasto_id,)).fetchone()
    if gasto is None:
        abort(404)

    nuevo_estado = 0 if gasto["activo"] else 1
    db.execute("UPDATE gastos SET activo = ?, actualizado_en = ? WHERE id = ?",
               (nuevo_estado, ahora(), gasto_id))
    db.commit()
    registrar("gasto_reactivado" if nuevo_estado else "gasto_anulado",
              "gastos", gasto_id)
    flash("Gasto reactivado." if nuevo_estado else "Gasto anulado.", "ok")
    return redirect(url_for("contabilidad.gastos_lista"))