"""RECEPCIÓN · PRODUCTOS: buscar (por nombre o código de barras), crear un producto nuevo,
completar sus datos técnicos y crear unidades, sin salir de la recepción.

Versión 1.1.15: esto estaba en app/recepciones.py (casi 1.500 líneas). Ahora la recepción
está en tres archivos, por tema, con las mismas direcciones (/recepciones/...):
    recepciones.py           -> la recepción: lista, nueva, guardar a medias, ver, aprobar
    recepciones_productos.py -> (este) buscar y crear productos sin salir de la recepción
    recepciones_acta.py      -> el acta de recepción técnica en PDF
Las rutas se registran en el mismo blueprint "recepciones" (bp).
"""
import sqlite3
from datetime import datetime

from flask import jsonify, request, url_for

from .audit import registrar
from .auth import login_required
from .db import ahora, get_db
# El blueprint de la recepción (está en app/recepciones.py)
from .recepciones import _presentaciones_simples, bp


# ---------- Búsqueda de productos para autocompletado ----------



def _fila_a_dict(f):
    return {
        # En qué puede llegar (Tableta, Sobre x 10, Caja x 100): ver "Viene en"
        "presentaciones": _presentaciones_simples(f["id"]),
        "id": f["id"],
        "codigo": f["codigo"],
        "nombre": f["nombre"],
        "concentracion": f["concentracion"] or "",
        "laboratorio": f["lab_nombre"] or "",
        "forma": f["forma_nombre"] or "",
        "unidad": f["unidad_nombre"] or "",
        "precio": f["precio_venta"] or 0,
        "registro": f["registro_sanitario"] or "",
        "registro_vence": f["registro_vence"] or "",
        "codigo_barras": f["codigo_barras"] or "",
        "maneja_vencimiento": f["maneja_vencimiento"] or 0,
        "cadena_frio": f["cadena_frio"] or 0,
        "control_especial": f["control_especial"] or 0,
        # IVA del producto (versión 1.1.6): la recepción lo pone solo en la línea
        "iva": (f["iva_tarifa"] or 0) if f["iva_tipo"] == "gravado" else 0,
    }


_SELECT_BUSQUEDA = (
    "SELECT p.id, p.codigo, p.nombre, p.concentracion, p.codigo_barras, "
    "p.registro_sanitario, p.registro_vence, p.precio_venta, p.iva_tipo, p.iva_tarifa, "
    "p.maneja_vencimiento, p.cadena_frio, p.control_especial, "
    "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
    "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre, "
    "(SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad_nombre "
    "FROM productos p "
)


@bp.route("/api/buscar-productos")
@login_required
def api_buscar_productos():
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify({"ok": True, "resultados": []})

    # Cada palabra puede estar en el nombre, la concentración o el LABORATORIO
    # (ver app/busqueda.py): "trazodona san fer 50" encuentra ese producto exacto.
    from .busqueda import ORDEN_NOMBRE_LAB, condicion_palabras, orden_relevancia
    cond, params = condicion_palabras(q)
    # Orden: lo más parecido a lo escrito de primero (código exacto, nombre que empieza
    # por lo escrito, palabra que empieza, nombre que lo contiene...). Ver
    # busqueda.orden_relevancia (versión 1.1.11; antes la regla estaba solo aquí).
    orden, orden_params = orden_relevancia(q)
    filas = get_db().execute(
        _SELECT_BUSQUEDA + "WHERE p.activo = 1" + cond + " "
        "ORDER BY " + orden + ", " + ORDEN_NOMBRE_LAB + " "
        # 40 resultados (la lista tiene barra para bajar). Antes eran 8: si había
        # muchos "MELOXICAM ...", el "MEBLAINEX MELOXICAM" quedaba por fuera.
        "LIMIT 40",
        params + orden_params,
    ).fetchall()
    return jsonify({"ok": True, "resultados": [_fila_a_dict(f) for f in filas]})


