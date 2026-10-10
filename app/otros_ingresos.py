"""
OTROS INGRESOS: plata que entra a la droguería y NO es una venta.

Ejemplos: la comisión de las recargas, el arriendo de un espacio, lo que
pagan por el reciclaje, un reintegro, los intereses del banco.

Es el "espejo" de los gastos:
    - Se registran desde el POS (menú → "Otro ingreso") o desde aquí
      (Contabilidad → Otros ingresos).
    - Suman en Utilidades (estado de resultados) en su propia línea.
    - Salen en el reporte R1 Ventas, aparte de las ventas.

REGLA IMPORTANTE (para que la caja siempre cuadre):
    Un ingreso que se registró en el POS en EFECTIVO ya entró a esa caja
    (quedó como "ingreso" en caja_movimientos). Por eso aquí NO se le
    puede cambiar el monto, la forma de pago ni la fecha: si se registró
    mal, se anula y se registra de nuevo (y, si la caja sigue abierta, se
    hace una salida de efectivo por la diferencia).
"""
from datetime import date, datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db

bp = Blueprint("otros_ingresos", __name__, url_prefix="/contabilidad/ingresos")

# Formas de pago posibles (las mismas de los gastos)
FORMAS = {"efectivo": "Efectivo", "nequi": "Nequi", "davivienda": "Davivienda",
          "tarjeta": "Tarjeta", "transferencia": "Transferencia"}


def _categorias():
    """Categorías activas de otros ingresos (Administración → Catálogos)."""
    return get_db().execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'categoria_ingreso' AND activo = 1 "
        "ORDER BY nombre COLLATE NOCASE").fetchall()


