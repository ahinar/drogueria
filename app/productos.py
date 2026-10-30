"""Productos: CRUD con bitácora, catálogos, categorías múltiples, usos y presentaciones."""
import sqlite3

from flask import (Blueprint, flash, redirect, render_template, request, url_for)
from .audit import registrar
from .auth import login_required, roles_required
from .catalogos import opciones as cat_opciones
from .db import ahora, get_db
from .utiles import obtener_o_404   # versión 1.1.15: ayudas comunes (app/utiles.py)
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
    return obtener_o_404("productos", prod_id)


def _categorias_de(prod_id):
    return [f["catalogo_id"] for f in get_db().execute(
        "SELECT catalogo_id FROM productos_categorias WHERE producto_id = ?", (prod_id,)
    ).fetchall()]


def _usos_de(prod_id):
    return [f["catalogo_id"] for f in get_db().execute(
        "SELECT catalogo_id FROM productos_usos WHERE producto_id = ?", (prod_id,)
    ).fetchall()]


def _unidades():
    # "Unidad" primero y después por tamaño (Sello x 4, Caja x 10, Sello x 10...): app/nombres.py
    from .nombres import orden_unidades
    return orden_unidades(get_db().execute(
        "SELECT id, nombre, cantidad FROM unidades_medida WHERE activo = 1").fetchall())


def _id_unidad_basica():
    """Id de la unidad "Unidad" (la cuenta mínima por defecto: 1 pasta, 1 frasco)."""
    fila = get_db().execute("SELECT id FROM unidades_medida WHERE nombre = 'Unidad' COLLATE NOCASE").fetchone()
    return fila["id"] if fila else None


def _venta_de(producto):
    """Lo que la ficha muestra ARRIBA: cómo se vende normalmente.

    En la base de datos se guarda así (ver presentaciones.py):
        - unidad_venta_id = la unidad mínima en que se CUENTA (Unidad, Tableta)
        - la presentación de venta (Sello x 10) con su precio, y
        - venta_defecto_unidad_id = cuál de ellas se vende al tocar en el POS.
    Para la persona es más natural: "se vende por Sello x 10 a $4.000".
    Devuelve {unidad_id, precio, costo, maximo, factor, fila_id}.
    """
    if not producto:
        return {"unidad_id": None, "precio": "", "costo": "", "maximo": "", "factor": 1, "fila_id": None, "barras": ""}
    fila = None
    if producto["venta_defecto_unidad_id"]:
        fila = get_db().execute(
            "SELECT * FROM producto_presentaciones WHERE producto_id = ? AND unidad_id = ?",
            (producto["id"], producto["venta_defecto_unidad_id"])).fetchone()
    if fila is None:          # se vende por la unidad mínima (frasco, unidad...)
        return {"unidad_id": producto["unidad_venta_id"], "precio": producto["precio_venta"] or 0,
                "costo": producto["precio_compra"] or 0, "maximo": producto["precio_maximo"] or "",
                "factor": 1, "fila_id": None, "barras": ""}
    return {"unidad_id": fila["unidad_id"], "precio": fila["precio_venta"],
            "costo": round((producto["precio_compra"] or 0) * fila["factor"], 2),
            "maximo": fila["precio_maximo"] or "", "factor": fila["factor"], "fila_id": fila["id"],
            "barras": fila["codigo_barras"] or ""}


def _base_grande(producto):
    """Si el inventario de este producto se cuenta en una unidad que trae
    varias (ej. "Sello x 10"), devuelve {nombre, cantidad}; si no, None.
    Pasa con productos creados antes de que la unidad mínima fuera "Unidad".
    """
    if not producto or not producto["unidad_venta_id"]:
        return None
    u = get_db().execute("SELECT nombre, cantidad FROM unidades_medida WHERE id = ?",
                         (producto["unidad_venta_id"],)).fetchone()
    if u is None:
        return None
    cantidad = pres.cantidad_efectiva(u["nombre"], u["cantidad"])
    return {"nombre": u["nombre"], "cantidad": cantidad} if cantidad > 1 else None