@bp.route("/api/buscar-barras")
@login_required
def api_buscar_barras():
    codigo = (request.args.get("codigo") or "").strip()
    if not codigo:
        return jsonify({"ok": False, "error": "Código vacío."})
    db = get_db()
    fila = db.execute(
        _SELECT_BUSQUEDA + "WHERE p.activo = 1 AND p.codigo_barras = ? LIMIT 1",
        (codigo,),
    ).fetchone()
    presentacion_id = 0
    if fila is None:
        # ¿Es el código de una CAJA o un SOBRE? Entonces la línea queda en esa presentación
        pp = db.execute("SELECT id, producto_id FROM producto_presentaciones WHERE codigo_barras = ? LIMIT 1",
                        (codigo,)).fetchone()
        if pp:
            presentacion_id = pp["id"]
            fila = db.execute(_SELECT_BUSQUEDA + "WHERE p.activo = 1 AND p.id = ?", (pp["producto_id"],)).fetchone()
    if fila is None:
        return jsonify({"ok": False, "error": "Producto no encontrado."})
    return jsonify({"ok": True, "producto": _fila_a_dict(fila), "presentacion_id": presentacion_id})


# ---------- Alta rápida de producto desde recepción ----------

def _producto_duplicado(nombre, laboratorio_id, concentracion):
    db = get_db()
    return db.execute(
        "SELECT id, codigo, nombre FROM productos "
        "WHERE LOWER(TRIM(nombre)) = LOWER(TRIM(?)) "
        "AND COALESCE(laboratorio_id, 0) = ? "
        "AND COALESCE(LOWER(TRIM(concentracion)), '') = COALESCE(LOWER(TRIM(?)), '') "
        "LIMIT 1",
        (nombre, laboratorio_id or 0, concentracion or ""),
    ).fetchone()


