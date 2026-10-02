"""Productos: CRUD con bitácora. No se borran, se desactivan."""
import sqlite3

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db

bp = Blueprint("productos", __name__, url_prefix="/productos")

IVA_TIPOS = {"excluido": "Excluido", "exento": "Exento", "gravado": "Gravado"}


def _obtener(prod_id):
    fila = get_db().execute("SELECT * FROM productos WHERE id = ?", (prod_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


@bp.route("/")
@login_required
def lista():
    q = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "activos")
    sql = "SELECT * FROM productos"
    cond, params = [], []
    if filtro == "activos":
        cond.append("activo = 1")
    elif filtro == "inactivos":
        cond.append("activo = 0")
    elif filtro == "frio":
        cond.append("activo = 1 AND cadena_frio = 1")
    elif filtro == "control":
        cond.append("activo = 1 AND control_especial = 1")
    elif filtro == "formula":
        cond.append("activo = 1 AND requiere_formula = 1")
    if q:
        cond.append("(codigo LIKE ? OR codigo_barras LIKE ? OR nombre LIKE ? OR principio_activo LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY nombre COLLATE NOCASE"
    filas = get_db().execute(sql, params).fetchall()
    return render_template("productos/lista.html", productos=filas, q=q, filtro=filtro)

def _valores_existentes():
    """Valores ya usados en productos, para autocompletar el formulario."""
    db = get_db()

    def valores(campo):
        # El campo viene solo de llamadas internas (no del usuario), por eso es seguro.
        filas = db.execute(
            "SELECT DISTINCT " + campo + " FROM productos "
            "WHERE " + campo + " IS NOT NULL AND " + campo + " != '' "
            "ORDER BY " + campo + " COLLATE NOCASE"
        ).fetchall()
        return [f[0] for f in filas]

    return {
        "principios": valores("principio_activo"),
        "concentraciones": valores("concentracion"),
        "formas": valores("forma_farmaceutica"),
        "fabricantes": valores("fabricante"),
    }

def _leer_formulario():
    def num(campo, defecto=0.0):
        v = request.form.get(campo, "").strip().replace(",", ".")
        try:
            return float(v) if v else defecto
        except ValueError:
            return defecto

    def ent(campo, defecto=0):
        v = request.form.get(campo, "").strip()
        try:
            return int(v) if v else defecto
        except ValueError:
            return defecto

    return {
        "codigo": request.form.get("codigo", "").strip(),
        "codigo_barras": request.form.get("codigo_barras", "").strip() or None,
        "nombre": request.form.get("nombre", "").strip(),
        "principio_activo": request.form.get("principio_activo", "").strip() or None,
        "concentracion": request.form.get("concentracion", "").strip() or None,
        "forma_farmaceutica": request.form.get("forma_farmaceutica", "").strip() or None,
        "registro_sanitario": request.form.get("registro_sanitario", "").strip() or None,
        "registro_vence": request.form.get("registro_vence", "").strip() or None,
        "fabricante": request.form.get("fabricante", "").strip() or None,
        "unidad": request.form.get("unidad", "").strip() or None,
        "iva_tipo": (iva_tipo := request.form.get("iva_tipo", "gravado")),
        "iva_tarifa": 0.0 if iva_tipo in ("excluido", "exento") else num("iva_tarifa", 19.0),
        "precio_venta": num("precio_venta", 0.0),
        "precio_maximo": num("precio_maximo") or None,
        "stock_minimo": ent("stock_minimo", 0),
        "requiere_formula": 1 if request.form.get("requiere_formula") else 0,
        "cadena_frio": 1 if request.form.get("cadena_frio") else 0,
        "control_especial": 1 if request.form.get("control_especial") else 0,
        "observaciones": request.form.get("observaciones", "").strip() or None,
    }


def _validar(datos):
    errores = []
    if not datos["codigo"]:
        errores.append("El código interno es obligatorio.")
    if not datos["nombre"]:
        errores.append("El nombre es obligatorio.")
    if datos["iva_tipo"] not in IVA_TIPOS:
        errores.append("Tipo de IVA no válido.")
    if datos["precio_venta"] < 0:
        errores.append("El precio de venta no puede ser negativo.")
    if datos["control_especial"] and not datos["registro_sanitario"]:
        errores.append("Un producto de control especial debe tener registro sanitario INVIMA.")
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
                    "INSERT INTO productos (codigo, codigo_barras, nombre, principio_activo, concentracion, "
                    "forma_farmaceutica, registro_sanitario, registro_vence, fabricante, unidad, iva_tipo, "
                    "iva_tarifa, precio_venta, precio_maximo, stock_minimo, requiere_formula, cadena_frio, "
                    "control_especial, observaciones, activo, creado_en) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                    (datos["codigo"], datos["codigo_barras"], datos["nombre"], datos["principio_activo"],
                     datos["concentracion"], datos["forma_farmaceutica"], datos["registro_sanitario"],
                     datos["registro_vence"], datos["fabricante"], datos["unidad"], datos["iva_tipo"],
                     datos["iva_tarifa"], datos["precio_venta"], datos["precio_maximo"],
                     datos["stock_minimo"], datos["requiere_formula"], datos["cadena_frio"],
                     datos["control_especial"], datos["observaciones"], ahora()),
                )
                db.commit()
                registrar("producto_creado", "productos", cur.lastrowid,
                          f"código={datos['codigo']} nombre={datos['nombre']}")
                flash("Producto creado.", "ok")
                return redirect(url_for("productos.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe un producto con ese código.")
        for e in errores:
            flash(e, "error")
    return render_template("productos/form.html", producto=None, iva_tipos=IVA_TIPOS,
                           valores=_valores_existentes())


@bp.route("/<int:prod_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def editar(prod_id):
    producto = _obtener(prod_id)
    if request.method == "POST":
        datos = _leer_formulario()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            try:
                db.execute(
                    "UPDATE productos SET codigo=?, codigo_barras=?, nombre=?, principio_activo=?, "
                    "concentracion=?, forma_farmaceutica=?, registro_sanitario=?, registro_vence=?, "
                    "fabricante=?, unidad=?, iva_tipo=?, iva_tarifa=?, precio_venta=?, precio_maximo=?, "
                    "stock_minimo=?, requiere_formula=?, cadena_frio=?, control_especial=?, observaciones=?, "
                    "actualizado_en=? WHERE id=?",
                    (datos["codigo"], datos["codigo_barras"], datos["nombre"], datos["principio_activo"],
                     datos["concentracion"], datos["forma_farmaceutica"], datos["registro_sanitario"],
                     datos["registro_vence"], datos["fabricante"], datos["unidad"], datos["iva_tipo"],
                     datos["iva_tarifa"], datos["precio_venta"], datos["precio_maximo"],
                     datos["stock_minimo"], datos["requiere_formula"], datos["cadena_frio"],
                     datos["control_especial"], datos["observaciones"], ahora(), prod_id),
                )
                db.commit()
                registrar("producto_editado", "productos", prod_id, f"código={datos['codigo']}")
                flash("Producto actualizado.", "ok")
                return redirect(url_for("productos.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe otro producto con ese código.")
        for e in errores:
            flash(e, "error")
    return render_template("productos/form.html", producto=producto, iva_tipos=IVA_TIPOS,
                           valores=_valores_existentes())


@bp.route("/<int:prod_id>/activar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def activar(prod_id):
    producto = _obtener(prod_id)
    nuevo_estado = 0 if producto["activo"] else 1
    db = get_db()
    db.execute("UPDATE productos SET activo=?, actualizado_en=? WHERE id=?",
               (nuevo_estado, ahora(), prod_id))
    db.commit()
    registrar("producto_activado" if nuevo_estado else "producto_desactivado",
              "productos", prod_id)
    flash("Producto activado." if nuevo_estado else "Producto desactivado.", "ok")
    return redirect(url_for("productos.lista"))