"""Proveedores: CRUD con bitácora. No se borran, se desactivan."""
import sqlite3

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db

bp = Blueprint("proveedores", __name__, url_prefix="/proveedores")


def _obtener(prov_id):
    fila = get_db().execute("SELECT * FROM proveedores WHERE id = ?", (prov_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


@bp.route("/")
@login_required
def lista():
    q = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "activos")
    sql = "SELECT * FROM proveedores"
    cond = []
    params = []
    if filtro == "activos":
        cond.append("activo = 1")
    elif filtro == "inactivos":
        cond.append("activo = 0")
    if q:
        cond.append("(nit LIKE ? OR razon_social LIKE ? OR nombre_comercial LIKE ? OR contacto LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY razon_social COLLATE NOCASE"
    filas = get_db().execute(sql, params).fetchall()
    return render_template("proveedores/lista.html", proveedores=filas, q=q, filtro=filtro)


def _leer_formulario():
    return {
        "nit": request.form.get("nit", "").strip(),
        "razon_social": request.form.get("razon_social", "").strip(),
        "nombre_comercial": request.form.get("nombre_comercial", "").strip() or None,
        "contacto": request.form.get("contacto", "").strip() or None,
        "telefono": request.form.get("telefono", "").strip() or None,
        "correo": request.form.get("correo", "").strip() or None,
        "direccion": request.form.get("direccion", "").strip() or None,
        "ciudad": request.form.get("ciudad", "").strip() or None,
        "concepto_sanitario": request.form.get("concepto_sanitario", "").strip() or None,
        "concepto_vence": request.form.get("concepto_vence", "").strip() or None,
        "certificaciones": request.form.get("certificaciones", "").strip() or None,
        "observaciones": request.form.get("observaciones", "").strip() or None,
    }


def _validar(datos):
    errores = []
    if not datos["nit"]:
        errores.append("El NIT es obligatorio.")
    if not datos["razon_social"]:
        errores.append("La razón social es obligatoria.")
    return errores


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def nuevo():
    if request.method == "POST":
        datos = _leer_formulario()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO proveedores (nit, razon_social, nombre_comercial, contacto, telefono, correo, "
                    "direccion, ciudad, concepto_sanitario, concepto_vence, certificaciones, observaciones, "
                    "activo, creado_en) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 1, ?)",
                    (datos["nit"], datos["razon_social"], datos["nombre_comercial"], datos["contacto"],
                     datos["telefono"], datos["correo"], datos["direccion"], datos["ciudad"],
                     datos["concepto_sanitario"], datos["concepto_vence"], datos["certificaciones"],
                     datos["observaciones"], ahora()),
                )
                db.commit()
                registrar("proveedor_creado", "proveedores", cur.lastrowid,
                          f"NIT={datos['nit']} razón={datos['razon_social']}")
                flash("Proveedor creado.", "ok")
                return redirect(url_for("proveedores.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe un proveedor con ese NIT.")
        for e in errores:
            flash(e, "error")
    return render_template("proveedores/form.html", proveedor=None)


@bp.route("/<int:prov_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def editar(prov_id):
    proveedor = _obtener(prov_id)
    if request.method == "POST":
        datos = _leer_formulario()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            try:
                db.execute(
                    "UPDATE proveedores SET nit=?, razon_social=?, nombre_comercial=?, contacto=?, telefono=?, "
                    "correo=?, direccion=?, ciudad=?, concepto_sanitario=?, concepto_vence=?, certificaciones=?, "
                    "observaciones=?, actualizado_en=? WHERE id=?",
                    (datos["nit"], datos["razon_social"], datos["nombre_comercial"], datos["contacto"],
                     datos["telefono"], datos["correo"], datos["direccion"], datos["ciudad"],
                     datos["concepto_sanitario"], datos["concepto_vence"], datos["certificaciones"],
                     datos["observaciones"], ahora(), prov_id),
                )
                db.commit()
                registrar("proveedor_editado", "proveedores", prov_id, f"NIT={datos['nit']}")
                flash("Proveedor actualizado.", "ok")
                return redirect(url_for("proveedores.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe otro proveedor con ese NIT.")
        for e in errores:
            flash(e, "error")
    return render_template("proveedores/form.html", proveedor=proveedor)


@bp.route("/<int:prov_id>/activar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def activar(prov_id):
    proveedor = _obtener(prov_id)
    nuevo_estado = 0 if proveedor["activo"] else 1
    db = get_db()
    db.execute("UPDATE proveedores SET activo=?, actualizado_en=? WHERE id=?",
               (nuevo_estado, ahora(), prov_id))
    db.commit()
    registrar("proveedor_activado" if nuevo_estado else "proveedor_desactivado",
              "proveedores", prov_id)
    flash("Proveedor activado." if nuevo_estado else "Proveedor desactivado.", "ok")
    return redirect(url_for("proveedores.lista"))