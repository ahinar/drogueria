"""Unidades de medida (tipo Odoo): Unidad, Sello x 10, Caja x 100, etc."""
import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .audit import registrar
from .auth import roles_required
from .db import ahora, get_db

bp = Blueprint("unidades", __name__, url_prefix="/admin/unidades")


def _obtener(uid):
    fila = get_db().execute("SELECT * FROM unidades_medida WHERE id = ?", (uid,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _todas():
    return get_db().execute(
        "SELECT u.*, r.nombre AS ref_nombre "
        "FROM unidades_medida u LEFT JOIN unidades_medida r ON r.id = u.referencia_id "
        "ORDER BY u.activo DESC, u.cantidad, u.nombre"
    ).fetchall()


@bp.route("/")
@roles_required("administrador", "director_tecnico")
def lista():
    return render_template("unidades/lista.html", filas=_todas())


def _leer_form():
    nombre = request.form.get("nombre", "").strip()
    try:
        cantidad = float(request.form.get("cantidad", "1").replace(",", "."))
    except ValueError:
        cantidad = 1
    ref = request.form.get("referencia_id", "").strip()
    referencia_id = int(ref) if ref.isdigit() else None
    return {"nombre": nombre, "cantidad": cantidad, "referencia_id": referencia_id}


def _validar(datos, editar_id=None):
    errores = []
    if not datos["nombre"]:
        errores.append("El nombre es obligatorio.")
    if datos["cantidad"] <= 0:
        errores.append("La cantidad debe ser mayor a cero.")
    if editar_id is not None and datos["referencia_id"] == editar_id:
        errores.append("La unidad no puede referenciarse a sí misma.")
    return errores


@bp.route("/nueva", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def nueva():
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO unidades_medida (nombre, cantidad, referencia_id, activo, creado_en) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (datos["nombre"], datos["cantidad"], datos["referencia_id"], ahora()),
                )
                db.commit()
                registrar("unidad_medida_creada", "unidades_medida", cur.lastrowid,
                          f"nombre={datos['nombre']} cantidad={datos['cantidad']}")
                flash(f"Unidad '{datos['nombre']}' creada.", "ok")
                return redirect(url_for("unidades.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe una unidad con ese nombre.")
        for e in errores:
            flash(e, "error")
    return render_template("unidades/form.html", item=None, referencias=_todas())


@bp.route("/<int:uid>/editar", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def editar(uid):
    item = _obtener(uid)
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos, editar_id=uid)
        if not errores:
            db = get_db()
            try:
                db.execute(
                    "UPDATE unidades_medida SET nombre=?, cantidad=?, referencia_id=?, actualizado_en=? WHERE id=?",
                    (datos["nombre"], datos["cantidad"], datos["referencia_id"], ahora(), uid),
                )
                db.commit()
                registrar("unidad_medida_editada", "unidades_medida", uid,
                          f"nombre={datos['nombre']}")
                flash("Unidad actualizada.", "ok")
                return redirect(url_for("unidades.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe una unidad con ese nombre.")
        for e in errores:
            flash(e, "error")
    return render_template("unidades/form.html", item=item, referencias=_todas())


@bp.route("/<int:uid>/activar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def activar(uid):
    item = _obtener(uid)
    nuevo = 0 if item["activo"] else 1
    db = get_db()
    db.execute("UPDATE unidades_medida SET activo=?, actualizado_en=? WHERE id=?",
               (nuevo, ahora(), uid))
    db.commit()
    registrar("unidad_medida_activada" if nuevo else "unidad_medida_desactivada",
              "unidades_medida", uid, f"nombre={item['nombre']}")
    flash("Unidad activada." if nuevo else "Unidad desactivada.", "ok")
    return redirect(url_for("unidades.lista"))


@bp.route("/<int:uid>/eliminar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def eliminar(uid):
    item = _obtener(uid)
    if item["nombre"] == "Unidad":
        flash("La unidad base 'Unidad' no se puede eliminar.", "error")
        return redirect(url_for("unidades.lista"))
    db = get_db()
    en_uso = db.execute("SELECT 1 FROM productos WHERE unidad_venta_id = ? LIMIT 1", (uid,)).fetchone()
    referenciada = db.execute("SELECT 1 FROM unidades_medida WHERE referencia_id = ? LIMIT 1", (uid,)).fetchone()
    if en_uso or referenciada:
        flash("No se puede eliminar: la unidad está en uso. Desactívala en su lugar.", "error")
        return redirect(url_for("unidades.lista"))
    db.execute("DELETE FROM unidades_medida WHERE id = ?", (uid,))
    db.commit()
    registrar("unidad_medida_eliminada", "unidades_medida", uid, f"nombre={item['nombre']}")
    flash("Unidad eliminada.", "ok")
    return redirect(url_for("unidades.lista"))

from flask import jsonify


@bp.route("/api/crear", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def api_crear():
    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400
    try:
        cantidad = float((request.form.get("cantidad") or "1").replace(",", "."))
    except ValueError:
        cantidad = 1
    ref = (request.form.get("referencia_id") or "").strip()
    referencia_id = int(ref) if ref.isdigit() else None

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO unidades_medida (nombre, cantidad, referencia_id, activo, creado_en) "
            "VALUES (?, ?, ?, 1, ?)",
            (nombre, cantidad, referencia_id, ahora()),
        )
        db.commit()
        registrar("unidad_medida_creada_api", "unidades_medida", cur.lastrowid,
                  f"nombre={nombre} cantidad={cantidad}")
        return jsonify({"ok": True, "id": cur.lastrowid, "nombre": nombre, "cantidad": cantidad})
    except sqlite3.IntegrityError:
        fila = db.execute(
            "SELECT id, nombre, cantidad FROM unidades_medida WHERE nombre = ?", (nombre,)
        ).fetchone()
        return jsonify({"ok": True, "id": fila["id"], "nombre": fila["nombre"],
                        "cantidad": fila["cantidad"], "existente": True})