@bp.route("/api/crear-producto", methods=["POST"])
@login_required
def api_crear_producto():
    from .productos import _siguiente_codigo

    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400

    codigo = (request.form.get("codigo") or "").strip() or _siguiente_codigo()
    registro = (request.form.get("registro_sanitario") or "").strip() or None
    registro_vence = (request.form.get("registro_vence") or "").strip() or None
    unidad_venta_id = (request.form.get("unidad_venta_id") or "").strip()
    laboratorio_id = (request.form.get("laboratorio_id") or "").strip()
    concentracion = (request.form.get("concentracion") or "").strip() or None

    # Laboratorio o marca: OPCIONAL desde la versión 1.1.6 (un jabón, un pañal...
    # puede no tenerlo, o no saberse en el momento). Sin él queda "Sin laboratorio".
    laboratorio_id = int(laboratorio_id) if laboratorio_id.isdigit() else None
    # ---- Cómo se vende (igual que la ficha del producto) ----
    # Formulario nuevo: "Unidad de venta" (Sello x 10) + precio + ¿suelto?.
    # Por dentro se cuenta en "Unidad" (ver productos._traducir_venta).
    from .importador import _num
    from .productos import _id_unidad_basica, _cantidad_unidad
    venta_uid = (request.form.get("venta_unidad_id") or "").strip()
    factor = 1.0
    if venta_uid.isdigit():
        venta_uid = int(venta_uid)
        trae = _num((request.form.get("venta_trae") or "").strip(), None)
        basica = _id_unidad_basica()
        if trae and trae > 1:
            factor = float(trae)
        elif basica and venta_uid != basica and _cantidad_unidad(venta_uid) > 1:
            factor = _cantidad_unidad(venta_uid) / _cantidad_unidad(basica)
        # Si trae más de 1, se cuenta en Unidad; si no (Frasco), se cuenta en lo mismo que se vende
        unidad_venta_id = str(basica if factor > 1 and basica else venta_uid)
    else:
        venta_uid = None
    if not unidad_venta_id or not unidad_venta_id.isdigit():
        return jsonify({"ok": False, "error": "Debes elegir la unidad de venta."}), 400

    dup = _producto_duplicado(nombre, laboratorio_id, concentracion)
    if dup:
        return jsonify({
            "ok": False,
            "error": f"Ya existe un producto idéntico: {dup['codigo']} — {dup['nombre']}. "
                     f"Si es una presentación distinta, cambia la concentración o el laboratorio.",
            "duplicado_id": dup["id"],
        }), 409

    precio = _num((request.form.get("precio_venta") or "").strip(), 0.0)
    vende_suelto = 1 if (factor <= 1 or request.form.get("vende_suelto")) else 0
    precio_unidad = round(precio / factor, 2) if factor > 1 else precio   # $4.000 ÷ 10 = $400
    # Costo de la unidad de venta (el del sello): se guarda el de 1 unidad
    costo_unidad = round(_num((request.form.get("venta_costo") or "").strip(), 0.0) / factor, 4)
    codigo_barras = (request.form.get("codigo_barras") or "").strip() or None
    if codigo_barras and get_db().execute(
            "SELECT 1 FROM productos WHERE codigo_barras = ? UNION ALL "
            "SELECT 1 FROM producto_presentaciones WHERE codigo_barras = ?",
            (codigo_barras, codigo_barras)).fetchone():
        return jsonify({"ok": False, "error": f"El código de barras {codigo_barras} ya lo tiene otro producto."}), 400

    maneja_venc = 1 if request.form.get("maneja_vencimiento") else 0
    requiere_formula = 1 if request.form.get("requiere_formula") else 0
    cadena_frio = 1 if request.form.get("cadena_frio") else 0
    control_especial = 1 if request.form.get("control_especial") else 0

    if (cadena_frio or control_especial) and not registro:
        return jsonify({"ok": False, "error":
                        "Un producto de cadena de frío o control especial debe tener registro INVIMA."}), 400

    if control_especial or cadena_frio:
        maneja_venc = 1

    db = get_db()
    try:
        # IVA (versión 1.1.3, pedido de Fernando): el producto creado aquí queda
        # EXCLUIDO de IVA (tarifa 0). Si sí tiene IVA, se cambia después en la ficha
        # del producto. Antes quedaba "gravado 19 %" (lo que trae la base por defecto).
        cur = db.execute(
            "INSERT INTO productos (codigo, nombre, concentracion, laboratorio_id, "
            "registro_sanitario, registro_vence, precio_venta, unidad_venta_id, "
            "maneja_vencimiento, requiere_formula, cadena_frio, control_especial, activo, creado_en, "
            "iva_tipo, iva_tarifa) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,'excluido',0)",
            (codigo, nombre, concentracion, laboratorio_id,
             registro, registro_vence, precio_unidad, int(unidad_venta_id),
             maneja_venc, requiere_formula, cadena_frio, control_especial, ahora()),
        )
        nuevo_id = cur.lastrowid
        db.execute("UPDATE productos SET vende_suelto = ?, precio_compra = ?, codigo_barras = ? WHERE id = ?",
                   (vende_suelto, costo_unidad, codigo_barras, nuevo_id))
        if factor > 1:
            # La unidad de venta (Sello x 10) queda como presentación y se vende por defecto
            db.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                       "creado_en) VALUES (?,?,?,?,?)", (nuevo_id, venta_uid, factor, precio, ahora()))
            db.execute("UPDATE productos SET venta_defecto_unidad_id = ? WHERE id = ?", (venta_uid, nuevo_id))
        db.commit()
        registrar("producto_creado_rapido", "productos", nuevo_id,
                  f"código={codigo} nombre={nombre} (desde recepción)")

        # ---- Versión 1.1.8: FOTO DEL PRODUCTO desde la recepción ----
        # Si en la ventana "Nuevo producto" escogieron una foto, se guarda igual
        # que en la ficha del producto (carpeta uploads/productos, máx. 5 MB).
        # Si la foto falla (formato raro, muy pesada), el producto SÍ queda creado
        # y solo se avisa: así no se pierde lo demás que se escribió.
        aviso_foto = _guardar_foto_producto(nuevo_id)

        lab = db.execute("SELECT nombre FROM catalogos WHERE id = ?", (laboratorio_id,)).fetchone() \
            if laboratorio_id else None
        return jsonify({
            "ok": True,
            "id": nuevo_id,
            "codigo": codigo,
            "nombre": nombre,
            "concentracion": concentracion or "",
            "laboratorio": lab["nombre"] if lab else "",
            "registro_sanitario": registro or "",
            "maneja_vencimiento": maneja_venc,
            "cadena_frio": cadena_frio,
            "control_especial": control_especial,
            # Para el selector "Viene en" de la línea (Unidad, Sello x 10, Otra caja…)
            "presentaciones": _presentaciones_simples(nuevo_id),
            "unidad": (db.execute("SELECT nombre FROM unidades_medida WHERE id = ?",
                                  (int(unidad_venta_id),)).fetchone() or {"nombre": ""})["nombre"],
            "aviso": aviso_foto,          # None si la foto se guardó bien (o no había foto)
        })
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "Ya existe un producto con ese código."}), 400


