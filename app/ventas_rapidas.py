"""VENTAS RÁPIDAS (versión 1.1.13).

PARA QUÉ (pedido de Fernando)
-----------------------------
En la droguería se venden cosas que NO van al inventario: dulcería, fotocopias,
inyectología, miscelánea... Antes había que escribirlas a mano cada vez en
«+ Venta libre». Ahora se crean UNA vez aquí y en el POS salen:
  - como botones al darle «+ Venta libre», y
  - en el buscador (escribir "fotoc" muestra la tarjeta de Fotocopia).

CÓMO SE GUARDA (tabla ventas_rapidas, migración 42)
---------------------------------------------------
  nombre      -> "Fotocopia"
  precio      -> precio de cada una CON IVA. Vacío = SIN precio fijo: el POS
                 pregunta el valor cada vez (sirve para dulcería o miscelánea,
                 donde cada cosa vale distinto).
  iva_tarifa  -> 0 (sin IVA), 5 o 19.
  costo       -> opcional: lo que le cuesta a la droguería cada una (sirve para la ganancia).
  activo      -> 0 = ya no sale en el POS (no se borra para no dañar los reportes).

Al cobrar, la línea se guarda como una venta libre más (no descuenta inventario)
pero con venta_lineas.venta_rapida_id: así el reporte de Ventas dice cuánto se
vendió de cada una.

QUIÉN PUEDE
-----------
  - Crear desde el POS (casilla «Guardar para la próxima vez»): cualquier usuario.
  - Editar, desactivar y crear en la pantalla de administración: administrador y
    director técnico. Todo queda en la bitácora.
"""
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .utiles import leer_numero   # versión 1.1.15: números escritos a la colombiana (app/utiles.py)

bp = Blueprint("ventas_rapidas", __name__, url_prefix="/ventas-rapidas")

TARIFAS = (0, 5, 19)          # las mismas de la venta libre (pos_ventas.TARIFAS_LIBRE)


def lista_activas(db=None):
    """Las ventas rápidas que salen en el POS, en orden alfabético (lista de diccionarios)."""
    db = db or get_db()
    return [dict(f) for f in db.execute(
        "SELECT id, nombre, precio, iva_tarifa, costo FROM ventas_rapidas "
        "WHERE activo = 1 ORDER BY nombre COLLATE ES")]


def _numero(texto):
    """'5.000' -> 5000.0 ; '2,5' -> 2.5 ; '' -> None ; texto raro -> 'error' (utiles.leer_numero)."""
    return leer_numero(texto, malo="error")

def leer_y_validar(datos):
    """Lee nombre, precio, IVA y costo de un formulario. Devuelve (valores, error)."""
    nombre = " ".join(str(datos.get("nombre") or "").split())[:80]
    if len(nombre) < 3:
        return None, "Escribe el nombre (mínimo 3 letras)."
    precio = _numero(datos.get("precio"))
    costo = _numero(datos.get("costo"))
    tarifa = _numero(datos.get("iva_tarifa"))
    if precio == "error" or (precio is not None and precio <= 0):
        return None, "El precio debe ser un número mayor a cero (o vacío si cambia cada vez)."
    if costo == "error" or (costo is not None and costo < 0):
        return None, "El costo debe ser un número (0 o más) o quedar vacío."
    tarifa = 0 if tarifa in (None, "error") else tarifa
    if tarifa not in TARIFAS:
        return None, "El IVA debe ser 0, 5 o 19 %."
    return {"nombre": nombre, "precio": precio, "iva_tarifa": tarifa, "costo": costo}, None


def _igual(db, nombre, excepto_id=None):
    """¿Ya existe una venta rápida con ese nombre? (sin importar tildes ni mayúsculas)"""
    return db.execute(
        "SELECT * FROM ventas_rapidas WHERE PLANO(nombre) = PLANO(?) AND id <> ?",
        (nombre, excepto_id or 0)).fetchone()


def _texto(v):
    """Para la bitácora: "Fotocopia · $200 · IVA 0 %"."""
    precio = f"${v['precio']:,.0f}".replace(",", ".") if v["precio"] else "precio libre"
    return f"{v['nombre']} · {precio} · IVA {v['iva_tarifa']:g} %"


# ---------------------------------------------------------------------
# Pantalla de administración (Administración → Ventas rápidas)
# ---------------------------------------------------------------------

@bp.route("/")
@login_required
@roles_required("administrador", "director_tecnico")
def lista():
    db = get_db()
    filas = db.execute(
        "SELECT vr.*, "
        # Cuánto se ha vendido de cada una (sin las ventas anuladas)
        "  (SELECT COUNT(*) FROM venta_lineas vl JOIN ventas v ON v.id = vl.venta_id "
        "    WHERE vl.venta_rapida_id = vr.id AND v.estado = 'completada') AS veces "
        "FROM ventas_rapidas vr ORDER BY vr.activo DESC, vr.nombre COLLATE ES").fetchall()
    editar = None
    if (request.args.get("editar") or "").isdigit():
        editar = db.execute("SELECT * FROM ventas_rapidas WHERE id = ?",
                            (int(request.args["editar"]),)).fetchone()
    return render_template("ventas_rapidas/lista.html", filas=filas, editar=editar, tarifas=TARIFAS)


