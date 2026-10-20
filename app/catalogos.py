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
    "laboratorio":        ("Laboratorios y marcas",  "🏭"),   # un jabón: la marca (versión 1.1.6)
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
    sql += " ORDER BY nombre COLLATE ES"

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
        # ¿Ya existe con otra forma de escribirlo? ("SAN FER" = "Sanfer" = "san fer.")
        from .nombres import catalogo_igual
        igual = catalogo_igual(get_db(), tipo, datos["nombre"]) if datos["nombre"] else None
        if not datos["nombre"]:
            flash("El nombre es obligatorio.", "error")
        elif igual:
            flash(f"Ya existe «{igual['nombre']}»" + ("" if igual["activo"] else " (está desactivado: actívalo)")
                  + ". No se creó otro.", "error")
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
        from .nombres import catalogo_igual
        igual = catalogo_igual(get_db(), tipo, datos["nombre"], excepto_id=cat_id) if datos["nombre"] else None
        if not datos["nombre"]:
            flash("El nombre es obligatorio.", "error")
        elif igual:
            flash(f"Ya existe otro registro «{igual['nombre']}» con ese nombre. "
                  "Si son el mismo, únelos con «Buscar repetidos».", "error")
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
        "SELECT id, nombre FROM catalogos WHERE tipo = ? AND activo = 1 ORDER BY nombre COLLATE ES",
        (tipo,),
    ).fetchall()


@bp.route("/<tipo>/api/lista")
def api_lista(tipo):
    """Lista ACTUAL de un catálogo (ej. laboratorios), en JSON.

    La usa la recepción al abrir «Completar datos» y «Nuevo producto»: así
    aparecen también los laboratorios creados DESPUÉS de abrir la página
    (en otra pestaña, en Catálogos o con el botón +). Versión 1.1.3.
    """
    from flask import g
    if g.get("user") is None:                    # sin sesión no se entrega nada
        return jsonify({"ok": False, "error": "Inicia sesión."}), 401
    _validar_tipo(tipo)
    return jsonify({"ok": True, "items": [{"id": f["id"], "nombre": f["nombre"]} for f in opciones(tipo)]})


