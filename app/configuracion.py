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
    # Ancho del papel de la impresora de tirillas (comprobante y recibos): "58" u "80" mm
    "ancho_tirilla": "80",
    # Cajón monedero (ver app/cajon.py): "no", "efectivo" o "siempre"
    "cajon_modo": "no",
    # Nombre de la impresora de tirillas en Windows (vacío = la predeterminada)
    "impresora_tirillas": "",
    # Cómo se imprime el comprobante del POS (ver app/tirilla_directa.py):
    #   "navegador" = se abre la página y se imprime desde ella (en el PC donde se vende)
    #   "directa"   = el programa la manda a la impresora del PC principal (sirve desde el portátil)
    "tirilla_modo": "navegador",
    # Tirilla directa: "si" = con tildes y ñ; "no" = sin tildes (si la impresora las imprime raras)
    "tirilla_tildes": "si",
}

MODOS_TIRILLA = {
    "navegador": "Por el navegador (en el computador donde se vende)",
    "directa": "Directa a la impresora del PC principal (recomendada; sirve desde el portátil)",
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
        # Solo se aceptan los dos anchos que existen en el mercado
        nuevos["ancho_tirilla"] = "58" if request.form.get("ancho_tirilla") == "58" else "80"
        # Cajón monedero: cuándo se abre solo y en qué impresora (ver app/cajon.py)
        from .cajon import MODOS
        nuevos["cajon_modo"] = request.form.get("cajon_modo") if request.form.get("cajon_modo") in MODOS else "no"
        nuevos["impresora_tirillas"] = (request.form.get("impresora_tirillas") or "").strip()
        # Tirilla del POS: por el navegador o directa (app/tirilla_directa.py)
        nuevos["tirilla_modo"] = "directa" if request.form.get("tirilla_modo") == "directa" else "navegador"
        nuevos["tirilla_tildes"] = "no" if request.form.get("tirilla_tildes") == "no" else "si"

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

    from . import cajon
    valores = obtener_config()
    return render_template("configuracion.html", campos=CAMPOS, valores=valores,
                           modos_cajon=cajon.MODOS, impresoras=cajon.impresoras(),
                           modos_tirilla=MODOS_TIRILLA,
                           cajon_disponible=cajon.disponible())


@bp.route("/probar-cajon", methods=["POST"])
@roles_required("administrador")
def probar_cajon():
    """Botón "Probar cajón" de la configuración: lo abre sin imprimir nada."""
    from . import cajon
    ok, error = cajon.abrir(request.form.get("impresora_tirillas") or obtener_config().get("impresora_tirillas"))
    registrar("cajon_prueba", "config", detalle="ok" if ok else error)
    flash("Listo: se mandó la orden de abrir el cajón." if ok else error, "ok" if ok else "error")
    return redirect(url_for("configuracion.ver"))

@bp.route("/probar-tirilla", methods=["POST"])
@roles_required("administrador")
def probar_tirilla():
    """Botón "Imprimir prueba": manda una tirilla corta directa a la impresora (app/tirilla_directa.py)."""
    from . import cajon
    from .tirilla_directa import Tirilla, CENTRO, NEGRILLA, SIN_NEGRILLA, IZQUIERDA
    valores = obtener_config()
    ancho = "58" if request.form.get("ancho_tirilla") == "58" else (valores.get("ancho_tirilla") or "80")
    tildes = (request.form.get("tirilla_tildes") or valores.get("tirilla_tildes")) != "no"
    t = Tirilla(ancho, tildes=tildes)
    t.orden(CENTRO, NEGRILLA).linea("PRUEBA DE IMPRESIÓN").orden(SIN_NEGRILLA)
    t.linea(valores.get("nombre_comercial") or valores.get("razon_social") or "Droguería")
    t.orden(IZQUIERDA).separador()
    t.linea("Tildes y eñe: á é í ó ú ñ Ñ ¡ ¿")
    t.dos_columnas("Acetaminofén 500 mg x 10", "$2.500")
    t.separador().linea("Si las tildes salen raras, escoge «sin tildes» en Configuración.")
    impresora = request.form.get("impresora_tirillas") or valores.get("impresora_tirillas")
    ok, error = cajon.enviar_crudo(impresora, t.terminar(), "Prueba Fervifarma")
    registrar("tirilla_prueba", "config", detalle="ok" if ok else error)
    flash("Listo: se mandó la tirilla de prueba." if ok else error, "ok" if ok else "error")
    return redirect(url_for("configuracion.ver"))