def _vecinos(prod_id):
    """Para las flechas ‹ › de la ficha: el producto anterior y el
    siguiente en orden alfabético (el mismo de la lista), y en qué puesto va.
    Devuelve {anterior, siguiente, posicion, total}.
    """
    ids = [f["id"] for f in get_db().execute(
        "SELECT id FROM productos WHERE activo = 1 ORDER BY nombre COLLATE ES, id").fetchall()]
    if prod_id not in ids:
        return None
    i = ids.index(prod_id)
    return {"anterior": ids[i - 1] if i > 0 else None,
            "siguiente": ids[i + 1] if i + 1 < len(ids) else None,
            "posicion": i + 1, "total": len(ids)}


def _texto_principios(prod_id):
    from .principios import texto_de
    return texto_de(get_db(), prod_id)


def _contexto_formulario(producto=None):
    venta = _venta_de(producto)
    return {
        "venta": venta,
        "unidad_basica_id": _id_unidad_basica(),
        # ¿El inventario se cuenta en algo que trae varias (ej. Sello x 10)? Entonces
        # no se puede vender suelto: hay que pasarlo a unidades (ver form.html)
        "base_grande": _base_grande(producto),
        "formas": cat_opciones("forma_farmaceutica"),
        "principios": cat_opciones("principio"),
        # Lo que va escrito en el campo de principios: "Acetaminofén, Codeína" (versión 1.1.6)
        "principios_texto": (request.form.get("principios") if request.method == "POST"
                             else (_texto_principios(producto["id"]) if producto else "")),
        "laboratorios": cat_opciones("laboratorio"),
        "categorias": cat_opciones("categoria"),
        "usos": cat_opciones("uso"),
        "unidades": _unidades(),
        "iva_tipos": IVA_TIPOS,
        "categorias_sel": _categorias_de(producto["id"]) if producto else [],
        "usos_sel": _usos_de(producto["id"]) if producto else [],
        "codigo_sugerido": _siguiente_codigo() if not producto else None,
        # Otras formas de vender el producto (sobre, caja...). Ver app/presentaciones.py
        # Otras presentaciones (ej. Caja x 100), SIN la de venta, que va arriba
        "presentaciones": [f for f in pres.filas_para_formulario(producto["id"] if producto else None)
                           if f["id"] != venta["fila_id"]],
        # Si ya tiene existencias o movimientos, la unidad de inventario queda bloqueada
        "unidad_bloqueada": pres.tiene_historia(get_db(), producto["id"]) if producto else False,
        "producto": producto,
        "vecinos": _vecinos(producto["id"]) if producto else None,
        # ¿Se puede borrar? Solo si nunca se usó (si no, se desactiva)
        "donde_se_usa": _donde_se_usa(get_db(), producto["id"]) if producto else [],
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
        # Todos los principios activos unidos con "+" (versión 1.1.6, ver app/principios.py)
        "COALESCE((SELECT GROUP_CONCAT(c.nombre, ' + ') FROM (SELECT c2.nombre FROM producto_principios pp2 JOIN catalogos c2 ON c2.id = pp2.catalogo_id WHERE pp2.producto_id = p.id ORDER BY pp2.orden) c), (SELECT nombre FROM catalogos WHERE id = p.principio_id)) AS principio_nombre, "
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
        # Palabra por palabra: nombre, concentración, LABORATORIO... (ver app/busqueda.py)
        from .busqueda import condicion_palabras
        extra_sql, extra_params = condicion_palabras(q, extra=("p.descripcion", "p.grupo"))
        cond.append("1 = 1" + extra_sql)        # "1 = 1" no filtra nada: solo para poder pegar los AND
        params += extra_params

    if cond:
        sql += " WHERE " + " AND ".join(cond)
    # Lo más parecido a lo buscado de primero (versión 1.1.11, ver busqueda.orden_relevancia);
    # después por nombre: los que se llaman igual quedan juntos, por laboratorio
    from .busqueda import ORDEN_NOMBRE_LAB, orden_relevancia
    orden, orden_params = orden_relevancia(q)
    sql += " ORDER BY " + orden + ", " + ORDEN_NOMBRE_LAB
    params += orden_params
    filas = get_db().execute(sql, params).fetchall()

    respuesta = render_template("productos/lista.html", productos=filas, q=q, filtro=filtro,
                                vista=vista, venta=_como_se_vende([f["id"] for f in filas]),
                                # Para la barra de acciones sobre varios productos
                                acciones=ACCIONES_MASIVAS, categorias=cat_opciones("categoria"),
                                laboratorios=cat_opciones("laboratorio"))
    from flask import make_response
    resp = make_response(respuesta)
    resp.set_cookie("productos_vista", vista, max_age=60 * 60 * 24 * 365)
    return resp


def _como_se_vende(producto_ids):
    """Para la lista de productos: {id: {precio, por, existencias}} dicho como se vende.

    Ej: acetaminofén que se vende por sobre -> precio $1.600 "por Sobre x 10"
    y existencias "29 Sobre x 10 + 5 Tableta" (por dentro son 295 tabletas).
    Las existencias son las VENDIBLES (lotes disponibles y no vencidos).
    """
    if not producto_ids:
        return {}
    from datetime import date
    db = get_db()
    marcas = ",".join("?" * len(producto_ids))
    hoy = date.today().isoformat()
    stock = {f["producto_id"]: f["total"] for f in db.execute(
        "SELECT producto_id, SUM(cantidad_disponible) AS total FROM lotes "
        f"WHERE producto_id IN ({marcas}) AND estado = 'disponible' AND cantidad_disponible > 0 "
        "AND (vencimiento IS NULL OR vencimiento = '' OR vencimiento >= ?) GROUP BY producto_id",
        list(producto_ids) + [hoy])}
    defecto = {f["id"]: f["venta_defecto_unidad_id"] for f in db.execute(
        f"SELECT id, venta_defecto_unidad_id FROM productos WHERE id IN ({marcas})", list(producto_ids))}
    salida = {}
    for pid, opciones in pres.presentaciones_de(producto_ids).items():
        id_def = pres.id_por_defecto(opciones, defecto.get(pid))
        normal = next((o for o in opciones if o["id"] == id_def), opciones[0])
        salida[pid] = {"precio": normal["precio"], "por": normal["nombre"],
                       "existencias": pres.texto_existencias(stock.get(pid, 0), opciones, id_def)}
    return salida


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
        # Versión 1.1.6: varios principios escritos con comas ("acetaminofén, codeína").
        # None = el formulario no trae ese campo (se usa principio_id como antes).
        "principios_texto": request.form.get("principios"),
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
        # ¿Se vende la pasta suelta? (casilla marcada = sí)
        # (una casilla sin marcar no se envía; el campo oculto "vende_suelto_en_form" dice
        #  que la casilla SÍ estaba en el formulario. Sin él, se deja "sí", como siempre fue)
        "vende_suelto": 1 if (request.form.get("vende_suelto")
                              or not request.form.get("vende_suelto_en_form")) else 0,
    }


