"""Catálogos genéricos: categorías, formas farmacéuticas, principios, categorías de gasto, etc."""
import sqlite3

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

from .audit import registrar
from .auth import roles_required
from .db import ahora, get_db

bp = Blueprint("catalogos", __name__, url_prefix="/admin/catalogos")

# Tipos de catálogo disponibles. El orden importa (aparece así en el índice).
TIPOS = {
    "categoria":          ("Categorías de producto", "🏷️"),
    "categoria_gasto":    ("Categorías de gasto",    "💸"),
    "categoria_ingreso":  ("Categorías de otros ingresos", "💰"),
    "forma_farmaceutica": ("Formas farmacéuticas",   "💊"),
    "principio":          ("Principios activos",     "🧪"),
    "laboratorio":        ("Laboratorios",           "🏭"),
    # "uso" funciona como buscador por síntoma en el POS (ver pos.api_productos).
    # En la descripción se pueden poner palabras parecidas: "resfriado, congestión".
    "uso":                ("Usos y síntomas",        "🩺"),
    # "tipo_pago" se quitó: el POS usa formas de pago fijas (efectivo, Nequi,
    # Davivienda, tarjeta) y este catálogo no lo usaba nadie.
}


def _titulo(tipo):
    return TIPOS.get(tipo, (tipo.title(), ""))[0]


def _icono(tipo):
    return TIPOS.get(tipo, ("", "🔹"))[1]


def _validar_tipo(tipo):
    if tipo not in TIPOS:
        abort(404)


def _obtener(tipo, cat_id):
    fila = get_db().execute(
        "SELECT * FROM catalogos WHERE id = ? AND tipo = ?", (cat_id, tipo)
    ).fetchone()
    if fila is None:
        abort(404)
    return fila


@bp.route("/")
@roles_required("administrador", "director_tecnico")
def index():
    db = get_db()
    resumen = []
    for tipo, (titulo, icono) in TIPOS.items():
        total = db.execute("SELECT COUNT(*) FROM catalogos WHERE tipo = ? AND activo = 1", (tipo,)).fetchone()[0]
        resumen.append({"tipo": tipo, "titulo": titulo, "icono": icono, "total": total})
    return render_template("catalogos/index.html", resumen=resumen)


@bp.route("/<tipo>/")
@roles_required("administrador", "director_tecnico")
def lista(tipo):
    _validar_tipo(tipo)
    q = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "activos")

    sql = "SELECT * FROM catalogos WHERE tipo = ?"
    params = [tipo]
    if filtro == "activos":
        sql += " AND activo = 1"
    elif filtro == "inactivos":
        sql += " AND activo = 0"
    if q:
        sql += " AND (nombre LIKE ? OR descripcion LIKE ?)"
        like = f"%{q}%"
        params += [like, like]
    sql += " ORDER BY nombre COLLATE NOCASE"

    filas = get_db().execute(sql, params).fetchall()
    return render_template(
        "catalogos/lista.html",
        tipo=tipo, titulo=_titulo(tipo), icono=_icono(tipo),
        filas=filas, q=q, filtro=filtro,
    )


def _leer_formulario():
    return {
        "nombre": request.form.get("nombre", "").strip(),
        "descripcion": request.form.get("descripcion", "").strip() or None,
    }


