"""Contabilidad básica: gastos, utilidades, estado de resultados (por fases)."""
from datetime import date, datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db

bp = Blueprint("contabilidad", __name__, url_prefix="/contabilidad")


# ============================================================
# Utilidades
# ============================================================

def _categorias_gasto():
    return get_db().execute(
        "SELECT id, nombre FROM catalogos "
        "WHERE tipo = 'categoria_gasto' AND activo = 1 "
        "ORDER BY nombre COLLATE NOCASE"
    ).fetchall()


def _proveedores():
    return get_db().execute(
        "SELECT id, nit, razon_social FROM proveedores WHERE activo = 1 "
        "ORDER BY razon_social COLLATE NOCASE"
    ).fetchall()


# ============================================================
# Dashboard
# ============================================================

@bp.route("/")
@login_required
@roles_required("administrador", "director_tecnico")
def index():
    db = get_db()

    hoy = date.today()
    inicio_mes = hoy.replace(day=1).isoformat()

    # Total del mes
    total_mes = db.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM gastos "
        "WHERE activo = 1 AND fecha >= ?",
        (inicio_mes,),
    ).fetchone()[0]

    n_gastos = db.execute(
        "SELECT COUNT(*) FROM gastos WHERE activo = 1 AND fecha >= ?",
        (inicio_mes,),
    ).fetchone()[0]

    # Total del mes anterior (para comparar)
    primer_dia_mes_actual = hoy.replace(day=1)
    ultimo_dia_mes_anterior = primer_dia_mes_actual - __import__("datetime").timedelta(days=1)
    primer_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)

    total_mes_anterior = db.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM gastos "
        "WHERE activo = 1 AND fecha >= ? AND fecha < ?",
        (primer_dia_mes_anterior.isoformat(), primer_dia_mes_actual.isoformat()),
    ).fetchone()[0]

    # Desglose por categoría (mes actual)
    por_categoria = db.execute(
        "SELECT c.nombre AS categoria, COUNT(*) AS n, "
        "       COALESCE(SUM(g.monto), 0) AS total "
        "FROM gastos g JOIN catalogos c ON c.id = g.categoria_id "
        "WHERE g.activo = 1 AND g.fecha >= ? "
        "GROUP BY c.nombre ORDER BY total DESC",
        (inicio_mes,),
    ).fetchall()

    # Últimos 8 gastos
    ultimos = db.execute(
        "SELECT g.*, c.nombre AS categoria_nombre "
        "FROM gastos g LEFT JOIN catalogos c ON c.id = g.categoria_id "
        "WHERE g.activo = 1 ORDER BY g.id DESC LIMIT 8"
    ).fetchall()

    # Otros ingresos del mes (plata que entra y no es venta)
    ingresos_mes, n_ingresos = db.execute(
        "SELECT COALESCE(SUM(monto), 0), COUNT(*) FROM otros_ingresos "
        "WHERE activo = 1 AND fecha >= ?", (inicio_mes,)).fetchone()

    # MESES_ES para el título
    meses = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    return render_template(
        "contabilidad/index.html",
        total_mes=total_mes,
        n_gastos=n_gastos,
        total_mes_anterior=total_mes_anterior,
        por_categoria=por_categoria,
        ultimos=ultimos,
        ingresos_mes=ingresos_mes,
        n_ingresos=n_ingresos,
        mes_actual=f"{meses[hoy.month]} {hoy.year}",
    )


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
    if datos["forma_pago"] not in ("efectivo", "nequi", "davivienda", "tarjeta", "transferencia"):
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