@bp.route("/<tipo>/api/crear", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def api_crear(tipo):
    """Crea un ítem de catálogo vía AJAX desde el formulario de productos."""
    _validar_tipo(tipo)
    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400
    db = get_db()
    # Si ya existe escrito de otra forma, se devuelve el que hay (y se reactiva si estaba apagado)
    from .nombres import catalogo_igual
    igual = catalogo_igual(db, tipo, nombre)
    if igual:
        if not igual["activo"]:
            db.execute("UPDATE catalogos SET activo = 1, actualizado_en = ? WHERE id = ?", (ahora(), igual["id"]))
            db.commit()
        return jsonify({"ok": True, "id": igual["id"], "nombre": igual["nombre"], "existente": True})
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

# =====================================================================
# BUSCAR REPETIDOS Y UNIRLOS (versión 1.1.6)
# =====================================================================
# Antes de la 1.1.6 se podían colar repetidos ("SAN FER" y "San fer").
# Esta pantalla los agrupa con app/nombres.clave() y deja UNIRLOS: todos los
# productos, gastos, etc. pasan al que se escoja, y los demás se borran.
# Nada se une solo: la persona escoge cuál queda.

# Dónde se usa cada catálogo: (tabla, columna). Las tablas "de unión"
# (producto ↔ catálogo) se tratan aparte porque no pueden quedar repetidas.
_USOS_CATALOGO = [
    ("productos", "principio_id"), ("productos", "laboratorio_id"),
    ("productos", "forma_farmaceutica_id"), ("gastos", "categoria_id"),
    ("otros_ingresos", "categoria_id"), ("conteos", "categoria_id"),
]
_UNIONES_CATALOGO = [("productos_categorias", "producto_id"), ("productos_usos", "producto_id"),
                     ("producto_principios", "producto_id")]
_USOS_UNIDAD = [("productos", "unidad_venta_id"), ("productos", "venta_defecto_unidad_id"),
                ("unidades_medida", "referencia_id"), ("producto_presentaciones", "unidad_id")]


def _tabla_existe(db, tabla):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone() is not None


def _usos(db, columnas, uniones, item_id):
    """Cuántas veces se usa un registro (para mostrarlo al escoger cuál queda)."""
    total = 0
    for tabla, col in columnas:
        total += db.execute(f"SELECT COUNT(*) FROM {tabla} WHERE {col} = ?", (item_id,)).fetchone()[0]
    for tabla, _col in uniones:
        if _tabla_existe(db, tabla):
            total += db.execute(f"SELECT COUNT(*) FROM {tabla} WHERE catalogo_id = ?", (item_id,)).fetchone()[0]
    return total


def grupos_repetidos(db):
    """Lista de grupos [{tipo, titulo, items:[{id, nombre, activo, usos}]}] con 2 o más iguales."""
    from .nombres import clave, orden
    grupos = []
    for tipo, (titulo, _icono_) in TIPOS.items():
        por_clave = {}
        for f in db.execute("SELECT id, nombre, activo FROM catalogos WHERE tipo = ?", (tipo,)):
            por_clave.setdefault(clave(f["nombre"]), []).append(f)
        for filas in por_clave.values():
            if len(filas) > 1:
                grupos.append({"tipo": tipo, "titulo": titulo, "items": [
                    {"id": f["id"], "nombre": f["nombre"], "activo": f["activo"],
                     "usos": _usos(db, _USOS_CATALOGO, _UNIONES_CATALOGO, f["id"])} for f in filas]})
    por_clave = {}
    for f in db.execute("SELECT id, nombre, activo FROM unidades_medida"):
        por_clave.setdefault(clave(f["nombre"]), []).append(f)
    for filas in por_clave.values():
        if len(filas) > 1:
            grupos.append({"tipo": "unidad", "titulo": "Unidades de medida", "items": [
                {"id": f["id"], "nombre": f["nombre"], "activo": f["activo"],
                 "usos": _usos(db, _USOS_UNIDAD, [], f["id"])} for f in filas]})
    for g_ in grupos:                                    # el más usado primero (sugerido para quedar)
        g_["items"].sort(key=lambda i: (-i["usos"], orden(i["nombre"])))
    grupos.sort(key=lambda g_: (g_["titulo"], orden(g_["items"][0]["nombre"])))
    return grupos


@bp.route("/repetidos")
@roles_required("administrador", "director_tecnico")
def repetidos():
    return render_template("catalogos/repetidos.html", grupos=grupos_repetidos(get_db()))


@bp.route("/repetidos/unir", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def unir_repetidos():
    """Une un grupo: todo lo que usaba los otros pasa al que queda, y los otros se borran."""
    from .nombres import clave
    tipo = request.form.get("tipo", "")
    queda = request.form.get("queda", type=int)
    otros = [int(x) for x in request.form.getlist("ids") if x.isdigit() and int(x) != queda]
    db = get_db()
    es_unidad = tipo == "unidad"
    if not es_unidad:
        _validar_tipo(tipo)
    tabla = "unidades_medida" if es_unidad else "catalogos"
    filtro_tipo = "" if es_unidad else " AND tipo = ?"
    extra = [] if es_unidad else [tipo]
    registro = db.execute(f"SELECT * FROM {tabla} WHERE id = ?{filtro_tipo}", [queda] + extra).fetchone()
    if registro is None or not otros:
        flash("Escoge cuál queda y al menos otro para unir.", "error")
        return redirect(url_for("catalogos.repetidos"))
    marcas = ",".join("?" * len(otros))
    filas_otros = db.execute(f"SELECT * FROM {tabla} WHERE id IN ({marcas}){filtro_tipo}", otros + extra).fetchall()
    # Seguridad: solo se unen registros que de verdad son el mismo nombre
    if len(filas_otros) != len(otros) or any(clave(f["nombre"]) != clave(registro["nombre"]) for f in filas_otros):
        flash("Solo se pueden unir registros con el mismo nombre.", "error")
        return redirect(url_for("catalogos.repetidos"))

    if es_unidad:
        # Un producto no puede tener dos veces la misma presentación: si pasa, se avisa y no se une
        choque = db.execute(
            f"SELECT p.nombre FROM producto_presentaciones a JOIN producto_presentaciones b "
            f"ON a.producto_id = b.producto_id JOIN productos p ON p.id = a.producto_id "
            f"WHERE a.unidad_id = ? AND b.unidad_id IN ({marcas}) LIMIT 3", [queda] + otros).fetchall()
        if choque:
            flash("No se unieron: estos productos tienen las dos unidades como presentaciones distintas: "
                  + ", ".join(f["nombre"] for f in choque) + ". Quita una en la ficha del producto y vuelve a intentar.",
                  "error")
            return redirect(url_for("catalogos.repetidos"))
    try:
        if es_unidad:
            for t, col in _USOS_UNIDAD:
                db.execute(f"UPDATE {t} SET {col} = ? WHERE {col} IN ({marcas})", [queda] + otros)
        else:
            for t, col in _USOS_CATALOGO:
                db.execute(f"UPDATE {t} SET {col} = ? WHERE {col} IN ({marcas})", [queda] + otros)
            for t, col in _UNIONES_CATALOGO:
                if not _tabla_existe(db, t):
                    continue
                # "INSERT OR IGNORE": si el producto ya tenía el que queda, no se repite
                db.execute(f"INSERT OR IGNORE INTO {t} ({col}, catalogo_id) "
                           f"SELECT {col}, ? FROM {t} WHERE catalogo_id IN ({marcas})", [queda] + otros)
                db.execute(f"DELETE FROM {t} WHERE catalogo_id IN ({marcas})", otros)
            # Si el que queda no tenía descripción (palabras de búsqueda en "usos"), toma la de otro
            if not registro["descripcion"]:
                desc = next((f["descripcion"] for f in filas_otros if f["descripcion"]), None)
                if desc:
                    db.execute("UPDATE catalogos SET descripcion = ? WHERE id = ?", (desc, queda))
        db.execute(f"UPDATE {tabla} SET activo = 1 WHERE id = ?", (queda,))
        db.execute(f"DELETE FROM {tabla} WHERE id IN ({marcas})", otros)
        db.commit()
    except Exception:
        db.rollback()
        raise
    registrar("repetidos_unidos", tabla, queda,
              f"tipo={tipo} queda={registro['nombre']} unidos=" + ", ".join(f["nombre"] for f in filas_otros))
    flash(f"Listo: todo quedó en «{registro['nombre']}» ({len(otros)} repetido(s) unido(s)).", "ok")
    return redirect(url_for("catalogos.repetidos"))