def _cantidad_unidad(uid):
    fila = get_db().execute("SELECT nombre, cantidad FROM unidades_medida WHERE id = ?", (uid,)).fetchone()
    return pres.cantidad_efectiva(fila["nombre"], fila["cantidad"]) if fila else 1.0


def _traducir_venta(datos):
    """Convierte lo que se escribió ARRIBA ("Sello x 10 a $4.000, se vende suelto")
    a como se guarda: unidad mínima + presentación de venta + precio de 1 unidad.

    Ejemplo: Ibuprofeno, Sello x 10 a $4.000, costo del sello $2.500, suelto sí:
        unidad mínima = Unidad
        presentación  = Sello x 10 (trae 10) a $4.000  -> se vende por defecto
        precio_venta  = $400 (lo que escribió, o $4.000 ÷ 10)
        precio_compra = $250 ($2.500 ÷ 10)
    """
    from .importador import _num             # entiende "4.000" (miles) y "2,5" (decimales)

    def num(campo):
        return _num((request.form.get(campo) or "").strip(), None)
    venta_uid = int(request.form.get("venta_unidad_id")) if (request.form.get("venta_unidad_id") or "").isdigit() else None
    datos["venta_unidad_id"] = venta_uid
    if not datos["unidad_venta_id"]:
        datos["unidad_venta_id"] = _id_unidad_basica()      # la cuenta mínima por defecto
    precio = num("venta_precio") or 0
    costo = num("venta_costo") or 0
    maximo = num("venta_maximo")
    base = datos["unidad_venta_id"]
    # Si se cuenta en algo que trae varias (ej. Sello x 10) y el producto aún no
    # tiene movimientos, se pasa a contar en "Unidad" (así se puede vender suelto)
    if base and _cantidad_unidad(base) > 1 and _id_unidad_basica():
        pid = request.view_args.get("prod_id") if request.view_args else None
        if not pid or not pres.tiene_historia(get_db(), pid):
            base = datos["unidad_venta_id"] = _id_unidad_basica()
    # Las otras presentaciones no pueden repetir la de venta (esa ya va arriba)
    datos["presentaciones"] = [f for f in datos["presentaciones"] if f["unidad_id"] != venta_uid]
    # ¿Cuántas unidades trae? Lo escrito en "Trae" (ej. un sello x 7), o lo que
    # dice la unidad de medida (Sello x 10 = 10)
    trae = num("venta_trae")
    if not venta_uid or venta_uid == base:
        factor = 1
    elif trae and trae >= 1:
        factor = trae
    else:
        factor = _cantidad_unidad(venta_uid) / _cantidad_unidad(base)
    # Si se vende por algo distinto a la unidad mínima, tiene que traer más de 1
    datos["venta_falta_trae"] = bool(venta_uid and venta_uid != base and factor <= 1)
    if factor > 1:
        barras = (request.form.get("venta_barras") or "").strip() or None
        datos["presentaciones"].insert(0, {"unidad_id": venta_uid, "factor": float(factor), "precio": float(precio),
                                           "maximo": maximo, "barras": barras})
        datos["venta_defecto_unidad_id"] = venta_uid
        datos["precio_compra"] = round(costo / factor, 4)
        suelto_precio = num("precio_venta")
        datos["precio_venta"] = (suelto_precio if datos["vende_suelto"] and suelto_precio
                                 else round(precio / factor, 2))
        datos["precio_maximo"] = round(maximo / factor, 2) if maximo else None
    else:
        # Se vende por la unidad mínima (un frasco, una unidad): no hay presentación aparte
        datos["venta_defecto_unidad_id"] = None
        datos["precio_venta"] = precio
        datos["precio_compra"] = costo
        datos["precio_maximo"] = maximo or None
        datos["vende_suelto"] = 1
    datos["venta_factor"] = factor


