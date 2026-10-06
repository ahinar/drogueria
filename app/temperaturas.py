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


def _pendientes():
    """Devuelve las zonas cuya próxima lectura programada ya venció y no se ha registrado."""
    db = get_db()
    ahora_dt = datetime.now()
    hoy = ahora_dt.date().isoformat()
    dia_semana = ahora_dt.isoweekday()
    pendientes = []
    zonas = db.execute("SELECT * FROM zonas_temperatura WHERE activa = 1").fetchall()

    for zona in zonas:
        # Verificar si hoy aplica según el día de la semana
        if str(dia_semana) not in (zona["dias_semana"] or "").split(","):
            continue

        horarios = [h.strip() for h in (zona["horarios"] or "").split(",") if h.strip()]
        for hora in horarios:
            try:
                hh, mm = map(int, hora.split(":"))
            except ValueError:
                continue
            programada = ahora_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            tolerancia = zona["minutos_tolerancia"] or 30

            # Solo pendiente si ya pasó la hora + tolerancia
            if ahora_dt < programada + timedelta(minutes=tolerancia):
                continue

            # ¿Hay alguna lectura para esta zona hoy DESPUÉS de la hora programada?
            existe = db.execute(
                "SELECT 1 FROM temperatura_registros "
                "WHERE zona_id = ? AND fecha >= ? AND fecha LIKE ? LIMIT 1",
                (zona["id"],
                 programada.isoformat(sep=" ", timespec="seconds"),
                 f"{hoy}%"),
            ).fetchone()
            if existe:
                continue
            pendientes.append({
                "zona_id": zona["id"],
                "zona": zona["nombre"],
                "hora": hora,
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

@bp.route("/registrar/<int:zona_id>", methods=["GET", "POST"])
@login_required
def registrar_lectura(zona_id):
    zona = _obtener_zona(zona_id)
    if not zona["activa"]:
        flash("Esa zona está desactivada.", "error")
        return redirect(url_for("temperaturas.inicio"))
    if request.method == "POST":
        try:
            temp = float(request.form.get("temperatura", "").replace(",", "."))
        except ValueError:
            flash("Temperatura inválida.", "error")
            return render_template("temperaturas/registrar.html", zona=zona)

        humedad = None
        if zona["controla_humedad"]:
            try:
                h = request.form.get("humedad", "").strip().replace(",", ".")
                humedad = float(h) if h else None
            except ValueError:
                flash("Humedad inválida.", "error")
                return render_template("temperaturas/registrar.html", zona=zona)

        en_rango = _en_rango(zona, temp, humedad)
        accion = request.form.get("accion_correctiva", "").strip() or None
        if not en_rango and not accion:
            flash("La lectura está fuera de rango. Debes describir la acción correctiva antes de guardar.", "error")
            return render_template("temperaturas/registrar.html", zona=zona)

        programada = request.form.get("programada_para", "").strip() or None
        observaciones = request.form.get("observaciones", "").strip() or None

        db = get_db()
        cur = db.execute(
            "INSERT INTO temperatura_registros (zona_id, fecha, programada_para, temperatura, humedad, "
            "dentro_de_rango, accion_correctiva, observaciones, usuario_id, usuario_nombre, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (zona_id, ahora(), programada, temp, humedad, 1 if en_rango else 0, accion,
             observaciones, g.user["id"], g.user["usuario"], ahora()),
        )
        db.commit()
        registrar("temperatura_registrada", "temperatura_registros", cur.lastrowid,
                  f"zona={zona['nombre']} temp={temp} humedad={humedad} en_rango={en_rango}")
        if en_rango:
            flash("Lectura registrada correctamente.", "ok")
        else:
            flash("Lectura registrada FUERA DE RANGO. Acción correctiva guardada.", "error")
        return redirect(url_for("temperaturas.inicio"))
    return render_template("temperaturas/registrar.html", zona=zona)


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