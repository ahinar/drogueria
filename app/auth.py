"""Inicio de sesión, roles, protección CSRF y cuenta propia."""
import hmac
import re
import secrets
import time
from functools import wraps
from urllib.parse import urlparse

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .audit import registrar
from .db import ahora, get_db

bp = Blueprint("auth", __name__)

ROLES = {
    "administrador": "Administrador",
    "director_tecnico": "Director Técnico",
    "auxiliar": "Auxiliar",
}

CLAVE_MINIMA = 8
USUARIO_VALIDO = re.compile(r"^[A-Za-z0-9._-]{3,30}$")

# Límite de intentos fallidos de inicio de sesión (en memoria, por nombre de usuario)
MAX_INTENTOS = 5
VENTANA_SEGUNDOS = 300
_fallos = {}


def reiniciar_limites():
    _fallos.clear()


def _intentos_recientes(clave):
    ahora_ts = time.time()
    _fallos[clave] = [t for t in _fallos.get(clave, []) if ahora_ts - t < VENTANA_SEGUNDOS]
    return len(_fallos[clave])


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def validar_clave(clave, confirmar):
    if len(clave) < CLAVE_MINIMA:
        return f"La contraseña debe tener al menos {CLAVE_MINIMA} caracteres."
    if clave != confirmar:
        return "Las contraseñas no coinciden."
    return None


def hay_usuarios():
    return get_db().execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None


def es_ruta_segura(destino):
    if not destino:
        return False
    partes = urlparse(destino)
    return not partes.scheme and not partes.netloc and destino.startswith("/") and not destino.startswith("//")


def login_required(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if g.user is None:
            siguiente = request.path if request.method == "GET" and request.path != "/" else None
            return redirect(url_for("auth.login", next=siguiente))
        return vista(*args, **kwargs)

    return envoltura


def roles_required(*roles):
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login"))
            if g.user["rol"] not in roles:
                abort(403)
            return vista(*args, **kwargs)

        return envoltura

    return decorador


@bp.app_context_processor
def variables_de_plantilla():
    return {"csrf_token": csrf_token, "ROLES": ROLES}


@bp.before_app_request
def cargar_usuario():
    g.user = None
    if request.endpoint == "static":
        return
    uid = session.get("user_id")
    if uid:
        usuario = get_db().execute("SELECT * FROM usuarios WHERE id = ? AND activo = 1", (uid,)).fetchone()
        if usuario is None:
            session.clear()
        else:
            g.user = usuario


@bp.before_app_request
def verificar_csrf():
    if request.method == "POST":
        esperado = session.get("_csrf")
        recibido = request.form.get("_csrf", "")
        if not esperado or not hmac.compare_digest(esperado, recibido):
            abort(400)


@bp.route("/configurar", methods=["GET", "POST"])
def configurar():
    """Primer arranque: crea el usuario administrador. Solo funciona mientras no haya usuarios."""
    if hay_usuarios():
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        error = None
        if not nombre:
            error = "Escribe tu nombre completo."
        elif not USUARIO_VALIDO.match(usuario):
            error = "El usuario debe tener 3 a 30 caracteres (letras, números, punto, guion)."
        else:
            error = validar_clave(clave, request.form.get("confirmar", ""))
        if error:
            flash(error, "error")
        else:
            db = get_db()
            cursor = db.execute(
                "INSERT INTO usuarios (nombre, usuario, clave_hash, rol, activo, creado_en) VALUES (?, ?, ?, 'administrador', 1, ?)",
                (nombre, usuario, generate_password_hash(clave), ahora()),
            )
            db.commit()
            nuevo = db.execute("SELECT * FROM usuarios WHERE id = ?", (cursor.lastrowid,)).fetchone()
            registrar("administrador_inicial_creado", "usuarios", nuevo["id"], f"usuario={usuario}", usuario=nuevo)
            flash("Administrador creado. Ya puedes iniciar sesión.", "ok")
            return redirect(url_for("auth.login"))
    return render_template("configurar.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not hay_usuarios():
        return redirect(url_for("auth.configurar"))
    if g.user is not None:
        return redirect(url_for("main.inicio"))
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        llave = usuario.lower()
        if _intentos_recientes(llave) >= MAX_INTENTOS:
            registrar("inicio_sesion_bloqueado", detalle=f"usuario={usuario}")
            flash("Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.", "error")
        else:
            db = get_db()
            fila = db.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
            if fila is not None and fila["activo"] and check_password_hash(fila["clave_hash"], clave):
                _fallos.pop(llave, None)
                session.clear()
                session["user_id"] = fila["id"]
                session.permanent = True
                db.execute("UPDATE usuarios SET ultimo_ingreso = ? WHERE id = ?", (ahora(), fila["id"]))
                db.commit()
                registrar("inicio_sesion", "usuarios", fila["id"], usuario=fila)
                siguiente = request.args.get("next")
                return redirect(siguiente if es_ruta_segura(siguiente) else url_for("main.inicio"))
            _fallos.setdefault(llave, []).append(time.time())
            registrar("inicio_sesion_fallido", detalle=f"usuario={usuario}")
            flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user is not None:
        registrar("cierre_sesion", "usuarios", g.user["id"])
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/cuenta", methods=["GET", "POST"])
@login_required
def cuenta():
    """Cada usuario puede cambiar su propia contraseña."""
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        if not check_password_hash(g.user["clave_hash"], actual):
            flash("La contraseña actual no es correcta.", "error")
        else:
            error = validar_clave(nueva, request.form.get("confirmar", ""))
            if error:
                flash(error, "error")
            else:
                db = get_db()
                db.execute("UPDATE usuarios SET clave_hash = ? WHERE id = ?", (generate_password_hash(nueva), g.user["id"]))
                db.commit()
                registrar("clave_cambiada", "usuarios", g.user["id"])
                flash("Contraseña actualizada.", "ok")
                return redirect(url_for("auth.cuenta"))
    return render_template("cuenta.html")