def _validar(datos, producto_id=None):
    errores = []
    # Formulario nuevo: "unidad de venta + precio" arriba (ver _traducir_venta)
    if "venta_unidad_id" in request.form:
        _traducir_venta(datos)
        if not datos["venta_unidad_id"]:
            errores.append("Escoge la unidad de venta (ej. Sello x 10, Frasco, Unidad).")
        elif datos["venta_falta_trae"]:
            errores.append("Escribe cuántas unidades trae la unidad de venta (ej. un sello trae 10).")
        if datos["precio_venta"] <= 0 and not errores:
            errores.append("Escribe el precio de venta.")
        elif datos["venta_factor"] > 1 and datos["presentaciones"][0]["precio"] <= 0:
            errores.append("Escribe el precio de venta.")
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
    # Si NO se vende suelto: tiene que tener al menos una presentación (sobre,
    # caja...), lo normal es venderlo por una de ellas, y el precio de la pasta
    # se calcula solo (precio del sobre ÷ cuántas trae), para costos y márgenes.
    if not datos["vende_suelto"]:
        validas = [f for f in datos["presentaciones"] if f["unidad_id"] and isinstance(f["factor"], float)
                   and f["factor"] > 1 and isinstance(f["precio"], float) and f["precio"] > 0]
        if not validas:
            errores.append("Si no se vende suelto, agrega al menos una presentación (ej. Sobre x 10) con su precio.")
        else:
            if datos["venta_defecto_unidad_id"] in (None, datos["unidad_venta_id"]):
                datos["venta_defecto_unidad_id"] = validas[0]["unidad_id"]
            principal = next((f for f in validas if f["unidad_id"] == datos["venta_defecto_unidad_id"]), validas[0])
            if datos["precio_venta"] <= 0:
                datos["precio_venta"] = round(principal["precio"] / principal["factor"], 2)
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


