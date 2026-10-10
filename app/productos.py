"""Productos: CRUD con bitácora, catálogos, categorías múltiples, usos y presentaciones."""
import sqlite3

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from .audit import registrar
from .auth import login_required, roles_required
from .catalogos import opciones as cat_opciones
from .db import ahora, get_db
from . import presentaciones as pres
from .utils_imagenes import guardar_imagen, eliminar_imagen

bp = Blueprint("productos", __name__, url_prefix="/productos")

IVA_TIPOS = {"excluido": "Excluido", "exento": "Exento", "gravado": "Gravado"}


def _siguiente_codigo():
    db = get_db()
    filas = db.execute(
        "SELECT codigo FROM productos WHERE codigo LIKE 'P%' "
        "ORDER BY CAST(SUBSTR(codigo, 2) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    if filas is None:
        return "P00001"
    try:
        n = int(filas["codigo"][1:]) + 1
    except ValueError:
        return "P00001"
    return f"P{n:05d}"


def _obtener(prod_id):
    fila = get_db().execute("SELECT * FROM productos WHERE id = ?", (prod_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _categorias_de(prod_id):
    return [f["catalogo_id"] for f in get_db().execute(
        "SELECT catalogo_id FROM productos_categorias WHERE producto_id = ?", (prod_id,)
    ).fetchall()]


def _usos_de(prod_id):
    return [f["catalogo_id"] for f in get_db().execute(
        "SELECT catalogo_id FROM productos_usos WHERE producto_id = ?", (prod_id,)
    ).fetchall()]


def _unidades():
    return get_db().execute(
        "SELECT id, nombre, cantidad FROM unidades_medida WHERE activo = 1 "
        "ORDER BY cantidad, nombre"
    ).fetchall()


def _contexto_formulario(producto=None):
    return {
        "formas": cat_opciones("forma_farmaceutica"),
        "principios": cat_opciones("principio"),
        "laboratorios": cat_opciones("laboratorio"),
        "categorias": cat_opciones("categoria"),
        "usos": cat_opciones("uso"),
        "unidades": _unidades(),
        "iva_tipos": IVA_TIPOS,
        "categorias_sel": _categorias_de(producto["id"]) if producto else [],
        "usos_sel": _usos_de(producto["id"]) if producto else [],
        "codigo_sugerido": _siguiente_codigo() if not producto else None,
        # Otras formas de vender el producto (sobre, caja...). Ver app/presentaciones.py
        "presentaciones": pres.filas_para_formulario(producto["id"] if producto else None),
        # Si ya tiene existencias o movimientos, la unidad de inventario queda bloqueada
        "unidad_bloqueada": pres.tiene_historia(get_db(), producto["id"]) if producto else False,
        "producto": producto,
    }


@bp.route("/")
@login_required
def lista():
    q = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "activos")
    vista = request.args.get("vista", "").strip()
    if not vista:
        vista = request.cookies.get("productos_vista", "grid")

    sql = (
        "SELECT p.*, "
        "  (SELECT GROUP_CONCAT(c.nombre, ', ') "
        "   FROM productos_categorias pc JOIN catalogos c ON c.id = pc.catalogo_id "
        "   WHERE pc.producto_id = p.id) AS categorias_txt, "
        "  (SELECT nombre FROM catalogos WHERE id = p.principio_id) AS principio_nombre, "
        "  (SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS laboratorio_nombre, "
        "  (SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad_nombre "
        "FROM productos p"
    )
    cond, params = [], []
    if filtro == "activos":
        cond.append("p.activo = 1")
    elif filtro == "inactivos":
        cond.append("p.activo = 0")
    elif filtro == "frio":
        cond.append("p.activo = 1 AND p.cadena_frio = 1")
    elif filtro == "control":
        cond.append("p.activo = 1 AND p.control_especial = 1")
    elif filtro == "formula":
        cond.append("p.activo = 1 AND p.requiere_formula = 1")

    if q:
        cond.append(
            "(p.codigo LIKE ? OR p.codigo_barras LIKE ? OR p.nombre LIKE ? "
            "OR p.descripcion LIKE ? OR p.grupo LIKE ? "
            "OR p.principio_id IN (SELECT id FROM catalogos WHERE nombre LIKE ?) "
            "OR p.laboratorio_id IN (SELECT id FROM catalogos WHERE nombre LIKE ?))"
        )
        like = f"%{q}%"
        params += [like, like, like, like, like, like, like]

    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY p.nombre COLLATE NOCASE"
    filas = get_db().execute(sql, params).fetchall()

    respuesta = render_template("productos/lista.html",
                                productos=filas, q=q, filtro=filtro, vista=vista)
    from flask import make_response
    resp = make_response(respuesta)
    resp.set_cookie("productos_vista", vista, max_age=60 * 60 * 24 * 365)
    return resp


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

    def cat(campo):
        v = request.form.get(campo, "").strip()
        try:
            return int(v) if v else None
        except ValueError:
            return None

    iva_tipo = request.form.get("iva_tipo", "gravado")
    return {
        "codigo": request.form.get("codigo", "").strip(),
        "codigo_barras": request.form.get("codigo_barras", "").strip() or None,
        "nombre": request.form.get("nombre", "").strip(),
        "descripcion": request.form.get("descripcion", "").strip() or None,
        "grupo": request.form.get("grupo", "").strip() or None,
        "principio_id": cat("principio_id"),
        "laboratorio_id": cat("laboratorio_id"),
        "forma_farmaceutica_id": cat("forma_farmaceutica_id"),
        "unidad_venta_id": cat("unidad_venta_id"),
        "concentracion": request.form.get("concentracion", "").strip() or None,
        "registro_sanitario": request.form.get("registro_sanitario", "").strip() or None,
        "registro_vence": request.form.get("registro_vence", "").strip() or None,
        "iva_tipo": iva_tipo,
        "iva_tarifa": 0.0 if iva_tipo in ("excluido", "exento") else num("iva_tarifa", 19.0),
        "precio_compra": num("precio_compra", 0.0),
        "precio_venta": num("precio_venta", 0.0),
        "precio_maximo": num("precio_maximo") or None,
        "stock_minimo": ent("stock_minimo", 0),
        "requiere_formula": 1 if request.form.get("requiere_formula") else 0,
        "cadena_frio": 1 if request.form.get("cadena_frio") else 0,
        "control_especial": 1 if request.form.get("control_especial") else 0,
        "maneja_vencimiento": 1 if request.form.get("maneja_vencimiento") else 0,
        "observaciones": request.form.get("observaciones", "").strip() or None,
        "categorias": [int(x) for x in request.form.getlist("categorias") if x.isdigit()],
        "usos": [int(x) for x in request.form.getlist("usos") if x.isdigit()],
        "presentaciones": pres.leer_del_formulario(request.form),
        # En qué presentación lo vende el POS al tocar la tarjeta (vacío = unidad de inventario)
        "venta_defecto_unidad_id": cat("venta_defecto_unidad_id"),
    }


def _validar(datos, producto_id=None):
    errores = []
    if not datos["codigo"]:
        errores.append("El código interno es obligatorio.")
    if not datos["nombre"]:
        errores.append("El nombre es obligatorio.")
    if datos["iva_tipo"] not in IVA_TIPOS:
        errores.append("Tipo de IVA no válido.")
    if datos["precio_venta"] < 0 or datos["precio_compra"] < 0:
        errores.append("Los precios no pueden ser negativos.")
    if not datos["unidad_venta_id"]:
        errores.append("Debes seleccionar la unidad de inventario.")
    # La unidad de inventario NO se cambia desde aquí si el producto ya tiene
    # existencias o movimientos: los números quedarían mal (ver presentaciones.tiene_historia)
    if producto_id:
        db = get_db()
        actual = db.execute("SELECT unidad_venta_id FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if actual and actual["unidad_venta_id"] and datos["unidad_venta_id"] != actual["unidad_venta_id"] \
                and pres.tiene_historia(db, producto_id):
            errores.append("La unidad de inventario no se puede cambiar aquí porque el producto ya tiene "
                           "existencias o movimientos. Usa el botón 'Cambiar unidad de inventario', "
                           "que convierte las cantidades.")
    # La presentación por defecto debe ser una de las del producto
    if datos["venta_defecto_unidad_id"]:
        if datos["venta_defecto_unidad_id"] == datos["unidad_venta_id"]:
            datos["venta_defecto_unidad_id"] = None          # es la unidad de inventario
        elif datos["venta_defecto_unidad_id"] not in {f["unidad_id"] for f in datos["presentaciones"]}:
            errores.append("'El POS lo vende como' debe ser la unidad de inventario o una de las presentaciones.")
    if datos["control_especial"] and not datos["registro_sanitario"]:
        errores.append("Un producto de control especial debe tener registro sanitario INVIMA.")
    if datos["control_especial"] or datos["cadena_frio"]:
        datos["maneja_vencimiento"] = 1
    # Otras presentaciones (sobre, caja...): factor > 1, precio > 0, sin repetir
    errores += pres.validar(datos["presentaciones"], datos["unidad_venta_id"],
                            producto_id, datos["codigo_barras"])
    return errores


def _guardar_relaciones(db, prod_id, categorias, usos):
    db.execute("DELETE FROM productos_categorias WHERE producto_id = ?", (prod_id,))
    db.execute("DELETE FROM productos_usos WHERE producto_id = ?", (prod_id,))
    for cid in categorias:
        db.execute("INSERT OR IGNORE INTO productos_categorias (producto_id, catalogo_id) VALUES (?, ?)",
                   (prod_id, cid))
    for uid in usos:
        db.execute("INSERT OR IGNORE INTO productos_usos (producto_id, catalogo_id) VALUES (?, ?)",
                   (prod_id, uid))


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
                    "INSERT INTO productos (codigo, codigo_barras, nombre, descripcion, grupo, "
                    "principio_id, laboratorio_id, forma_farmaceutica_id, unidad_venta_id, "
                    "concentracion, registro_sanitario, registro_vence, iva_tipo, iva_tarifa, "
                    "precio_compra, precio_venta, precio_maximo, stock_minimo, requiere_formula, "
                    "cadena_frio, control_especial, maneja_vencimiento, observaciones, activo, creado_en) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                    (datos["codigo"], datos["codigo_barras"], datos["nombre"], datos["descripcion"],
                     datos["grupo"], datos["principio_id"], datos["laboratorio_id"],
                     datos["forma_farmaceutica_id"], datos["unidad_venta_id"],
                     datos["concentracion"], datos["registro_sanitario"], datos["registro_vence"],
                     datos["iva_tipo"], datos["iva_tarifa"], datos["precio_compra"],
                     datos["precio_venta"], datos["precio_maximo"], datos["stock_minimo"],
                     datos["requiere_formula"], datos["cadena_frio"], datos["control_especial"],
                     datos["maneja_vencimiento"], datos["observaciones"], ahora()),
                )
                pid = cur.lastrowid
                db.execute("UPDATE productos SET venta_defecto_unidad_id = ? WHERE id = ?",
                           (datos["venta_defecto_unidad_id"], pid))
                _guardar_relaciones(db, pid, datos["categorias"], datos["usos"])
                texto_pres = pres.guardar(db, pid, datos["presentaciones"], ahora())

                # Subir imagen si viene
                archivo_img = request.files.get("imagen")
                if archivo_img and archivo_img.filename:
                    ruta, error = guardar_imagen(
                        archivo_img, "productos", max_px=1200, max_bytes=5 * 1024 * 1024,
                    )
                    if ruta:
                        db.execute("UPDATE productos SET imagen = ? WHERE id = ?", (ruta, pid))
                    elif error:
                        flash(f"Aviso: no se pudo subir la imagen ({error}).", "error")

                db.commit()
                registrar("producto_creado", "productos", pid,
                          f"código={datos['codigo']} nombre={datos['nombre']}{texto_pres}")
                flash("Producto creado.", "ok")
                return redirect(url_for("productos.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe un producto con ese código.")
        for e in errores:
            flash(e, "error")
    return render_template("productos/form.html", **_contexto_formulario())


@bp.route("/<int:prod_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def editar(prod_id):
    producto = _obtener(prod_id)
    if request.method == "POST":
        datos = _leer_formulario()
        errores = _validar(datos, prod_id)
        if not errores:
            db = get_db()
            try:
                db.execute(
                    "UPDATE productos SET codigo=?, codigo_barras=?, nombre=?, descripcion=?, grupo=?, "
                    "principio_id=?, laboratorio_id=?, forma_farmaceutica_id=?, unidad_venta_id=?, "
                    "concentracion=?, registro_sanitario=?, registro_vence=?, iva_tipo=?, iva_tarifa=?, "
                    "precio_compra=?, precio_venta=?, precio_maximo=?, stock_minimo=?, requiere_formula=?, "
                    "cadena_frio=?, control_especial=?, maneja_vencimiento=?, observaciones=?, "
                    "actualizado_en=? WHERE id=?",
                    (datos["codigo"], datos["codigo_barras"], datos["nombre"], datos["descripcion"],
                     datos["grupo"], datos["principio_id"], datos["laboratorio_id"],
                     datos["forma_farmaceutica_id"], datos["unidad_venta_id"],
                     datos["concentracion"], datos["registro_sanitario"], datos["registro_vence"],
                     datos["iva_tipo"], datos["iva_tarifa"], datos["precio_compra"],
                     datos["precio_venta"], datos["precio_maximo"], datos["stock_minimo"],
                     datos["requiere_formula"], datos["cadena_frio"], datos["control_especial"],
                     datos["maneja_vencimiento"], datos["observaciones"], ahora(), prod_id),
                )
                db.execute("UPDATE productos SET venta_defecto_unidad_id = ? WHERE id = ?",
                           (datos["venta_defecto_unidad_id"], prod_id))
                _guardar_relaciones(db, prod_id, datos["categorias"], datos["usos"])
                texto_pres = pres.guardar(db, prod_id, datos["presentaciones"], ahora())

                # Manejar imagen
                accion_img = request.form.get("_imagen_accion", "")
                if accion_img == "eliminar":
                    eliminar_imagen(producto["imagen"])
                    db.execute("UPDATE productos SET imagen = NULL WHERE id = ?", (prod_id,))
                else:
                    archivo_img = request.files.get("imagen")
                    if archivo_img and archivo_img.filename:
                        ruta, error = guardar_imagen(
                            archivo_img, "productos", max_px=1200, max_bytes=5 * 1024 * 1024,
                        )
                        if ruta:
                            eliminar_imagen(producto["imagen"])
                            db.execute("UPDATE productos SET imagen = ? WHERE id = ?", (ruta, prod_id))
                        elif error:
                            flash(f"Aviso: no se pudo subir la imagen ({error}).", "error")

                db.commit()
                registrar("producto_editado", "productos", prod_id,
                          f"código={datos['codigo']}{texto_pres}")
                flash("Producto actualizado.", "ok")
                return redirect(url_for("productos.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe otro producto con ese código.")
        for e in errores:
            flash(e, "error")
    return render_template("productos/form.html", **_contexto_formulario(producto))


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

# ============================================================
# CAMBIAR LA UNIDAD DE INVENTARIO (asistente que convierte todo)
# Ver app/unidad_inventario.py para la explicación completa.
# ============================================================
@bp.route("/<int:prod_id>/cambiar-unidad", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def cambiar_unidad(prod_id):
    from . import unidad_inventario
    producto = _obtener(prod_id)
    db = get_db()

    def numero(nombre):
        texto = (request.form.get(nombre) or "").strip().replace(",", ".")
        try:
            return float(texto) if texto else None
        except ValueError:
            return -1

    if request.method == "POST":
        modo = request.form.get("modo")
        factor = 1.0 if modo == "corregir" else numero("factor")
        unidad_id = request.form.get("unidad_id", type=int)
        try:
            texto = unidad_inventario.cambiar(db, producto, unidad_id, factor,
                                              numero("precio") if modo == "convertir" else None,
                                              numero("maximo") if modo == "convertir" else None)
        except unidad_inventario.UnidadError as e:
            flash(str(e), "error")
        else:
            registrar("producto_unidad_cambiada", "productos", prod_id, texto)
            flash("Unidad de inventario cambiada. Revisa la ficha (precios y presentaciones).", "ok")
            return redirect(url_for("productos.editar", prod_id=prod_id))

    unidad_actual = db.execute("SELECT * FROM unidades_medida WHERE id = ?",
                               (producto["unidad_venta_id"],)).fetchone()
    existencias = db.execute("SELECT COALESCE(SUM(cantidad_disponible), 0) FROM lotes WHERE producto_id = ?",
                             (prod_id,)).fetchone()[0]
    return render_template("productos/cambiar_unidad.html", producto=producto, unidad_actual=unidad_actual,
                           existencias=existencias, unidades=_unidades(),
                           presentaciones=pres.filas_para_formulario(prod_id))