def _ingreso_o_404(ingreso_id):
    fila = get_db().execute("SELECT * FROM otros_ingresos WHERE id = ?", (ingreso_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _bloqueado(ingreso):
    """True si entró en efectivo por la caja del POS (monto y forma no se tocan)."""
    return ingreso is not None and ingreso["origen"] == "pos"


# ============================================================
# LISTA (con filtros)
# ============================================================

@bp.route("/")
@login_required
@roles_required("administrador", "director_tecnico")
def lista():
    q = request.args.get("q", "").strip()
    cat_id = request.args.get("categoria", type=int)
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    filtro = request.args.get("filtro", "activos")

    # Se arma el WHERE poco a poco según los filtros que se llenaron
    cond, params = [], []
    if filtro == "activos":
        cond.append("i.activo = 1")
    elif filtro == "inactivos":
        cond.append("i.activo = 0")
    if q:
        cond.append("(i.descripcion LIKE ? OR i.comprobante LIKE ? OR c.nombre LIKE ?)")
        params += [f"%{q}%"] * 3
    if cat_id:
        cond.append("i.categoria_id = ?")
        params.append(cat_id)
    if desde:
        cond.append("i.fecha >= ?")
        params.append(desde + " 00:00:00")
    if hasta:
        cond.append("i.fecha <= ?")
        params.append(hasta + " 23:59:59")
    where = ("WHERE " + " AND ".join(cond)) if cond else ""

    filas = get_db().execute(
        "SELECT i.*, c.nombre AS categoria_nombre, cj.numero AS caja_numero "
        "FROM otros_ingresos i LEFT JOIN catalogos c ON c.id = i.categoria_id "
        "LEFT JOIN cajas cj ON cj.id = i.caja_id "
        f"{where} ORDER BY i.fecha DESC, i.id DESC LIMIT 1000", params).fetchall()

    return render_template(
        "contabilidad/ingresos_lista.html", filas=filas, categorias=_categorias(),
        q=q, cat_id=cat_id, desde=desde, hasta=hasta, filtro=filtro, formas=FORMAS,
        total_filtro=sum(f["monto"] or 0 for f in filas if f["activo"]))


# ============================================================
# NUEVO / EDITAR
# ============================================================

def _leer_form():
    try:
        monto = float((request.form.get("monto") or "0").strip().replace(",", "."))
    except ValueError:
        monto = 0.0
    cat = (request.form.get("categoria_id") or "").strip()
    return {
        "fecha": (request.form.get("fecha") or "").strip(),
        "categoria_id": int(cat) if cat.isdigit() else None,
        "descripcion": " ".join((request.form.get("descripcion") or "").split()),
        "monto": monto,
        "forma_pago": (request.form.get("forma_pago") or "efectivo").strip(),
        "comprobante": (request.form.get("comprobante") or "").strip() or None,
        "observaciones": (request.form.get("observaciones") or "").strip() or None,
    }


def _validar(datos, bloqueado=False):
    errores = []
    if not bloqueado:
        if not datos["fecha"]:
            errores.append("La fecha es obligatoria.")
        elif datos["fecha"] > date.today().isoformat():
            errores.append("La fecha no puede ser en el futuro.")
        if datos["monto"] <= 0:
            errores.append("El monto debe ser mayor a cero.")
        if datos["forma_pago"] not in FORMAS:
            errores.append("Forma de pago inválida.")
    if not datos["categoria_id"] or get_db().execute(
            "SELECT 1 FROM catalogos WHERE id = ? AND tipo = 'categoria_ingreso'",
            (datos["categoria_id"],)).fetchone() is None:
        errores.append("Escoge una categoría.")
    if len(datos["descripcion"]) < 3:
        errores.append("Escribe de qué es el ingreso (mínimo 3 letras).")
    return errores


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def nuevo():
    """Ingreso que NO pasó por la caja del POS (ej: llegó al banco)."""
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            # A la fecha escogida se le pone la hora actual (como en los gastos)
            fecha = datos["fecha"] + " " + datetime.now().strftime("%H:%M:%S")
            nuevo_id = db.execute(
                "INSERT INTO otros_ingresos (fecha, categoria_id, descripcion, monto, forma_pago, "
                "origen, comprobante, observaciones, usuario_id, usuario_nombre, activo, creado_en) "
                "VALUES (?,?,?,?,?, 'ninguna', ?,?,?,?,1,?)",
                (fecha, datos["categoria_id"], datos["descripcion"], datos["monto"],
                 datos["forma_pago"], datos["comprobante"], datos["observaciones"],
                 g.user["id"], g.user["nombre"], ahora())).lastrowid
            db.commit()
            registrar("otro_ingreso_creado", "otros_ingresos", nuevo_id,
                      f"monto={datos['monto']} · {datos['descripcion']}")
            flash("Ingreso registrado.", "ok")
            return redirect(url_for("otros_ingresos.lista"))
        for e in errores:
            flash(e, "error")
    return render_template("contabilidad/ingresos_form.html", ingreso=None, bloqueado=False,
                           categorias=_categorias(), formas=FORMAS, hoy=date.today().isoformat())


@bp.route("/<int:ingreso_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def editar(ingreso_id):
    ingreso = _ingreso_o_404(ingreso_id)
    bloqueado = _bloqueado(ingreso)
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos, bloqueado)
        if not errores:
            db = get_db()
            if bloqueado:
                # Entró por la caja: solo se corrigen los textos y la categoría
                db.execute(
                    "UPDATE otros_ingresos SET categoria_id=?, descripcion=?, comprobante=?, "
                    "observaciones=?, actualizado_en=? WHERE id=?",
                    (datos["categoria_id"], datos["descripcion"], datos["comprobante"],
                     datos["observaciones"], ahora(), ingreso_id))
            else:
                # Se conserva la hora original si no cambiaron el día
                hora = ingreso["fecha"][11:19] if len(ingreso["fecha"]) >= 19 else datetime.now().strftime("%H:%M:%S")
                db.execute(
                    "UPDATE otros_ingresos SET fecha=?, categoria_id=?, descripcion=?, monto=?, "
                    "forma_pago=?, comprobante=?, observaciones=?, actualizado_en=? WHERE id=?",
                    (datos["fecha"] + " " + hora, datos["categoria_id"], datos["descripcion"],
                     datos["monto"], datos["forma_pago"], datos["comprobante"],
                     datos["observaciones"], ahora(), ingreso_id))
            db.commit()
            registrar("otro_ingreso_editado", "otros_ingresos", ingreso_id,
                      f"monto={ingreso['monto'] if bloqueado else datos['monto']}")
            flash("Ingreso actualizado.", "ok")
            return redirect(url_for("otros_ingresos.lista"))
        for e in errores:
            flash(e, "error")
    return render_template("contabilidad/ingresos_form.html", ingreso=ingreso, bloqueado=bloqueado,
                           categorias=_categorias(), formas=FORMAS, hoy=date.today().isoformat())


@bp.route("/<int:ingreso_id>/anular", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def anular(ingreso_id):
    """Anula (o reactiva) un ingreso. No se borra: queda en la lista como anulado."""
    ingreso = _ingreso_o_404(ingreso_id)
    nuevo_estado = 0 if ingreso["activo"] else 1
    db = get_db()
    db.execute("UPDATE otros_ingresos SET activo = ?, actualizado_en = ? WHERE id = ?",
               (nuevo_estado, ahora(), ingreso_id))
    db.commit()
    registrar("otro_ingreso_reactivado" if nuevo_estado else "otro_ingreso_anulado",
              "otros_ingresos", ingreso_id)
    if not nuevo_estado and ingreso["origen"] == "pos" and ingreso["forma_pago"] == "efectivo":
        flash("Ingreso anulado. Ojo: esa plata había entrado a la caja del POS; si la caja sigue "
              "abierta y la plata no está, registra una salida de efectivo.", "ok")
    else:
        flash("Ingreso reactivado." if nuevo_estado else "Ingreso anulado.", "ok")
    return redirect(url_for("otros_ingresos.lista"))