def _guardar_principios(db, prod_id, datos):
    """Principios activos del producto (varios, separados por comas). Ver app/principios.py"""
    from . import principios
    if datos.get("principios_texto") is not None:
        principios.guardar(db, prod_id, datos["principios_texto"])
    else:
        principios.guardar_ids(db, prod_id, [datos["principio_id"]] if datos["principio_id"] else [])


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
                db.execute("UPDATE productos SET venta_defecto_unidad_id = ?, vende_suelto = ? WHERE id = ?",
                           (datos["venta_defecto_unidad_id"], datos["vende_suelto"], pid))
                _guardar_relaciones(db, pid, datos["categorias"], datos["usos"])
                _guardar_principios(db, pid, datos)
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
                db.execute("UPDATE productos SET venta_defecto_unidad_id = ?, vende_suelto = ? WHERE id = ?",
                           (datos["venta_defecto_unidad_id"], datos["vende_suelto"], prod_id))
                _guardar_relaciones(db, prod_id, datos["categorias"], datos["usos"])
                _guardar_principios(db, prod_id, datos)
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
                # "Guardar y siguiente →": pasa al próximo producto (para editar muchos seguidos)
                if request.form.get("_despues") == "siguiente":
                    vec = _vecinos(prod_id)
                    if vec and vec["siguiente"]:
                        return redirect(url_for("productos.editar", prod_id=vec["siguiente"]))
                if request.form.get("_despues") == "quedarse":
                    return redirect(url_for("productos.editar", prod_id=prod_id))
                return redirect(url_for("productos.lista"))
            except sqlite3.IntegrityError:
                errores.append("Ya existe otro producto con ese código.")
        for e in errores:
            flash(e, "error")
    return render_template("productos/form.html", **_contexto_formulario(producto))


# Dónde puede aparecer un producto. Si aparece en alguna, NO se puede borrar:
# hay que guardar la historia (ventas, recepciones, kardex...) por trazabilidad
# (INVIMA / Secretaría de Salud). En ese caso se DESACTIVA.
_DONDE_SE_USA = (
    ("venta_lineas", "ventas"), ("recepcion_lineas", "recepciones"), ("lotes", "lotes"),
    ("movimientos_inventario", "movimientos de inventario"), ("conteo_lineas", "conteos"),
    ("devolucion_lineas", "devoluciones"),
)


def _donde_se_usa(db, prod_id):
    """Lista de lugares donde aparece el producto (vacía = se puede eliminar)."""
    return [texto for tabla, texto in _DONDE_SE_USA
            if db.execute(f"SELECT 1 FROM {tabla} WHERE producto_id = ? LIMIT 1", (prod_id,)).fetchone()]


