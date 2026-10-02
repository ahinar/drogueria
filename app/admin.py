"""Administración: usuarios, bitácora y respaldos."""
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .audit import registrar
from .auth import ROLES, USUARIO_VALIDO, roles_required, validar_clave
from .backup_utils import hacer_respaldo, listar_respaldos
from .db import ahora, get_db

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/usuarios")
@roles_required("administrador")
def usuarios():
    filas = get_db().execute(
        "SELECT id, nombre, usuario, rol, activo, ultimo_ingreso FROM usuarios ORDER BY activo DESC, nombre"
    ).fetchall()
    return render_template("usuarios.html", usuarios=filas)


@bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@roles_required("administrador")
def usuario_nuevo():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        usuario = request.form.get("usuario", "").strip()
        rol = request.form.get("rol", "")
        clave = request.form.get("clave", "")
        error = None
        if not nombre:
            error = "Escribe el nombre completo."
        elif not USUARIO_VALIDO.match(usuario):
            error = "El usuario debe tener 3 a 30 caracteres (letras, números, punto, guion)."
        elif rol not in ROLES:
            error = "Escoge un rol válido."
        else:
            error = validar_clave(clave, request.form.get("confirmar", ""))
        if error:
            flash(error, "error")
        else:
            db = get_db()
            try:
                cursor = db.execute(
                    "INSERT INTO usuarios (nombre, usuario, clave_hash, rol, activo, creado_en) VALUES (?, ?, ?, ?, 1, ?)",
                    (nombre, usuario, generate_password_hash(clave), rol, ahora()),
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash("Ya existe un usuario con ese nombre de usuario.", "error")
            else:
                registrar("usuario_creado", "usuarios", cursor.lastrowid, f"usuario={usuario}, rol={rol}")
                flash(f"Usuario {usuario} creado.", "ok")
                return redirect(url_for("admin.usuarios"))
    return render_template("usuario_nuevo.html")


def _usuario_o_404(uid):
    fila = get_db().execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    if fila is None:
        abort(404)
    return fila


@bp.route("/usuarios/<int:uid>/estado", methods=["POST"])
@roles_required("administrador")
def usuario_estado(uid):
    objetivo = _usuario_o_404(uid)
    db = get_db()
    if objetivo["activo"]:
        if objetivo["id"] == g.user["id"]:
            flash("No puedes desactivar tu propio usuario.", "error")
            return redirect(url_for("admin.usuarios"))
        if objetivo["rol"] == "administrador":
            otros = db.execute(
                "SELECT COUNT(*) FROM usuarios WHERE rol = 'administrador' AND activo = 1 AND id != ?", (uid,)
            ).fetchone()[0]
            if otros == 0:
                flash("Debe quedar al menos un administrador activo.", "error")
                return redirect(url_for("admin.usuarios"))
    nuevo = 0 if objetivo["activo"] else 1
    db.execute("UPDATE usuarios SET activo = ? WHERE id = ?", (nuevo, uid))
    db.commit()
    registrar("usuario_activado" if nuevo else "usuario_desactivado", "usuarios", uid, f"usuario={objetivo['usuario']}")
    flash(f"Usuario {objetivo['usuario']} {'activado' if nuevo else 'desactivado'}.", "ok")
    return redirect(url_for("admin.usuarios"))


@bp.route("/usuarios/<int:uid>/clave", methods=["GET", "POST"])
@roles_required("administrador")
def usuario_clave(uid):
    objetivo = _usuario_o_404(uid)
    if request.method == "POST":
        error = validar_clave(request.form.get("nueva", ""), request.form.get("confirmar", ""))
        if error:
            flash(error, "error")
        else:
            db = get_db()
            db.execute("UPDATE usuarios SET clave_hash = ? WHERE id = ?", (generate_password_hash(request.form["nueva"]), uid))
            db.commit()
            registrar("clave_restablecida", "usuarios", uid, f"usuario={objetivo['usuario']}")
            flash(f"Contraseña de {objetivo['usuario']} actualizada.", "ok")
            return redirect(url_for("admin.usuarios"))
    return render_template("usuario_clave.html", objetivo=objetivo)


@bp.route("/bitacora")
@roles_required("administrador", "director_tecnico")
def bitacora():
    q = request.args.get("q", "").strip()
    pagina = max(request.args.get("pagina", 1, type=int), 1)
    por_pagina = 50
    filtro, params = "", []
    if q:
        filtro = "WHERE accion LIKE ? OR usuario_nombre LIKE ? OR detalle LIKE ?"
        params = [f"%{q}%"] * 3
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM bitacora {filtro}", params).fetchone()[0]
    filas = db.execute(
        f"SELECT * FROM bitacora {filtro} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [por_pagina, (pagina - 1) * por_pagina],
    ).fetchall()
    paginas = max((total + por_pagina - 1) // por_pagina, 1)
    return render_template("bitacora.html", filas=filas, q=q, pagina=pagina, paginas=paginas, total=total)


@bp.route("/respaldos", methods=["GET", "POST"])
@roles_required("administrador")
def respaldos():
    carpeta = current_app.config["BACKUP_DIR"]
    if request.method == "POST":
        try:
            destino, avisos = hacer_respaldo(
                current_app.config["DB_PATH"], carpeta, current_app.config["BACKUP_EXTRA_DIR"], current_app.config["BACKUP_KEEP"]
            )
        except Exception as error:
            flash(f"No se pudo crear el respaldo: {error}", "error")
        else:
            registrar("respaldo_manual", detalle=destino.name)
            flash(f"Respaldo creado: {destino.name}", "ok")
            for aviso in avisos:
                flash(aviso, "error")
        return redirect(url_for("admin.respaldos"))
    lista = []
    for ruta in listar_respaldos(carpeta):
        info = ruta.stat()
        lista.append(
            {
                "nombre": ruta.name,
                "kb": round(info.st_size / 1024),
                "fecha": datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return render_template(
        "respaldos.html", lista=lista, carpeta=str(Path(carpeta).resolve()), extra=current_app.config["BACKUP_EXTRA_DIR"]
    )
