"""Equipos y calibraciones (termohigrómetros, neveras, data loggers, balanzas...).

PARA QUÉ (para aprender):
    La Secretaría de Salud pide que los equipos que miden temperatura y humedad
    estén CALIBRADOS y que se guarde el certificado. Este módulo:
      - Lleva la lista de equipos, con la zona de temperatura que miden.
      - Guarda el HISTORIAL de calibraciones (fecha, empresa, número y archivo
        del certificado, resultado conforme / no conforme).
      - Calcula el estado de cada equipo: al día, por vencer (≤ 30 días),
        vencida o sin calibración. El panel de alertas del Inicio lo usa.
      - Al registrar una temperatura, el programa anota qué equipo de esa zona
        la midió (temperatura_registros.equipo_id), para trazabilidad.

QUIÉN PUEDE:
    Ver: todos. Crear, editar y registrar calibraciones: administrador y DT.
"""
import calendar
from datetime import date

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .utils_imagenes import guardar_documento

bp = Blueprint("equipos", __name__, url_prefix="/equipos")

TIPOS = {
    "termohigrometro": "Termohigrómetro",
    "nevera": "Nevera / refrigerador",
    "data_logger": "Data logger",
    "termometro": "Termómetro",
    "balanza": "Balanza / báscula",
    "tensiometro": "Tensiómetro",
    "glucometro": "Glucómetro",
    "otro": "Otro",
}
DIAS_AVISO = 30          # "por vencer" = vence en 30 días o menos

# Resultado de la última calibración de cada equipo (para la consulta SQL).
# Si fue "no conforme", el equipo NO sirve aunque la fecha esté vigente.
ULTIMO_RESULTADO = ("(SELECT c.resultado FROM calibraciones c WHERE c.equipo_id = e.id "
                    "ORDER BY c.fecha DESC, c.id DESC LIMIT 1) AS ultimo_resultado")


# ----------------------------------------------------------------------
# Ayudas
# ----------------------------------------------------------------------

def sumar_meses(fecha, meses):
    """Suma meses a una fecha: 31/01 + 1 mes = 28/02 (o 29 en bisiesto)."""
    mes = fecha.month - 1 + meses
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def estado_calibracion(proxima, hoy=None):
    """('vencida' | 'por_vencer' | 'al_dia' | 'sin', días que faltan o None)."""
    if not proxima:
        return "sin", None
    hoy = hoy or date.today()
    try:
        dias = (date.fromisoformat(str(proxima)[:10]) - hoy).days
    except ValueError:
        return "sin", None
    if dias < 0:
        return "vencida", dias
    if dias <= DIAS_AVISO:
        return "por_vencer", dias
    return "al_dia", dias


ESTADOS = {
    "no_conforme": ("⛔ No conforme", "rojo"),
    "vencida": ("⛔ Calibración vencida", "rojo"),
    "por_vencer": ("⚠️ Vence pronto", "amarillo"),
    "al_dia": ("✅ Al día", "verde"),
    "sin": ("❔ Sin calibración", "gris"),
}