@bp.route("/<int:prod_id>/eliminar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def eliminar(prod_id):
    """Borra un producto que NUNCA se usó (ej. uno mal creado o importado).
    Si ya tiene ventas, recepciones, lotes... no se borra: se desactiva."""
    producto = _obtener(prod_id)
    db = get_db()
    usado = _donde_se_usa(db, prod_id)
    if usado:
        flash("No se puede eliminar: ya tiene " + ", ".join(usado) +
              ". Para que no salga más, usa Desactivar.", "error")
        return redirect(url_for("productos.editar", prod_id=prod_id))
    # Primero lo que cuelga del producto, luego el producto
    for tabla in ("producto_presentaciones", "productos_categorias", "productos_usos"):
        db.execute(f"DELETE FROM {tabla} WHERE producto_id = ?", (prod_id,))
    db.execute("DELETE FROM productos WHERE id = ?", (prod_id,))
    db.commit()
    if producto["imagen"]:
        eliminar_imagen(producto["imagen"])
    registrar("producto_eliminado", "productos", prod_id,
              f"código={producto['codigo']} nombre={producto['nombre']}")
    flash(f"Producto {producto['codigo']} · {producto['nombre']} eliminado.", "ok")
    return redirect(url_for("productos.lista"))


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
# ACCIONES SOBRE VARIOS PRODUCTOS A LA VEZ (lista con casillas)
# Se marcan productos en la lista y se escoge qué hacer con todos.
# Cada acción queda en la bitácora con cuántos productos tocó.
# ============================================================
ACCIONES_MASIVAS = {
    "eliminar": "Eliminar (solo los que nunca se usaron)",
    "desactivar": "Desactivar",
    "activar": "Activar",
    "categoria": "Agregar a la categoría…",
    "laboratorio": "Poner laboratorio…",
    "iva": "Cambiar IVA…",
    "vence_si": "Marcar: maneja lote y vencimiento",
    "vence_no": "Quitar: maneja lote y vencimiento",
    "formula_si": "Marcar: requiere fórmula médica",
    "formula_no": "Quitar: requiere fórmula médica",
    "frio_si": "Marcar: cadena de frío",
    "frio_no": "Quitar: cadena de frío",
    "exportar": "Exportar a Excel",
}


@bp.route("/masivo", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def masivo():
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    accion = request.form.get("accion", "")
    valor = (request.form.get("valor") or "").strip()
    volver = request.form.get("volver") or url_for("productos.lista", vista="lista")
    if not ids or accion not in ACCIONES_MASIVAS:
        flash("Marca al menos un producto y escoge qué hacer.", "error")
        return redirect(volver)
    db = get_db()
    marcas = ",".join("?" * len(ids))

    if accion == "exportar":
        return _exportar_excel(ids)

    if accion == "eliminar":
        # Solo se borran los que nunca se usaron (trazabilidad: INVIMA / Secretaría)
        borrados, no = 0, []
        for pid in ids:
            prod = db.execute("SELECT * FROM productos WHERE id = ?", (pid,)).fetchone()
            if prod is None:
                continue
            if _donde_se_usa(db, pid):
                no.append(prod["nombre"])
                continue
            for tabla in ("producto_presentaciones", "productos_categorias", "productos_usos"):
                db.execute(f"DELETE FROM {tabla} WHERE producto_id = ?", (pid,))
            db.execute("DELETE FROM productos WHERE id = ?", (pid,))
            if prod["imagen"]:
                eliminar_imagen(prod["imagen"])
            borrados += 1
        db.commit()
        registrar("productos_eliminados_masivo", "productos", None, f"{borrados} eliminados")
        flash(f"{borrados} producto(s) eliminado(s).", "ok")
        if no:
            flash(f"{len(no)} no se eliminaron porque ya tienen ventas, lotes o recepciones "
                  f"(ej. {', '.join(no[:3])}). A esos usa Desactivar.", "error")
        return redirect(volver)

    # Cambios de un campo: columna y valor
    cambios = {
        "desactivar": ("activo", 0), "activar": ("activo", 1),
        "vence_si": ("maneja_vencimiento", 1), "vence_no": ("maneja_vencimiento", 0),
        "formula_si": ("requiere_formula", 1), "formula_no": ("requiere_formula", 0),
        "frio_si": ("cadena_frio", 1), "frio_no": ("cadena_frio", 0),
    }
    if accion in cambios:
        columna, v = cambios[accion]
        db.execute(f"UPDATE productos SET {columna} = ?, actualizado_en = ? WHERE id IN ({marcas})",
                   [v, ahora()] + ids)
        # Cadena de frío obliga a manejar vencimiento (igual que en la ficha)
        if accion == "frio_si":
            db.execute(f"UPDATE productos SET maneja_vencimiento = 1 WHERE id IN ({marcas})", ids)
    elif accion == "categoria":
        if not valor.isdigit():
            flash("Escoge la categoría.", "error")
            return redirect(volver)
        for pid in ids:
            db.execute("INSERT OR IGNORE INTO productos_categorias (producto_id, catalogo_id) VALUES (?, ?)",
                       (pid, int(valor)))
    elif accion == "laboratorio":
        if not valor.isdigit():
            flash("Escoge el laboratorio.", "error")
            return redirect(volver)
        db.execute(f"UPDATE productos SET laboratorio_id = ?, actualizado_en = ? WHERE id IN ({marcas})",
                   [int(valor), ahora()] + ids)
    elif accion == "iva":
        # valor: "excluido", "exento", "gravado:19", "gravado:5"
        tipo, _, tarifa = valor.partition(":")
        if tipo not in IVA_TIPOS:
            flash("Escoge el IVA.", "error")
            return redirect(volver)
        db.execute(f"UPDATE productos SET iva_tipo = ?, iva_tarifa = ?, actualizado_en = ? WHERE id IN ({marcas})",
                   [tipo, float(tarifa or 0) if tipo == "gravado" else 0, ahora()] + ids)
    db.commit()
    registrar("productos_cambio_masivo", "productos", None,
              f"{ACCIONES_MASIVAS[accion]} {valor} -> {len(ids)} productos")
    flash(f"Listo: «{ACCIONES_MASIVAS[accion].rstrip('…')}» en {len(ids)} producto(s).", "ok")
    return redirect(volver)


def _exportar_excel(ids):
    """Excel con los productos marcados (para revisar o compartir)."""
    import io
    from openpyxl import Workbook
    from flask import send_file
    db = get_db()
    venta = _como_se_vende(ids)
    wb = Workbook()
    ws = wb.active
    ws.title = "Productos"
    ws.append(["Código", "Código de barras", "Nombre", "Concentración", "Laboratorio", "Principio activo",
               "Se vende por", "Precio", "Costo de 1 unidad", "Existencias", "IVA", "Maneja vencimiento",
               "Requiere fórmula", "Activo"])
    marcas = ",".join("?" * len(ids))
    for p in db.execute(
            "SELECT p.*, (SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) lab, "
            "COALESCE((SELECT GROUP_CONCAT(c.nombre, ' + ') FROM (SELECT c2.nombre FROM producto_principios pp2 JOIN catalogos c2 ON c2.id = pp2.catalogo_id WHERE pp2.producto_id = p.id ORDER BY pp2.orden) c), (SELECT nombre FROM catalogos WHERE id = p.principio_id)) pa FROM productos p "
            f"WHERE p.id IN ({marcas}) ORDER BY p.nombre COLLATE ES", ids):
        v = venta.get(p["id"], {})
        ws.append([p["codigo"], p["codigo_barras"], p["nombre"], p["concentracion"], p["lab"], p["pa"],
                   v.get("por"), v.get("precio", p["precio_venta"]), p["precio_compra"], v.get("existencias"),
                   IVA_TIPOS.get(p["iva_tipo"], p["iva_tipo"]) + (f" {p['iva_tarifa']:g}%" if p["iva_tipo"] == "gravado" else ""),
                   "SI" if p["maneja_vencimiento"] else "NO", "SI" if p["requiere_formula"] else "NO",
                   "SI" if p["activo"] else "NO"])
    for col, ancho in zip("ABCDEFGHIJKLMN", (10, 16, 40, 12, 18, 18, 14, 10, 12, 22, 12, 10, 10, 8)):
        ws.column_dimensions[col].width = ancho
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    registrar("productos_exportados", "productos", None, f"{len(ids)} productos a Excel")
    return send_file(buf, as_attachment=True, download_name="productos.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