@bp.route("/<tipo>/nuevo", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def nuevo(tipo):
    _validar_tipo(tipo)
    if request.method == "POST":
        datos = _leer_formulario()
        if not datos["nombre"]:
            flash("El nombre es obligatorio.", "error")
        else:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO catalogos (tipo, nombre, descripcion, activo, creado_en) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (tipo, datos["nombre"], datos["descripcion"], ahora()),
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash("Ya existe un registro con ese nombre.", "error")
                return render_template("catalogos/form.html",
                                       tipo=tipo, titulo=_titulo(tipo), icono=_icono(tipo), item=None)
            registrar(f"catalogo_{tipo}_creado", "catalogos", cur.lastrowid,
                      f"tipo={tipo} nombre={datos['nombre']}")
            flash("Registro creado.", "ok")
            return redirect(url_for("catalogos.lista", tipo=tipo))
    return render_template("catalogos/form.html",
                           tipo=tipo, titulo=_titulo(tipo), icono=_icono(tipo), item=None)


@bp.route("/<tipo>/<int:cat_id>/editar", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def editar(tipo, cat_id):
    _validar_tipo(tipo)
    item = _obtener(tipo, cat_id)
    if request.method == "POST":
        datos = _leer_formulario()
        if not datos["nombre"]:
            flash("El nombre es obligatorio.", "error")
        else:
            db = get_db()
            try:
                db.execute(
                    "UPDATE catalogos SET nombre=?, descripcion=?, actualizado_en=? "
                    "WHERE id=? AND tipo=?",
                    (datos["nombre"], datos["descripcion"], ahora(), cat_id, tipo),
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash("Ya existe otro registro con ese nombre.", "error")
                return render_template("catalogos/form.html",
                                       tipo=tipo, titulo=_titulo(tipo), icono=_icono(tipo), item=item)
            registrar(f"catalogo_{tipo}_editado", "catalogos", cat_id,
                      f"tipo={tipo} nombre={datos['nombre']}")
            flash("Registro actualizado.", "ok")
            return redirect(url_for("catalogos.lista", tipo=tipo))
    return render_template("catalogos/form.html",
                           tipo=tipo, titulo=_titulo(tipo), icono=_icono(tipo), item=item)


@bp.route("/<tipo>/<int:cat_id>/activar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def activar(tipo, cat_id):
    _validar_tipo(tipo)
    item = _obtener(tipo, cat_id)
    nuevo_estado = 0 if item["activo"] else 1
    db = get_db()
    db.execute("UPDATE catalogos SET activo=?, actualizado_en=? WHERE id=?",
               (nuevo_estado, ahora(), cat_id))
    db.commit()
    registrar(f"catalogo_{tipo}_activado" if nuevo_estado else f"catalogo_{tipo}_desactivado",
              "catalogos", cat_id, f"nombre={item['nombre']}")
    flash("Registro activado." if nuevo_estado else "Registro desactivado.", "ok")
    return redirect(url_for("catalogos.lista", tipo=tipo))


@bp.route("/<tipo>/<int:cat_id>/eliminar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def eliminar(tipo, cat_id):
    _validar_tipo(tipo)
    item = _obtener(tipo, cat_id)

    # Verificar si está en uso (categorías de gasto, por ejemplo)
    db = get_db()
    en_uso = False
    if tipo == "categoria_gasto":
        fila = db.execute("SELECT 1 FROM gastos WHERE categoria_id = ? LIMIT 1", (cat_id,)).fetchone()
        if fila:
            en_uso = True
    if tipo == "categoria_ingreso":
        fila = db.execute("SELECT 1 FROM otros_ingresos WHERE categoria_id = ? LIMIT 1", (cat_id,)).fetchone()
        if fila:
            en_uso = True

    if en_uso:
        flash("No se puede eliminar: el registro está en uso. Desactívalo en su lugar.", "error")
        return redirect(url_for("catalogos.lista", tipo=tipo))

    db.execute("DELETE FROM catalogos WHERE id=? AND tipo=?", (cat_id, tipo))
    db.commit()
    registrar(f"catalogo_{tipo}_eliminado", "catalogos", cat_id,
              f"nombre={item['nombre']}")
    flash("Registro eliminado.", "ok")
    return redirect(url_for("catalogos.lista", tipo=tipo))


def opciones(tipo: str):
    """Devuelve los registros activos de un catálogo, ordenados por nombre."""
    return get_db().execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = ? AND activo = 1 ORDER BY nombre COLLATE NOCASE",
        (tipo,),
    ).fetchall()


@bp.route("/<tipo>/api/crear", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def api_crear(tipo):
    """Crea un ítem de catálogo vía AJAX desde el formulario de productos."""
    _validar_tipo(tipo)
    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES (?, ?, 1, ?)",
            (tipo, nombre, ahora()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        fila = db.execute(
            "SELECT id, nombre FROM catalogos WHERE tipo = ? AND nombre = ?",
            (tipo, nombre),
        ).fetchone()
        return jsonify({"ok": True, "id": fila["id"], "nombre": fila["nombre"], "existente": True})
    registrar(f"catalogo_{tipo}_creado_api", "catalogos", cur.lastrowid,
              f"tipo={tipo} nombre={nombre}")
    return jsonify({"ok": True, "id": cur.lastrowid, "nombre": nombre})