"""Configuración del negocio: datos que van en informes, PDFs y reportes."""
from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from .audit import registrar
from .auth import roles_required
from .db import ahora, get_db
from .utils_imagenes import guardar_imagen, eliminar_imagen

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")

CAMPOS = [
    ("nit",                    "NIT",                             "text"),
    ("razon_social",           "Razón social",                    "text"),
    ("nombre_comercial",       "Nombre comercial",                "text"),
    ("direccion",              "Dirección",                       "text"),
    ("ciudad",                 "Ciudad",                          "text"),
    ("departamento",           "Departamento",                    "text"),
    ("telefono",               "Teléfono",                        "text"),
    ("celular",                "Celular / WhatsApp",              "text"),
    ("correo",                 "Correo electrónico",              "text"),
    ("sitio_web",              "Sitio web",                       "text"),
    ("regente_nombre",         "Director Técnico — Nombre",       "text"),
    ("regente_documento",      "Director Técnico — Documento",    "text"),
    ("regente_tarjeta",        "Director Técnico — Tarjeta profesional", "text"),
    ("horario",                "Horario de atención",             "text"),
]

DEFAULTS = {
    "nit": "",
    "razon_social": "",
    "nombre_comercial": "",
    "direccion": "",
    "ciudad": "",
    "departamento": "",
    "telefono": "",
    "celular": "",
    "correo": "",
    "sitio_web": "",
    "regente_nombre": "",
    "regente_documento": "",
    "regente_tarjeta": "",
    "horario": "",
    "pie_pagina": "Comprobante interno, no válido como factura.",
    "logo_ruta": "",
}


def obtener_config() -> dict:
    """Devuelve la configuración actual (combinando con los valores por defecto)."""
    filas = get_db().execute("SELECT clave, valor FROM config").fetchall()
    valores = dict(DEFAULTS)
    for fila in filas:
        valores[fila["clave"]] = fila["valor"] or ""
    return valores


def guardar_config(valores: dict) -> None:
    db = get_db()
    for clave, valor in valores.items():
        db.execute(
            "INSERT INTO config (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, valor),
        )
    db.commit()


@bp.route("/", methods=["GET", "POST"])
@roles_required("administrador")
def ver():
    if request.method == "POST":
        accion = request.form.get("_accion", "guardar")

        # ===== Eliminar logo =====
        if accion == "eliminar_logo":
            actual = obtener_config()
            if actual.get("logo_ruta"):
                eliminar_imagen(actual["logo_ruta"])
            guardar_config({"logo_ruta": ""})
            registrar("configuracion_logo_eliminado", "config")
            flash("Logo eliminado.", "ok")
            return redirect(url_for("configuracion.ver"))

        # ===== Guardar todo =====
        nuevos = {}
        for clave, _titulo, _tipo in CAMPOS:
            nuevos[clave] = request.form.get(clave, "").strip()
        nuevos["pie_pagina"] = request.form.get("pie_pagina", "").strip()

        # Manejar subida de logo
        archivo_logo = request.files.get("logo")
        if archivo_logo and archivo_logo.filename:
            ruta, error = guardar_imagen(
                archivo_logo, "logos", max_px=800, max_bytes=2 * 1024 * 1024,
                nombre_fijo="logo",
            )
            if error:
                flash(f"Error con el logo: {error}", "error")
                return redirect(url_for("configuracion.ver"))
            # Eliminar el logo anterior si existía y era distinto
            anterior = obtener_config().get("logo_ruta")
            if anterior and anterior != ruta:
                eliminar_imagen(anterior)
            nuevos["logo_ruta"] = ruta

        if not nuevos["razon_social"]:
            flash("La razón social es obligatoria.", "error")
        elif not nuevos["nit"]:
            flash("El NIT es obligatorio.", "error")
        else:
            guardar_config(nuevos)
            registrar("configuracion_actualizada", "config",
                      detalle=f"NIT={nuevos['nit']} razón={nuevos['razon_social']}")
            flash("Configuración guardada.", "ok")
            return redirect(url_for("configuracion.ver"))

    valores = obtener_config()
    return render_template("configuracion.html", campos=CAMPOS, valores=valores)