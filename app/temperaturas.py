"""Temperaturas: zonas, lecturas, alarmas y bitácora."""
import sqlite3
from datetime import datetime, timedelta

from flask import (Blueprint, abort, flash, g, jsonify, redirect,
                   render_template, request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db

bp = Blueprint("temperaturas", __name__, url_prefix="/temperaturas")

DIAS = {1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves",
        5: "Viernes", 6: "Sábado", 7: "Domingo"}


def _obtener_zona(zona_id):
    fila = get_db().execute("SELECT * FROM zonas_temperatura WHERE id = ?", (zona_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _obtener_registro(reg_id):
    fila = get_db().execute("SELECT * FROM temperatura_registros WHERE id = ?", (reg_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _en_rango(zona, temp, humedad):
    if temp < zona["temp_min"] or temp > zona["temp_max"]:
        return False
    if zona["controla_humedad"] and humedad is not None:
        if zona["humedad_min"] is not None and humedad < zona["humedad_min"]:
            return False
        if zona["humedad_max"] is not None and humedad > zona["humedad_max"]:
            return False
    return True


def _ultima_lectura(zona_id):
    return get_db().execute(
        "SELECT * FROM temperatura_registros WHERE zona_id = ? ORDER BY id DESC LIMIT 1",
        (zona_id,),
    ).fetchone()


# ---------- TURNOS ----------
# Hay solo DOS turnos al día:
#   AM = desde que abre hasta las 11:59   |   PM = desde las 12:00 hasta el cierre del día.
# En cada turno se toma UNA sola lectura por zona. Si el turno se cierra sin lectura
# (por ejemplo, la droguería no abrió en la mañana), esa lectura simplemente NO se toma:
# la alarma deja de sonar y no queda pendiente para el otro turno.
HORA_CAMBIO_TURNO = 12


def turno_de_hh(hh):
    """Dada una hora (0-23) devuelve 'am' o 'pm'."""
    return "am" if hh < HORA_CAMBIO_TURNO else "pm"


def _fin_del_turno(turno, ahora_dt):
    """Momento en que se cierra el turno: el AM a las 12:00; el PM al terminar el día."""
    if turno == "am":
        return ahora_dt.replace(hour=HORA_CAMBIO_TURNO, minute=0, second=0, microsecond=0)
    return ahora_dt.replace(hour=23, minute=59, second=59, microsecond=0)


def _pendientes():
    """Lecturas que HOY están pendientes: ya llegó su hora, el turno sigue abierto
    y todavía no se registró la lectura de ese turno. Devuelve a lo sumo una por zona y turno."""
    db = get_db()
    ahora_dt = datetime.now()
    dia_semana = ahora_dt.isoweekday()
    pendientes = []

    zonas = db.execute("SELECT * FROM zonas_temperatura WHERE activa = 1").fetchall()
    for zona in zonas:
        if str(dia_semana) not in (zona["dias_semana"] or "").split(","):
            continue

        # Leemos los horarios de la zona y los ordenamos de menor a mayor.
        programadas = []
        for hora in (zona["horarios"] or "").split(","):
            hora = hora.strip()
            try:
                hh, mm = map(int, hora.split(":"))
            except ValueError:
                continue
            programadas.append((hh, mm, hora))
        programadas.sort()

        turnos_vistos = set()
        for hh, mm, hora in programadas:
            turno = turno_de_hh(hh)
            # Una sola lectura por turno: si la zona tiene dos horas en el mismo turno,
            # manda la primera.
            if turno in turnos_vistos:
                continue
            turnos_vistos.add(turno)

            programada = ahora_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            tolerancia = zona["minutos_tolerancia"] or 0

            # Todavía no es hora de avisar.
            if ahora_dt < programada + timedelta(minutes=tolerancia):
                continue
            # El turno ya se cerró: esa lectura no se toma y la alarma no debe sonar más.
            if ahora_dt >= _fin_del_turno(turno, ahora_dt):
                continue
            # Ya se registró la lectura de este turno.
            if _ya_registro_turno_hoy(zona["id"], turno):
                continue

            pendientes.append({
                "zona_id": zona["id"],
                "zona": zona["nombre"],
                "hora": hora,
                "turno": turno,
                "programada_para": programada.strftime("%Y-%m-%d %H:%M"),
            })
    return pendientes

# ---------- Rutas ----------

@bp.route("/")
@login_required
def inicio():
    db = get_db()
    zonas = db.execute("SELECT * FROM zonas_temperatura ORDER BY activa DESC, nombre").fetchall()
    resumen = []
    for zona in zonas:
        ultima = _ultima_lectura(zona["id"])
        resumen.append({"zona": zona, "ultima": ultima})
    return render_template("temperaturas/inicio.html", resumen=resumen)


@bp.route("/zonas")
@login_required
@roles_required("administrador", "director_tecnico")
def zonas_lista():
    filas = get_db().execute(
        "SELECT z.*, "
        "(SELECT COUNT(*) FROM temperatura_registros r WHERE r.zona_id = z.id) AS lecturas "
        "FROM zonas_temperatura z "
        "ORDER BY z.activa DESC, z.nombre COLLATE NOCASE"
    ).fetchall()
    return render_template("temperaturas/zonas_lista.html", zonas=filas)


@bp.route("/zonas/<int:zona_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def zonas_editar(zona_id):
    zona = _obtener_zona(zona_id)
    if request.method == "POST":
        try:
            temp_min = float(request.form.get("temp_min", "").replace(",", "."))
            temp_max = float(request.form.get("temp_max", "").replace(",", "."))
        except ValueError:
            flash("Temperaturas inválidas.", "error")
            return render_template("temperaturas/zonas_form.html", zona=zona)

        controla_humedad = 1 if request.form.get("controla_humedad") else 0
        humedad_min = humedad_max = None
        if controla_humedad:
            try:
                humedad_min = float(request.form.get("humedad_min", "").replace(",", ".")) if request.form.get("humedad_min") else None
                humedad_max = float(request.form.get("humedad_max", "").replace(",", ".")) if request.form.get("humedad_max") else None
            except ValueError:
                flash("Humedades inválidas.", "error")
                return render_template("temperaturas/zonas_form.html", zona=zona)

        horarios = ",".join(h.strip() for h in request.form.get("horarios", "").split(",") if h.strip())
        dias = ",".join(d for d in request.form.getlist("dias") if d in "1234567")
        minutos = int(request.form.get("minutos_tolerancia", 30) or 30)

        db = get_db()
        db.execute(
            "UPDATE zonas_temperatura SET descripcion=?, temp_min=?, temp_max=?, controla_humedad=?, "
            "humedad_min=?, humedad_max=?, horarios=?, dias_semana=?, minutos_tolerancia=?, actualizado_en=? "
            "WHERE id=?",
            (request.form.get("descripcion", "").strip() or None, temp_min, temp_max, controla_humedad,
             humedad_min, humedad_max, horarios, dias, minutos, ahora(), zona_id),
        )
        db.commit()
        registrar("zona_temperatura_editada", "zonas_temperatura", zona_id,
                  f"zona={zona['nombre']} rango={temp_min}-{temp_max}")
        flash("Zona actualizada.", "ok")
        return redirect(url_for("temperaturas.zonas_lista"))
    return render_template("temperaturas/zonas_form.html", zona=zona)


@bp.route("/zonas/<int:zona_id>/activar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def zonas_activar(zona_id):
    zona = _obtener_zona(zona_id)
    nuevo = 0 if zona["activa"] else 1
    db = get_db()
    db.execute("UPDATE zonas_temperatura SET activa=?, actualizado_en=? WHERE id=?",
               (nuevo, ahora(), zona_id))
    db.commit()
    registrar("zona_temperatura_activada" if nuevo else "zona_temperatura_desactivada",
              "zonas_temperatura", zona_id, f"zona={zona['nombre']}")
    flash("Zona activada." if nuevo else "Zona desactivada.", "ok")
    return redirect(url_for("temperaturas.zonas_lista"))

@bp.route("/zonas/nueva", methods=["GET", "POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def zonas_nueva():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None

        try:
            temp_min = float(request.form.get("temp_min", "").replace(",", "."))
            temp_max = float(request.form.get("temp_max", "").replace(",", "."))
        except ValueError:
            flash("Temperaturas inválidas.", "error")
            return render_template("temperaturas/zonas_form.html", zona=None)

        if not nombre:
            flash("El nombre de la zona es obligatorio.", "error")
            return render_template("temperaturas/zonas_form.html", zona=None)
        if temp_min >= temp_max:
            flash("La temperatura mínima debe ser menor que la máxima.", "error")
            return render_template("temperaturas/zonas_form.html", zona=None)

        controla_humedad = 1 if request.form.get("controla_humedad") else 0
        humedad_min = humedad_max = None
        if controla_humedad:
            try:
                humedad_min = float(request.form.get("humedad_min", "").replace(",", ".")) if request.form.get("humedad_min") else None
                humedad_max = float(request.form.get("humedad_max", "").replace(",", ".")) if request.form.get("humedad_max") else None
            except ValueError:
                flash("Humedades inválidas.", "error")
                return render_template("temperaturas/zonas_form.html", zona=None)

        horarios = ",".join(h.strip() for h in request.form.get("horarios", "").split(",") if h.strip())
        dias = ",".join(d for d in request.form.getlist("dias") if d in "1234567")
        minutos = int(request.form.get("minutos_tolerancia", 30) or 30)

        db = get_db()
        try:
            cur = db.execute(
                "INSERT INTO zonas_temperatura (nombre, descripcion, temp_min, temp_max, controla_humedad, "
                "humedad_min, humedad_max, horarios, dias_semana, activa, minutos_tolerancia, creado_en) "
                "VALUES (?,?,?,?,?,?,?,?,?, 1, ?, ?)",
                (nombre, descripcion, temp_min, temp_max, controla_humedad,
                 humedad_min, humedad_max, horarios or "09:00,18:00", dias or "1,2,3,4,5,6,7",
                 minutos, ahora()),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Ya existe una zona con ese nombre.", "error")
            return render_template("temperaturas/zonas_form.html", zona=None)

        registrar("zona_temperatura_creada", "zonas_temperatura", cur.lastrowid,
                  f"zona={nombre} rango={temp_min}-{temp_max}")
        flash(f"Zona '{nombre}' creada.", "ok")
        return redirect(url_for("temperaturas.zonas_lista"))

    return render_template("temperaturas/zonas_form.html", zona=None)


@bp.route("/zonas/<int:zona_id>/eliminar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def zonas_eliminar(zona_id):
    zona = _obtener_zona(zona_id)
    db = get_db()

    lecturas = db.execute(
        "SELECT COUNT(*) FROM temperatura_registros WHERE zona_id = ?", (zona_id,)
    ).fetchone()[0]

    if lecturas > 0:
        flash(
            f"No se puede eliminar '{zona['nombre']}': tiene {lecturas} lecturas registradas. "
            "Desactívala en su lugar.",
            "error",
        )
        return redirect(url_for("temperaturas.zonas_lista"))

    db.execute("DELETE FROM zonas_temperatura WHERE id = ?", (zona_id,))
    db.commit()
    registrar("zona_temperatura_eliminada", "zonas_temperatura", zona_id,
              f"zona={zona['nombre']}")
    flash(f"Zona '{zona['nombre']}' eliminada.", "ok")
    return redirect(url_for("temperaturas.zonas_lista"))

def _turno_de_hora(hora_str):
    """Devuelve 'am' o 'pm' según una hora escrita como 'HH:MM'."""
    try:
        hh, _mm = map(int, hora_str.split(":"))
    except (ValueError, AttributeError):
        return "am"
    return turno_de_hh(hh)


def _turno_actual(zona=None):
    """Turno en el que estamos ahora, según el reloj: antes de las 12:00 es AM, después PM.
    (El parámetro `zona` se conserva por compatibilidad, pero ya no se usa: antes se
    elegía la hora programada más cercana y eso daba el turno equivocado.)"""
    return turno_de_hh(datetime.now().hour)


def _ya_registro_turno_hoy(zona_id, turno):
    """Verifica si ya existe una lectura hoy en el turno dado."""
    hoy = datetime.now().date().isoformat()
    registros = get_db().execute(
        "SELECT fecha FROM temperatura_registros "
        "WHERE zona_id = ? AND fecha LIKE ?",
        (zona_id, f"{hoy}%"),
    ).fetchall()

    for r in registros:
        # Extraer la hora del campo fecha (formato YYYY-MM-DD HH:MM:SS)
        try:
            hora = int(r["fecha"][11:13])
        except (ValueError, TypeError):
            continue
        if turno_de_hh(hora) == turno:
            return True
    return False


@bp.route("/registrar/<int:zona_id>", methods=["GET", "POST"])
@login_required
def registrar_lectura(zona_id):
    zona = _obtener_zona(zona_id)
    if not zona["activa"]:
        flash("Esa zona está desactivada.", "error")
        return redirect(url_for("temperaturas.inicio"))

    turno = _turno_actual(zona)
    turno_txt = {"am": "mañana", "pm": "tarde"}.get(turno, turno)

    # ¿Ya registró este turno hoy?
    if _ya_registro_turno_hoy(zona_id, turno):
        flash(
            f"Ya registraste la temperatura de la {turno_txt} hoy para esta zona. "
            f"Solo se permite una lectura por turno.",
            "error"
        )
        return redirect(url_for("temperaturas.inicio"))

    if request.method == "POST":
        try:
            temp = float(request.form.get("temperatura", "").replace(",", "."))
        except ValueError:
            flash("Temperatura inválida.", "error")
            return render_template("temperaturas/registrar.html", zona=zona, turno=turno_txt)

        humedad = None
        if zona["controla_humedad"]:
            try:
                h = request.form.get("humedad", "").strip().replace(",", ".")
                humedad = float(h) if h else None
            except ValueError:
                flash("Humedad inválida.", "error")
                return render_template("temperaturas/registrar.html", zona=zona, turno=turno_txt)

        en_rango = _en_rango(zona, temp, humedad)
        accion = request.form.get("accion_correctiva", "").strip() or None
        if not en_rango and not accion:
            flash("La lectura está fuera de rango. Debes describir la acción correctiva antes de guardar.", "error")
            return render_template("temperaturas/registrar.html", zona=zona, turno=turno_txt)

        programada = request.form.get("programada_para", "").strip() or None
        observaciones = request.form.get("observaciones", "").strip() or None

        db = get_db()
        cur = db.execute(
            "INSERT INTO temperatura_registros (zona_id, fecha, programada_para, temperatura, humedad, "
            "dentro_de_rango, accion_correctiva, observaciones, usuario_id, usuario_nombre, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (zona_id, ahora(), programada, temp, humedad, 1 if en_rango else 0, accion,
             observaciones, g.user["id"], g.user["nombre"], ahora()),
        )
        db.commit()
        registrar("temperatura_registrada", "temperatura_registros", cur.lastrowid,
                  f"zona={zona['nombre']} turno={turno} temp={temp} humedad={humedad} en_rango={en_rango}")
        if en_rango:
            flash(f"Lectura de la {turno_txt} registrada correctamente.", "ok")
        else:
            flash(f"Lectura de la {turno_txt} registrada FUERA DE RANGO. Acción correctiva guardada.", "error")
        return redirect(url_for("temperaturas.inicio"))

    return render_template("temperaturas/registrar.html", zona=zona, turno=turno_txt)


@bp.route("/historial")
@login_required
def historial():
    zona_id = request.args.get("zona_id", type=int)
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    solo_fuera = request.args.get("fuera", "") == "1"
    cond, params = [], []
    if zona_id:
        cond.append("r.zona_id = ?")
        params.append(zona_id)
    if desde:
        cond.append("r.fecha >= ?")
        params.append(desde + " 00:00:00")
    if hasta:
        cond.append("r.fecha <= ?")
        params.append(hasta + " 23:59:59")
    if solo_fuera:
        cond.append("r.dentro_de_rango = 0")
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    filas = get_db().execute(
        f"SELECT r.*, z.nombre AS zona_nombre FROM temperatura_registros r "
        f"JOIN zonas_temperatura z ON z.id = r.zona_id "
        f"{where} ORDER BY r.id DESC LIMIT 500",
        params,
    ).fetchall()
    zonas = get_db().execute("SELECT id, nombre FROM zonas_temperatura ORDER BY nombre").fetchall()
    return render_template("temperaturas/historial.html",
                           filas=filas, zonas=zonas, zona_id=zona_id,
                           desde=desde, hasta=hasta, solo_fuera=solo_fuera)


@bp.route("/api/pendientes")
@login_required
def api_pendientes():
    """Endpoint que el cliente consulta periódicamente para disparar la alarma."""
    return jsonify({"pendientes": _pendientes()})