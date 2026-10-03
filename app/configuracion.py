"""Configuración del negocio: datos que van en informes, PDFs y reportes."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .audit import registrar
from .auth import roles_required
from .db import ahora, get_db

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")

# Orden en el que aparecen los campos en el formulario.
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

# Valores por defecto si aún no se ha guardado nada.
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
        nuevos = {}
        for clave, _titulo, _tipo in CAMPOS:
            nuevos[clave] = request.form.get(clave, "").strip()
        # Campo libre adicional: pie de página.
        nuevos["pie_pagina"] = request.form.get("pie_pagina", "").strip()

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