def _guardar_foto_producto(producto_id):
    """Guarda (o quita) la foto del producto que llegó en el formulario.

    Versión 1.1.8. Lo usan "Nuevo producto" y "Completar datos" de la recepción.
      - campo "imagen": la foto nueva (reemplaza la anterior, que se borra del disco)
      - campo "imagen_accion" = "eliminar": quitar la foto que tenía
    Devuelve None si todo bien, o el texto del problema para avisarle a la persona.
    """
    from .utils_imagenes import eliminar_imagen, guardar_imagen
    db = get_db()
    anterior = db.execute("SELECT imagen FROM productos WHERE id = ?", (producto_id,)).fetchone()
    anterior = anterior["imagen"] if anterior else None
    archivo = request.files.get("imagen")
    if archivo and archivo.filename:
        ruta, error = guardar_imagen(archivo, "productos", max_px=1200, max_bytes=5 * 1024 * 1024)
        if error:
            return f"El producto quedó guardado, pero la foto no: {error}"
        db.execute("UPDATE productos SET imagen = ? WHERE id = ?", (ruta, producto_id))
        db.commit()
        if anterior:
            eliminar_imagen(anterior)            # la foto vieja ya no sirve
        registrar("producto_imagen", "productos", producto_id, "foto cargada desde recepción")
    elif request.form.get("imagen_accion") == "eliminar" and anterior:
        db.execute("UPDATE productos SET imagen = NULL WHERE id = ?", (producto_id,))
        db.commit()
        eliminar_imagen(anterior)
        registrar("producto_imagen", "productos", producto_id, "foto quitada desde recepción")
    return None


# ---------- Completar los datos técnicos del producto desde la recepción ----------
# Pasa mucho: llega un producto al que le falta el registro INVIMA, el
# laboratorio o la concentración. En vez de salir a la ficha, se completan
# aquí mismo (ventana "Completar datos" de la línea) y quedan guardados en la
# ficha del producto. Queda en la bitácora.
_CAMPOS_TECNICOS = ("laboratorio_id", "principio_id", "forma_farmaceutica_id",
                    "concentracion", "registro_sanitario", "registro_vence")


def _tecnicos_de(producto_id):
    p = get_db().execute(
        "SELECT p.id, p.nombre, p.laboratorio_id, p.principio_id, p.forma_farmaceutica_id, p.concentracion, "
        "p.registro_sanitario, p.registro_vence, p.cadena_frio, p.control_especial, p.imagen, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS laboratorio "
        "FROM productos p WHERE p.id = ?", (producto_id,)).fetchone()
    if not p:
        return None
    datos = dict(p)
    # Versión 1.1.8: dirección de la foto para mostrarla en "Completar datos"
    datos["imagen_url"] = url_for("static", filename=p["imagen"]) if p["imagen"] else ""
    # Varios principios activos, como se escriben: "Acetaminofén, Codeína" (versión 1.1.6)
    from .principios import texto_de
    datos["principios"] = texto_de(get_db(), producto_id)
    return datos


