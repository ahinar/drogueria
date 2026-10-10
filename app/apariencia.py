"""Apariencia: el TEMA (colores y letra) que cada usuario escoge.

CÓMO FUNCIONA (para aprender):
    - Cada usuario guarda su tema en usuarios.tema ('verde', 'azul' o 'clasico').
    - base.html pone ese nombre en <html data-tema="verde">.
    - static/css/temas.css define los colores de cada tema con "variables CSS"
      (por ejemplo --acento). Las demás hojas de estilo usan esas variables, así
      que al cambiar de tema cambia todo el programa sin tocar cada pantalla.
    - "Clásico" es el aspecto que tenía el programa antes del rediseño: si el
      nuevo no gusta, se vuelve a él con un clic.
"""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .audit import registrar
from .auth import login_required
from .db import get_db

bp = Blueprint("apariencia", __name__, url_prefix="/cuenta")

# nombre interno -> (nombre para mostrar, descripción, colores de muestra)
TEMAS = {
    "verde": ("Verde salud", "Verde azulado, letra IBM Plex Sans e íconos de línea. Es el tema por defecto.",
              ["#0E2A25", "#0F766E", "#E6F3F1", "#F4F7F6"]),
    "azul": ("Azul", "El mismo diseño nuevo, en tonos azules.",
             ["#0F1B33", "#1D4ED8", "#E8EEFC", "#F4F6FA"]),
    "clasico": ("Clásico", "Como se veía el programa antes del rediseño (emojis y letra del sistema).",
                ["#12212e", "#0a6ebd", "#eaf3fb", "#f4f6f8"]),
}
TEMA_POR_DEFECTO = "verde"


def tema_de(usuario):
    """Tema del usuario conectado (o el de por defecto si no hay sesión)."""
    try:
        tema = usuario["tema"] if usuario is not None else None
    except (IndexError, KeyError):
        tema = None
    return tema if tema in TEMAS else TEMA_POR_DEFECTO


def caja_abierta_actual():
    """Caja del POS abierta (para mostrarla en la barra superior), o None."""
    try:
        return get_db().execute("SELECT numero FROM cajas WHERE estado = 'abierta' "
                                "ORDER BY id DESC LIMIT 1").fetchone()
    except Exception:
        return None


@bp.route("/apariencia", methods=["GET", "POST"])
@login_required
def apariencia():
    if request.method == "POST":
        tema = request.form.get("tema")
        if tema not in TEMAS:
            flash("Ese tema no existe.", "error")
        else:
            db = get_db()
            db.execute("UPDATE usuarios SET tema = ? WHERE id = ?", (tema, g.user["id"]))
            db.commit()
            registrar("tema_cambiado", "usuarios", g.user["id"], f"tema={tema}")
            flash(f"Listo: ahora usas el tema {TEMAS[tema][0]}.", "ok")
        return redirect(url_for("apariencia.apariencia"))
    return render_template("apariencia.html", temas=TEMAS, actual=tema_de(g.user))