@bp.route("/guardar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def guardar():
    """Crea una nueva (sin id) o cambia una que ya existe (con id)."""
    db = get_db()
    vr_id = int(request.form["id"]) if (request.form.get("id") or "").isdigit() else None
    valores, error = leer_y_validar(request.form)
    if not error and _igual(db, valores["nombre"], vr_id):
        error = f"Ya existe una venta rápida que se llama «{valores['nombre']}»."
    if error:
        flash(error, "error")
        return redirect(url_for("ventas_rapidas.lista", editar=vr_id) if vr_id else url_for("ventas_rapidas.lista"))
    if vr_id:
        db.execute("UPDATE ventas_rapidas SET nombre = ?, precio = ?, iva_tarifa = ?, costo = ?, "
                   "actualizado_en = ? WHERE id = ?",
                   (valores["nombre"], valores["precio"], valores["iva_tarifa"], valores["costo"], ahora(), vr_id))
        registrar("venta_rapida_editar", "ventas_rapidas", vr_id, _texto(valores))
        flash(f"Se guardaron los cambios de «{valores['nombre']}».", "ok")
    else:
        cur = db.execute("INSERT INTO ventas_rapidas (nombre, precio, iva_tarifa, costo, creado_en, "
                         "creado_por_nombre) VALUES (?,?,?,?,?,?)",
                         (valores["nombre"], valores["precio"], valores["iva_tarifa"], valores["costo"],
                          ahora(), _usuario()))
        registrar("venta_rapida_crear", "ventas_rapidas", cur.lastrowid, _texto(valores))
        flash(f"Venta rápida «{valores['nombre']}» creada. Ya sale en el POS.", "ok")
    db.commit()
    return redirect(url_for("ventas_rapidas.lista"))


@bp.route("/<int:vr_id>/activar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def activar(vr_id):
    """Quitar del POS (activo = 0) o volver a mostrar (activo = 1). No se borra nunca."""
    db = get_db()
    fila = db.execute("SELECT * FROM ventas_rapidas WHERE id = ?", (vr_id,)).fetchone()
    if fila:
        nuevo = 0 if fila["activo"] else 1
        db.execute("UPDATE ventas_rapidas SET activo = ?, actualizado_en = ? WHERE id = ?", (nuevo, ahora(), vr_id))
        db.commit()
        registrar("venta_rapida_" + ("activar" if nuevo else "quitar"), "ventas_rapidas", vr_id, fila["nombre"])
        flash(f"«{fila['nombre']}» " + ("vuelve a salir en el POS." if nuevo else "ya no sale en el POS."), "ok")
    return redirect(url_for("ventas_rapidas.lista"))


def _usuario():
    from flask import g
    return g.user["nombre"] if getattr(g, "user", None) else None


# ---------------------------------------------------------------------
# Desde el POS: «Guardar para la próxima vez» (cualquier usuario)
# ---------------------------------------------------------------------

@bp.route("/api/crear", methods=["POST"])
@login_required
def api_crear():
    """Crea una venta rápida desde la ventana de venta libre del POS.

    Si ya hay una con el mismo nombre, NO se crea otra: se devuelve la que existe
    (ya_existia = true) para que el POS la use.
    """
    db = get_db()
    valores, error = leer_y_validar(request.form)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    existente = _igual(db, valores["nombre"])
    if existente:
        if not existente["activo"]:          # estaba quitada: vuelve a salir
            db.execute("UPDATE ventas_rapidas SET activo = 1, actualizado_en = ? WHERE id = ?",
                       (ahora(), existente["id"]))
            db.commit()
        return jsonify({"ok": True, "ya_existia": True, "venta_rapida": {
            k: existente[k] for k in ("id", "nombre", "precio", "iva_tarifa", "costo")}})
    cur = db.execute("INSERT INTO ventas_rapidas (nombre, precio, iva_tarifa, costo, creado_en, "
                     "creado_por_nombre) VALUES (?,?,?,?,?,?)",
                     (valores["nombre"], valores["precio"], valores["iva_tarifa"], valores["costo"],
                      ahora(), _usuario()))
    db.commit()
    registrar("venta_rapida_crear", "ventas_rapidas", cur.lastrowid, _texto(valores) + " (desde el POS)")
    return jsonify({"ok": True, "ya_existia": False,
                    "venta_rapida": dict(valores, id=cur.lastrowid)})