def _obtener(equipo_id):
    fila = get_db().execute(
        "SELECT e.*, z.nombre AS zona_nombre, " + ULTIMO_RESULTADO + " FROM equipos e "
        "LEFT JOIN zonas_temperatura z ON z.id = e.zona_id WHERE e.id = ?", (equipo_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _con_estado(fila):
    """Fila de equipo -> diccionario con su estado de calibración listo para mostrar."""
    d = dict(fila)
    d["estado"], d["dias"] = estado_calibracion(d["proxima_calibracion"])
    if d.get("ultimo_resultado") == "no_conforme":
        d["estado"] = "no_conforme"
    d["estado_texto"], d["estado_color"] = ESTADOS[d["estado"]]
    d["tipo_texto"] = TIPOS.get(d["tipo"], d["tipo"])
    return d


def _zonas():
    return get_db().execute("SELECT id, nombre FROM zonas_temperatura ORDER BY nombre").fetchall()


def equipo_de_zona(zona_id):
    """Id del equipo activo que mide esa zona (el más reciente), o None.

    Lo usa temperaturas.py al guardar una lectura.
    """
    fila = get_db().execute("SELECT id FROM equipos WHERE zona_id = ? AND activo = 1 "
                            "ORDER BY id DESC LIMIT 1", (zona_id,)).fetchone()
    return fila["id"] if fila else None


# ----------------------------------------------------------------------
# Lista
# ----------------------------------------------------------------------

@bp.route("/")
@login_required
def lista():
    filas = get_db().execute(
        "SELECT e.*, z.nombre AS zona_nombre, " + ULTIMO_RESULTADO + " FROM equipos e "
        "LEFT JOIN zonas_temperatura z ON z.id = e.zona_id "
        "ORDER BY e.activo DESC, e.nombre COLLATE NOCASE").fetchall()
    equipos = [_con_estado(f) for f in filas]
    # Zonas de temperatura activas que no tienen ningún equipo asignado
    sin_equipo = get_db().execute(
        "SELECT nombre FROM zonas_temperatura z WHERE z.activa = 1 AND NOT EXISTS "
        "(SELECT 1 FROM equipos e WHERE e.zona_id = z.id AND e.activo = 1) ORDER BY nombre").fetchall()
    return render_template("equipos/lista.html", equipos=equipos, sin_equipo=sin_equipo)


# ----------------------------------------------------------------------
# Crear y editar
# ----------------------------------------------------------------------

def _leer_form():
    zona = (request.form.get("zona_id") or "").strip()
    try:
        frecuencia = int(request.form.get("frecuencia_meses") or 12)
    except ValueError:
        frecuencia = 0
    return {
        "nombre": (request.form.get("nombre") or "").strip(),
        "tipo": request.form.get("tipo") or "termohigrometro",
        "marca": (request.form.get("marca") or "").strip() or None,
        "modelo": (request.form.get("modelo") or "").strip() or None,
        "serie": (request.form.get("serie") or "").strip() or None,
        "zona_id": int(zona) if zona.isdigit() else None,
        "frecuencia_meses": frecuencia,
        "observaciones": (request.form.get("observaciones") or "").strip() or None,
    }


def _validar(datos):
    errores = []
    if not datos["nombre"]:
        errores.append("El nombre es obligatorio (ej: Termohigrómetro bodega).")
    if datos["tipo"] not in TIPOS:
        errores.append("Tipo de equipo no válido.")
    if not 1 <= datos["frecuencia_meses"] <= 60:
        errores.append("La frecuencia de calibración debe estar entre 1 y 60 meses.")
    return errores


@bp.route("/nuevo", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def nuevo():
    datos = None
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            cur = db.execute(
                "INSERT INTO equipos (nombre, tipo, marca, modelo, serie, zona_id, frecuencia_meses, "
                "observaciones, activo, creado_en) VALUES (?,?,?,?,?,?,?,?,1,?)",
                (datos["nombre"], datos["tipo"], datos["marca"], datos["modelo"], datos["serie"],
                 datos["zona_id"], datos["frecuencia_meses"], datos["observaciones"], ahora()))
            db.commit()
            registrar("equipo_creado", "equipos", cur.lastrowid, f"nombre={datos['nombre']} tipo={datos['tipo']}")
            flash("Equipo creado. Ahora registra su calibración.", "ok")
            return redirect(url_for("equipos.ver", equipo_id=cur.lastrowid))
        for e in errores:
            flash(e, "error")
    return render_template("equipos/form.html", equipo=datos, zonas=_zonas(), tipos=TIPOS, nuevo=True)


@bp.route("/<int:equipo_id>/editar", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def editar(equipo_id):
    equipo = _obtener(equipo_id)
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            db.execute(
                "UPDATE equipos SET nombre=?, tipo=?, marca=?, modelo=?, serie=?, zona_id=?, "
                "frecuencia_meses=?, observaciones=?, actualizado_en=? WHERE id=?",
                (datos["nombre"], datos["tipo"], datos["marca"], datos["modelo"], datos["serie"],
                 datos["zona_id"], datos["frecuencia_meses"], datos["observaciones"], ahora(), equipo_id))
            db.commit()
            registrar("equipo_editado", "equipos", equipo_id, f"nombre={datos['nombre']}")
            flash("Equipo actualizado.", "ok")
            return redirect(url_for("equipos.ver", equipo_id=equipo_id))
        for e in errores:
            flash(e, "error")
        equipo = dict(equipo, **datos)
    return render_template("equipos/form.html", equipo=equipo, zonas=_zonas(), tipos=TIPOS, nuevo=False)


@bp.route("/<int:equipo_id>/activar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def activar(equipo_id):
    """Dar de baja (o volver a activar) un equipo. No se borra: su historial se conserva."""
    equipo = _obtener(equipo_id)
    nuevo = 0 if equipo["activo"] else 1
    db = get_db()
    db.execute("UPDATE equipos SET activo=?, actualizado_en=? WHERE id=?", (nuevo, ahora(), equipo_id))
    db.commit()
    registrar("equipo_activado" if nuevo else "equipo_dado_de_baja", "equipos", equipo_id,
              f"nombre={equipo['nombre']}")
    flash("Equipo activado." if nuevo else "Equipo dado de baja (su historial se conserva).", "ok")
    return redirect(url_for("equipos.ver", equipo_id=equipo_id))


# ----------------------------------------------------------------------
# Ver un equipo + historial + registrar calibración
# ----------------------------------------------------------------------

@bp.route("/<int:equipo_id>")
@login_required
def ver(equipo_id):
    equipo = _con_estado(_obtener(equipo_id))
    historial = get_db().execute(
        "SELECT * FROM calibraciones WHERE equipo_id = ? ORDER BY fecha DESC, id DESC", (equipo_id,)).fetchall()
    lecturas = get_db().execute(
        "SELECT COUNT(*) FROM temperatura_registros WHERE equipo_id = ?", (equipo_id,)).fetchone()[0]
    hoy = date.today()
    return render_template("equipos/ver.html", equipo=equipo, historial=historial, lecturas=lecturas,
                           hoy=hoy.isoformat(),
                           proxima_sugerida=sumar_meses(hoy, equipo["frecuencia_meses"] or 12).isoformat())


@bp.route("/<int:equipo_id>/calibrar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def calibrar(equipo_id):
    """Registra una calibración y actualiza la fecha de la próxima en el equipo."""
    equipo = _obtener(equipo_id)
    volver = redirect(url_for("equipos.ver", equipo_id=equipo_id))
    try:
        fecha = date.fromisoformat(request.form.get("fecha") or "")
    except ValueError:
        flash("Indica la fecha de la calibración.", "error")
        return volver
    if fecha > date.today():
        flash("La fecha de calibración no puede ser futura.", "error")
        return volver
    # Si no se escribe la próxima, se calcula con la frecuencia del equipo
    try:
        proxima = date.fromisoformat(request.form.get("proxima") or "")
    except ValueError:
        proxima = sumar_meses(fecha, equipo["frecuencia_meses"] or 12)
    if proxima <= fecha:
        flash("La próxima calibración debe ser después de la fecha de calibración.", "error")
        return volver
    resultado = request.form.get("resultado") if request.form.get("resultado") in ("conforme", "no_conforme") else "conforme"

    # Certificado escaneado (PDF o foto), opcional pero recomendado
    archivo = None
    if request.files.get("certificado") and request.files["certificado"].filename:
        archivo, error = guardar_documento(request.files["certificado"], "certificados")
        if error:
            flash(f"No se guardó la calibración: {error}", "error")
            return volver

    db = get_db()
    cur = db.execute(
        "INSERT INTO calibraciones (equipo_id, fecha, proxima, empresa, certificado_numero, resultado, "
        "archivo, observaciones, usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (equipo_id, fecha.isoformat(), proxima.isoformat(),
         (request.form.get("empresa") or "").strip() or None,
         (request.form.get("certificado_numero") or "").strip() or None,
         resultado, archivo, (request.form.get("observaciones") or "").strip() or None,
         g.user["id"], g.user["nombre"], ahora()))
    # El equipo queda con la calibración MÁS RECIENTE (por si se carga una vieja después)
    ultima = db.execute("SELECT fecha, proxima FROM calibraciones WHERE equipo_id = ? "
                        "ORDER BY fecha DESC, id DESC LIMIT 1", (equipo_id,)).fetchone()
    db.execute("UPDATE equipos SET fecha_calibracion=?, proxima_calibracion=?, actualizado_en=? WHERE id=?",
               (ultima["fecha"], ultima["proxima"], ahora(), equipo_id))
    db.commit()
    registrar("equipo_calibrado", "equipos", equipo_id,
              f"nombre={equipo['nombre']} fecha={fecha} proxima={proxima} resultado={resultado} "
              f"calibracion_id={cur.lastrowid}")
    if resultado == "no_conforme":
        flash("Calibración registrada como NO CONFORME: no uses este equipo para registrar temperaturas "
              "hasta repararlo o reemplazarlo.", "error")
    else:
        flash(f"Calibración registrada. Próxima: {proxima.strftime('%d/%m/%Y')}.", "ok")
    return volver