@bp.route("/api/producto/<int:producto_id>/tecnicos", methods=["GET", "POST"])
@login_required
def api_datos_tecnicos(producto_id):
    actual = _tecnicos_de(producto_id)
    if actual is None:
        return jsonify({"ok": False, "error": "Ese producto no existe."}), 404
    if request.method == "GET":
        return jsonify({"ok": True, "producto": actual})
    f = request.form
    nuevos = {}
    for campo in ("laboratorio_id", "principio_id", "forma_farmaceutica_id"):
        v = (f.get(campo) or "").strip()
        nuevos[campo] = int(v) if v.isdigit() else None
    for campo in ("concentracion", "registro_sanitario"):
        nuevos[campo] = (f.get(campo) or "").strip() or None
    vence = (f.get("registro_vence") or "").strip()
    if vence:
        try:
            datetime.strptime(vence, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False, "error": "La fecha de vencimiento del registro no es válida."}), 400
    nuevos["registro_vence"] = vence or None
    if (actual["cadena_frio"] or actual["control_especial"]) and not nuevos["registro_sanitario"]:
        return jsonify({"ok": False, "error": "Este producto es de cadena de frío o control especial: "
                                              "el registro INVIMA es obligatorio."}), 400
    # Principios activos (versión 1.1.6): si llega el texto con comas, manda ese
    db = get_db()
    cambio_principios = False
    if "principios" in f:
        from . import principios
        antes = actual["principios"]
        principios.guardar(db, producto_id, f.get("principios") or "")
        nuevos["principio_id"] = db.execute("SELECT principio_id FROM productos WHERE id = ?",
                                            (producto_id,)).fetchone()[0]
        cambio_principios = principios.texto_de(db, producto_id) != antes
    cambios = [c for c in _CAMPOS_TECNICOS if (actual[c] or None) != nuevos[c]]
    if cambio_principios and "principio_id" not in cambios:
        cambios.append("principio_id")
    if cambios:
        db.execute("UPDATE productos SET " + ", ".join(f"{c} = ?" for c in cambios) + ", actualizado_en = ? "
                   "WHERE id = ?", [nuevos[c] for c in cambios] + [ahora(), producto_id])
        db.commit()
        registrar("producto_datos_tecnicos", "productos", producto_id,
                  "desde recepción: " + ", ".join(f"{c}={nuevos[c]}" for c in cambios))
    else:
        db.commit()
    # Versión 1.1.8: también se puede poner, cambiar o quitar la FOTO del producto
    aviso_foto = _guardar_foto_producto(producto_id)
    return jsonify({"ok": True, "producto": _tecnicos_de(producto_id), "cambios": len(cambios),
                    "aviso": aviso_foto})


@bp.route("/api/crear-unidad", methods=["POST"])
@login_required
def api_crear_unidad():
    """Crea una unidad de medida desde la línea de la recepción (ej. "CAJA X 12").

    Si el nombre ya existe, devuelve la que hay. Si no escriben cuántas trae,
    se lee del nombre ("CAJA X 12" -> 12).
    """
    import re
    from .importador import _num
    nombre = " ".join((request.form.get("nombre") or "").upper().split())
    if not nombre:
        return jsonify({"ok": False, "error": "Escribe el nombre (ej. CAJA X 12)."}), 400
    cantidad = _num((request.form.get("cantidad") or "").strip(), 0)
    if cantidad <= 0:
        m = re.search(r"x\s*(\d+(?:[.,]\d+)?)\s*$", nombre, re.I)
        cantidad = float(m.group(1).replace(",", ".")) if m else 0
    if cantidad <= 1:
        return jsonify({"ok": False, "error": "Escribe cuántas unidades trae (más de 1)."}), 400
    db = get_db()
    from .nombres import unidad_igual
    fila = unidad_igual(db, nombre)          # "CAJA X12" = "Caja x 12": no se crea otra
    if fila is None:
        cur = db.execute("INSERT INTO unidades_medida (nombre, cantidad, referencia_id, activo, creado_en) "
                         "VALUES (?, ?, NULL, 1, ?)", (nombre, cantidad, ahora()))
        db.commit()
        registrar("unidad_medida_creada_api", "unidades_medida", cur.lastrowid,
                  f"nombre={nombre} cantidad={cantidad:g} (desde recepción)")
        fila = {"id": cur.lastrowid, "nombre": nombre, "cantidad": cantidad}
    return jsonify({"ok": True, "id": fila["id"], "nombre": fila["nombre"], "cantidad": fila["cantidad"]})
