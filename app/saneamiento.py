"""
SANEAMIENTO (Fase 4.2): limpieza, control de plagas y residuos
=============================================================

PARA QUÉ (para aprender):
    En la visita, la Secretaría de Salud pide ver que la droguería está limpia
    Y que hay REGISTROS de eso. Este módulo tiene tres partes:

    1. LIMPIEZA
       - Tareas: qué se limpia y cada cuánto (diaria, semanal, quincenal o
         mensual). Vienen cargadas las tres de Fernando: pisos (diaria),
         estanterías (semanal) y nevera (mensual).
       - Planilla: cada vez que alguien hace una tarea, la marca con un toque.
         Queda el día y quién la hizo. La planilla del mes se imprime en PDF.
       - "Período": para una tarea semanal, basta con hacerla UNA vez en la
         semana (lunes a domingo); para una mensual, una vez en el mes, etc.

    2. CONTROL DE PLAGAS
       Cada fumigación: fecha, empresa, número y archivo del certificado y la
       fecha de la siguiente (6 meses por defecto). Avisa en el Inicio.

    3. RESIDUOS (Resolución 591 de 2024 de MinSalud y MinAmbiente)
       - Registro de lo que se genera, por TIPO y en KILOS (se consolida por
         mes: es el formato que pide la norma).
       - Entregas a la empresa GESTORA autorizada, con su certificado.
       - "Dar de baja vencidos": saca del inventario los lotes vencidos y los
         registra como residuo farmacéutico en un solo paso.

QUIÉN PUEDE:
    Marcar limpieza y registrar residuos generados: todos.
    Tareas, plagas, entregas al gestor y baja de vencidos: administrador y DT.

TABLAS (migración 31 en app/db.py): limpieza_tareas, limpieza_registros,
control_plagas, residuos_registros, residuos_entregas.
"""
import calendar
from datetime import date, datetime, timedelta
from io import BytesIO

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   send_file, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .equipos import estado_calibracion, sumar_meses
from .utils_imagenes import guardar_documento

bp = Blueprint("saneamiento", __name__, url_prefix="/saneamiento")

JEFES = ("administrador", "director_tecnico")

# ----------------------------------------------------------------------
# Catálogos (lo que se muestra en las listas desplegables)
# ----------------------------------------------------------------------

FRECUENCIAS = {
    "diaria": "Diaria",
    "semanal": "Semanal",
    "quincenal": "Quincenal",
    "mensual": "Mensual",
}

TIPOS_PLAGA = {
    "integral": "Control integrado de plagas",
    "insectos": "Fumigación (insectos)",
    "roedores": "Desratización (roedores)",
    "desinfeccion": "Desinfección ambiental",
}
MESES_PLAGAS = 6                 # la siguiente fumigación se sugiere 6 meses después

# Tipos de residuo (clasificación de la Resolución 591 de 2024, simplificada).
# El segundo dato dice si es PELIGROSO: esos deben ir a un gestor autorizado.
TIPOS_RESIDUO = {
    "farmaceuticos": ("Medicamentos vencidos, deteriorados o parcialmente usados", True),
    "cortopunzantes": ("Cortopunzantes (agujas, lancetas)", True),
    "biosanitarios": ("Biosanitarios (algodón, gasas con fluidos)", True),
    "quimicos": ("Otros químicos (envases de desinfectantes, termómetros de mercurio)", True),
    "aprovechables": ("Aprovechables (cartón, papel, plástico)", False),
    "ordinarios": ("No aprovechables (ordinarios)", False),
}
PELIGROSOS = tuple(k for k, (_, peligroso) in TIPOS_RESIDUO.items() if peligroso)
DIAS_MAX_ALMACEN = 90            # residuos peligrosos guardados más de 90 días -> aviso

MESES_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
            "septiembre", "octubre", "noviembre", "diciembre"]


# ----------------------------------------------------------------------
# Ayudas de fechas
# ----------------------------------------------------------------------

def periodo(frecuencia, dia):
    """El período al que pertenece un día, según la frecuencia: (inicio, fin).

    diaria    -> ese mismo día
    semanal   -> de lunes a domingo
    quincenal -> del 1 al 15, o del 16 al fin de mes
    mensual   -> todo el mes
    """
    if frecuencia == "semanal":
        inicio = dia - timedelta(days=dia.weekday())          # weekday(): lunes = 0
        return inicio, inicio + timedelta(days=6)
    ultimo = calendar.monthrange(dia.year, dia.month)[1]
    if frecuencia == "quincenal":
        if dia.day <= 15:
            return dia.replace(day=1), dia.replace(day=15)
        return dia.replace(day=16), dia.replace(day=ultimo)
    if frecuencia == "mensual":
        return dia.replace(day=1), dia.replace(day=ultimo)
    return dia, dia                                            # diaria


def _mes(texto):
    """'2026-10' -> date(2026, 10, 1). Vacío o malo -> el mes actual."""
    try:
        return datetime.strptime(texto or "", "%Y-%m").date()
    except ValueError:
        return date.today().replace(day=1)


def _fecha_form(nombre, defecto=None):
    try:
        return date.fromisoformat(request.form.get(nombre) or "")
    except ValueError:
        return defecto


def _numero(nombre):
    """Lee un número del formulario aceptando coma decimal ('1,5' -> 1.5). Malo -> None."""
    try:
        return float((request.form.get(nombre) or "").replace(",", "."))
    except ValueError:
        return None


def _es_jefe():
    return g.user["rol"] in JEFES


# ======================================================================
# 1. LIMPIEZA
# ======================================================================

def estado_tareas(hoy=None):
    """Tareas activas con su estado en el período ACTUAL.

    Cada tarea trae: hecho (el registro de este período o None), inicio y fin
    del período y cuántos días le quedan.
    """
    hoy = hoy or date.today()
    db = get_db()
    tareas = []
    for t in db.execute("SELECT * FROM limpieza_tareas WHERE activa = 1 ORDER BY orden, id").fetchall():
        inicio, fin = periodo(t["frecuencia"], hoy)
        hecho = db.execute("SELECT * FROM limpieza_registros WHERE tarea_id = ? AND fecha BETWEEN ? AND ? "
                           "ORDER BY fecha DESC LIMIT 1",
                           (t["id"], inicio.isoformat(), fin.isoformat())).fetchone()
        tareas.append(dict(t, hecho=hecho, inicio=inicio, fin=fin, quedan=(fin - hoy).days,
                           frecuencia_texto=FRECUENCIAS[t["frecuencia"]]))
    return tareas


def limpieza_pendiente_para_aviso(ahora_dt=None):
    """Tareas que conviene recordar en el Inicio (las usa app/alertas.py).

    No se avisa de todo desde temprano (sería ruido): las diarias desde las
    3 p. m., las semanales cuando queda 1 día de la semana, las quincenales
    cuando quedan 2 y las mensuales cuando quedan 3.
    """
    ahora_dt = ahora_dt or datetime.now()
    hoy = ahora_dt.date()
    margen = {"semanal": 1, "quincenal": 2, "mensual": 3}
    pendientes = []
    for t in estado_tareas(hoy):
        if t["hecho"]:
            continue
        if t["frecuencia"] == "diaria":
            if ahora_dt.hour >= 15:
                pendientes.append(t)
        elif t["quedan"] <= margen[t["frecuencia"]]:
            pendientes.append(t)
    return pendientes


def planilla_mes(primero, hoy=None):
    """Datos de la planilla de un mes: una fila por tarea y una casilla por día.

    Devuelve (dias, filas). Cada fila: tarea, marcas {día: registro} y el
    cumplimiento = períodos con la tarea hecha / períodos ya transcurridos.
    """
    hoy = hoy or date.today()
    ultimo = calendar.monthrange(primero.year, primero.month)[1]
    dias = [primero.replace(day=d) for d in range(1, ultimo + 1)]
    db = get_db()
    # Se traen registros desde una semana antes y hasta una después: una semana
    # puede empezar en el mes anterior o terminar en el siguiente.
    desde = (dias[0] - timedelta(days=7)).isoformat()
    hasta = (dias[-1] + timedelta(days=7)).isoformat()
    filas = []
    tareas = db.execute("SELECT * FROM limpieza_tareas ORDER BY activa DESC, orden, id").fetchall()
    for t in tareas:
        regs = db.execute("SELECT * FROM limpieza_registros WHERE tarea_id = ? AND fecha BETWEEN ? AND ?",
                          (t["id"], desde, hasta)).fetchall()
        por_fecha = {r["fecha"]: r for r in regs}
        marcas = {d.day: por_fecha[d.isoformat()] for d in dias if d.isoformat() in por_fecha}
        # Cumplimiento: solo los días que ya pasaron (o hoy) y desde que existe
        # la tarea (no se le cobra a una tarea nueva lo que pasó antes de crearla)
        creada = date.fromisoformat(t["creado_en"][:10])
        periodos = {periodo(t["frecuencia"], d) for d in dias if creada <= d <= hoy}
        hechos = sum(1 for (i, f) in periodos
                     if any(i.isoformat() <= fecha <= f.isoformat() for fecha in por_fecha))
        # Si la tarea está inactiva y no tiene marcas este mes, no se muestra
        if not t["activa"] and not marcas:
            continue
        filas.append({"tarea": t, "marcas": marcas, "periodos": len(periodos), "hechos": hechos,
                      "frecuencia_texto": FRECUENCIAS[t["frecuencia"]]})
    return dias, filas


@bp.route("/")
@login_required
def inicio():
    return redirect(url_for("saneamiento.limpieza"))


@bp.route("/limpieza")
@login_required
def limpieza():
    primero = _mes(request.args.get("mes"))
    dias, filas = planilla_mes(primero)
    hoy = date.today()
    anterior = (primero - timedelta(days=1)).replace(day=1)
    siguiente = (primero + timedelta(days=32)).replace(day=1)
    return render_template("saneamiento/limpieza.html", tareas=estado_tareas(hoy), dias=dias, filas=filas,
                           primero=primero, mes_texto=f"{MESES_ES[primero.month]} {primero.year}",
                           anterior=anterior.strftime("%Y-%m"),
                           siguiente=siguiente.strftime("%Y-%m") if siguiente <= hoy else None,
                           hoy=hoy, minimo=(hoy - timedelta(days=7)).isoformat(), pestana="limpieza")


@bp.route("/limpieza/marcar", methods=["POST"])
@login_required
def limpieza_marcar():
    """Marca una tarea como hecha en un día (por defecto, hoy)."""
    volver = redirect(request.referrer or url_for("saneamiento.limpieza"))
    tarea = get_db().execute("SELECT * FROM limpieza_tareas WHERE id = ?",
                             (request.form.get("tarea_id", type=int),)).fetchone()
    if tarea is None or not tarea["activa"]:
        flash("Esa tarea no existe o está inactiva.", "error")
        return volver
    hoy = date.today()
    fecha = _fecha_form("fecha", hoy)
    if fecha > hoy:
        flash("No se puede marcar una limpieza en una fecha futura.", "error")
        return volver
    # Los auxiliares pueden ponerse al día hasta 7 días atrás; el jefe, cualquier fecha
    if not _es_jefe() and fecha < hoy - timedelta(days=7):
        flash("Solo se pueden marcar limpiezas de los últimos 7 días.", "error")
        return volver
    db = get_db()
    if db.execute("SELECT 1 FROM limpieza_registros WHERE tarea_id = ? AND fecha = ?",
                  (tarea["id"], fecha.isoformat())).fetchone():
        flash(f"«{tarea['nombre']}» ya estaba marcada el {fecha.strftime('%d/%m/%Y')}.", "ok")
        return volver
    cur = db.execute("INSERT INTO limpieza_registros (tarea_id, fecha, observaciones, usuario_id, usuario_nombre, "
                     "creado_en) VALUES (?,?,?,?,?,?)",
                     (tarea["id"], fecha.isoformat(), (request.form.get("observaciones") or "").strip() or None,
                      g.user["id"], g.user["nombre"], ahora()))
    db.commit()
    registrar("limpieza_hecha", "limpieza_registros", cur.lastrowid, f"{tarea['nombre']} fecha={fecha}")
    flash(f"Listo: «{tarea['nombre']}» quedó registrada el {fecha.strftime('%d/%m/%Y')}.", "ok")
    return volver


@bp.route("/limpieza/<int:registro_id>/quitar", methods=["POST"])
@login_required
def limpieza_quitar(registro_id):
    """Quita una marca puesta por error: quien la puso (el mismo día) o el jefe."""
    volver = redirect(request.referrer or url_for("saneamiento.limpieza"))
    db = get_db()
    r = db.execute("SELECT r.*, t.nombre FROM limpieza_registros r JOIN limpieza_tareas t ON t.id = r.tarea_id "
                   "WHERE r.id = ?", (registro_id,)).fetchone()
    if r is None:
        abort(404)
    propio = r["usuario_id"] == g.user["id"] and r["creado_en"][:10] == date.today().isoformat()
    if not (_es_jefe() or propio):
        flash("Solo quien la marcó (el mismo día) o el director técnico pueden quitar esa marca.", "error")
        return volver
    db.execute("DELETE FROM limpieza_registros WHERE id = ?", (registro_id,))
    db.commit()
    # Queda en la bitácora quién la quitó y qué decía
    registrar("limpieza_quitada", "limpieza_registros", registro_id,
              f"{r['nombre']} fecha={r['fecha']} la había marcado {r['usuario_nombre']}")
    flash("Marca quitada.", "ok")
    return volver


# ---------- Tareas de limpieza (administrador y DT) ----------

def _leer_tarea():
    return {
        "nombre": (request.form.get("nombre") or "").strip(),
        "area": (request.form.get("area") or "").strip() or None,
        "frecuencia": request.form.get("frecuencia") or "diaria",
        "producto": (request.form.get("producto") or "").strip() or None,
        "instrucciones": (request.form.get("instrucciones") or "").strip() or None,
        "orden": request.form.get("orden", type=int) or 0,
    }


def _validar_tarea(datos):
    errores = []
    if not datos["nombre"]:
        errores.append("Escribe qué se limpia (ej: Baño, Mostrador).")
    if datos["frecuencia"] not in FRECUENCIAS:
        errores.append("Frecuencia no válida.")
    return errores


@bp.route("/limpieza/tareas", methods=["GET", "POST"])
@roles_required(*JEFES)
def tareas():
    """Lista de tareas + formulario para crear una nueva."""
    datos = None
    if request.method == "POST":
        datos = _leer_tarea()
        errores = _validar_tarea(datos)
        if not errores:
            db = get_db()
            if not datos["orden"]:
                datos["orden"] = (db.execute("SELECT MAX(orden) m FROM limpieza_tareas").fetchone()["m"] or 0) + 1
            cur = db.execute("INSERT INTO limpieza_tareas (nombre, area, frecuencia, producto, instrucciones, orden, "
                             "activa, creado_en) VALUES (?,?,?,?,?,?,1,?)",
                             (datos["nombre"], datos["area"], datos["frecuencia"], datos["producto"],
                              datos["instrucciones"], datos["orden"], ahora()))
            db.commit()
            registrar("limpieza_tarea_creada", "limpieza_tareas", cur.lastrowid, datos["nombre"])
            flash(f"Tarea «{datos['nombre']}» creada.", "ok")
            return redirect(url_for("saneamiento.tareas"))
        for e in errores:
            flash(e, "error")
    lista = get_db().execute("SELECT * FROM limpieza_tareas ORDER BY activa DESC, orden, id").fetchall()
    return render_template("saneamiento/tareas.html", tareas=lista, frecuencias=FRECUENCIAS, datos=datos or {},
                           pestana="limpieza")


@bp.route("/limpieza/tareas/<int:tarea_id>", methods=["GET", "POST"])
@roles_required(*JEFES)
def tarea_editar(tarea_id):
    db = get_db()
    tarea = db.execute("SELECT * FROM limpieza_tareas WHERE id = ?", (tarea_id,)).fetchone()
    if tarea is None:
        abort(404)
    if request.method == "POST":
        if request.form.get("accion") == "activar":
            # Desactivar o volver a activar (nunca se borra: su planilla se conserva)
            db.execute("UPDATE limpieza_tareas SET activa = ?, actualizado_en = ? WHERE id = ?",
                       (0 if tarea["activa"] else 1, ahora(), tarea_id))
            db.commit()
            registrar("limpieza_tarea_" + ("desactivada" if tarea["activa"] else "activada"), "limpieza_tareas",
                      tarea_id, tarea["nombre"])
            flash("Tarea desactivada (su historial se conserva)." if tarea["activa"] else "Tarea activada.", "ok")
            return redirect(url_for("saneamiento.tareas"))
        datos = _leer_tarea()
        errores = _validar_tarea(datos)
        if not errores:
            db.execute("UPDATE limpieza_tareas SET nombre=?, area=?, frecuencia=?, producto=?, instrucciones=?, "
                       "orden=?, actualizado_en=? WHERE id=?",
                       (datos["nombre"], datos["area"], datos["frecuencia"], datos["producto"],
                        datos["instrucciones"], datos["orden"] or tarea["orden"], ahora(), tarea_id))
            db.commit()
            registrar("limpieza_tarea_editada", "limpieza_tareas", tarea_id, datos["nombre"])
            flash("Tarea actualizada.", "ok")
            return redirect(url_for("saneamiento.tareas"))
        for e in errores:
            flash(e, "error")
        tarea = dict(tarea, **datos)
    return render_template("saneamiento/tarea_form.html", tarea=tarea, frecuencias=FRECUENCIAS, pestana="limpieza")


# ======================================================================
# 2. CONTROL DE PLAGAS
# ======================================================================

def estado_plagas(hoy=None):
    """Estado del control de plagas según la ÚLTIMA fumigación registrada.

    Devuelve (estado, ultima, dias): estado = 'sin' | 'vencida' | 'por_vencer' | 'al_dia'.
    """
    ultima = get_db().execute("SELECT * FROM control_plagas ORDER BY fecha DESC, id DESC LIMIT 1").fetchone()
    if ultima is None:
        return "sin", None, None
    estado, dias = estado_calibracion(ultima["proxima"], hoy)
    return estado, ultima, dias


@bp.route("/plagas", methods=["GET", "POST"])
@login_required
def plagas():
    hoy = date.today()
    if request.method == "POST":
        if not _es_jefe():
            abort(403)
        volver = redirect(url_for("saneamiento.plagas"))
        fecha = _fecha_form("fecha")
        tipo = request.form.get("tipo") if request.form.get("tipo") in TIPOS_PLAGA else "integral"
        empresa = (request.form.get("empresa") or "").strip()
        if fecha is None or fecha > hoy:
            flash("Indica la fecha de la fumigación (no puede ser futura).", "error")
            return volver
        if not empresa:
            flash("Escribe la empresa que hizo el control de plagas.", "error")
            return volver
        proxima = _fecha_form("proxima") or sumar_meses(fecha, MESES_PLAGAS)
        if proxima <= fecha:
            flash("La próxima fumigación debe ser después de esta.", "error")
            return volver
        archivo = None
        if request.files.get("certificado") and request.files["certificado"].filename:
            archivo, error = guardar_documento(request.files["certificado"], "saneamiento")
            if error:
                flash(f"No se guardó: {error}", "error")
                return volver
        db = get_db()
        cur = db.execute(
            "INSERT INTO control_plagas (fecha, tipo, empresa, certificado_numero, producto, areas, proxima, archivo, "
            "observaciones, usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fecha.isoformat(), tipo, empresa, (request.form.get("certificado_numero") or "").strip() or None,
             (request.form.get("producto") or "").strip() or None, (request.form.get("areas") or "").strip() or None,
             proxima.isoformat(), archivo, (request.form.get("observaciones") or "").strip() or None,
             g.user["id"], g.user["nombre"], ahora()))
        db.commit()
        registrar("control_plagas", "control_plagas", cur.lastrowid, f"{fecha} {empresa} proxima={proxima}")
        flash(f"Control de plagas registrado. Próximo: {proxima.strftime('%d/%m/%Y')}.", "ok")
        return volver

    estado, ultima, dias = estado_plagas(hoy)
    historial = get_db().execute("SELECT * FROM control_plagas ORDER BY fecha DESC, id DESC").fetchall()
    return render_template("saneamiento/plagas.html", estado=estado, ultima=ultima, dias=dias, historial=historial,
                           tipos=TIPOS_PLAGA, hoy=hoy.isoformat(),
                           proxima_sugerida=sumar_meses(hoy, MESES_PLAGAS).isoformat(), pestana="plagas")


# ======================================================================
# 3. RESIDUOS
# ======================================================================

def residuos_sin_entregar(hoy=None):
    """Residuos PELIGROSOS registrados después de la última entrega al gestor.

    Devuelve (kilos, fecha_mas_vieja). Sirve para el aviso del Inicio: no
    deben quedarse guardados mucho tiempo en la droguería.
    """
    db = get_db()
    ultima = db.execute("SELECT MAX(fecha) f FROM residuos_entregas").fetchone()["f"] or ""
    marcas = ",".join("?" * len(PELIGROSOS))
    fila = db.execute(f"SELECT SUM(cantidad_kg) kg, MIN(fecha) desde FROM residuos_registros "
                      f"WHERE tipo IN ({marcas}) AND fecha > ?", (*PELIGROSOS, ultima)).fetchone()
    return (fila["kg"] or 0), fila["desde"]


def _vencidos_en_inventario():
    """Lotes vencidos que todavía tienen unidades (para darlos de baja)."""
    return get_db().execute(
        "SELECT l.id, l.lote, l.vencimiento, l.cantidad_disponible, l.estado, p.nombre, p.codigo "
        "FROM lotes l JOIN productos p ON p.id = l.producto_id "
        "WHERE l.vencimiento IS NOT NULL AND l.vencimiento < ? AND l.cantidad_disponible > 0 "
        "AND l.estado IN ('disponible', 'bloqueado') ORDER BY l.vencimiento, p.nombre",
        (date.today().isoformat(),)).fetchall()


def resumen_residuos(primero):
    """Kilos por tipo en un mes (el consolidado mensual que pide la norma)."""
    ultimo = primero.replace(day=calendar.monthrange(primero.year, primero.month)[1])
    db = get_db()
    registros = db.execute("SELECT * FROM residuos_registros WHERE fecha BETWEEN ? AND ? ORDER BY fecha, id",
                           (primero.isoformat(), ultimo.isoformat())).fetchall()
    entregas = db.execute("SELECT * FROM residuos_entregas WHERE fecha BETWEEN ? AND ? ORDER BY fecha, id",
                          (primero.isoformat(), ultimo.isoformat())).fetchall()
    por_tipo = {k: 0.0 for k in TIPOS_RESIDUO}
    for r in registros:
        por_tipo[r["tipo"]] += r["cantidad_kg"]
    return registros, entregas, por_tipo


@bp.route("/residuos")
@login_required
def residuos():
    primero = _mes(request.args.get("mes"))
    registros, entregas, por_tipo = resumen_residuos(primero)
    hoy = date.today()
    kg_pendientes, desde = residuos_sin_entregar(hoy)
    anterior = (primero - timedelta(days=1)).replace(day=1)
    siguiente = (primero + timedelta(days=32)).replace(day=1)
    todas_entregas = get_db().execute("SELECT * FROM residuos_entregas ORDER BY fecha DESC, id DESC LIMIT 20").fetchall()
    return render_template(
        "saneamiento/residuos.html", registros=registros, entregas=entregas, todas_entregas=todas_entregas,
        por_tipo=por_tipo, tipos=TIPOS_RESIDUO, peligrosos=PELIGROSOS,
        total_peligrosos=sum(v for k, v in por_tipo.items() if k in PELIGROSOS),
        total_no_peligrosos=sum(v for k, v in por_tipo.items() if k not in PELIGROSOS),
        kg_pendientes=kg_pendientes, pendientes_desde=desde,
        vencidos=_vencidos_en_inventario() if _es_jefe() else [],
        primero=primero, mes_texto=f"{MESES_ES[primero.month]} {primero.year}",
        anterior=anterior.strftime("%Y-%m"), siguiente=siguiente.strftime("%Y-%m") if siguiente <= hoy else None,
        hoy=hoy.isoformat(), pestana="residuos")


@bp.route("/residuos/registro", methods=["POST"])
@login_required
def residuo_registrar():
    """Anota residuos generados (ej. 0,3 kg de cortopunzantes)."""
    volver = redirect(request.referrer or url_for("saneamiento.residuos"))
    tipo = request.form.get("tipo")
    cantidad = _numero("cantidad_kg")
    fecha = _fecha_form("fecha", date.today())
    if tipo not in TIPOS_RESIDUO:
        flash("Elige el tipo de residuo.", "error")
        return volver
    if not cantidad or cantidad <= 0 or cantidad > 1000:
        flash("Escribe cuántos kilos (ej: 0,5). Si no tienes balanza, haz un estimado.", "error")
        return volver
    if fecha > date.today():
        flash("La fecha no puede ser futura.", "error")
        return volver
    db = get_db()
    cur = db.execute("INSERT INTO residuos_registros (fecha, tipo, cantidad_kg, descripcion, usuario_id, "
                     "usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?)",
                     (fecha.isoformat(), tipo, round(cantidad, 3), (request.form.get("descripcion") or "").strip() or None,
                      g.user["id"], g.user["nombre"], ahora()))
    db.commit()
    registrar("residuo_registrado", "residuos_registros", cur.lastrowid, f"{tipo} {cantidad} kg")
    flash(f"Registrado: {cantidad:g} kg de {TIPOS_RESIDUO[tipo][0].lower()}.", "ok")
    return volver


@bp.route("/residuos/entrega", methods=["POST"])
@roles_required(*JEFES)
def residuo_entrega():
    """Entrega de residuos a la empresa gestora, con su certificado."""
    volver = redirect(url_for("saneamiento.residuos"))
    fecha = _fecha_form("fecha")
    gestor = (request.form.get("gestor") or "").strip()
    if fecha is None or fecha > date.today():
        flash("Indica la fecha de la entrega (no puede ser futura).", "error")
        return volver
    if not gestor:
        flash("Escribe el nombre de la empresa gestora.", "error")
        return volver
    archivo = None
    if request.files.get("certificado") and request.files["certificado"].filename:
        archivo, error = guardar_documento(request.files["certificado"], "saneamiento")
        if error:
            flash(f"No se guardó: {error}", "error")
            return volver
    tipos = ", ".join(TIPOS_RESIDUO[t][0].split(" (")[0] for t in request.form.getlist("tipos") if t in TIPOS_RESIDUO)
    db = get_db()
    cur = db.execute(
        "INSERT INTO residuos_entregas (fecha, gestor, gestor_nit, tipos, cantidad_kg, certificado_numero, archivo, "
        "observaciones, usuario_id, usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (fecha.isoformat(), gestor, (request.form.get("gestor_nit") or "").strip() or None, tipos or None,
         _numero("cantidad_kg"), (request.form.get("certificado_numero") or "").strip() or None, archivo,
         (request.form.get("observaciones") or "").strip() or None, g.user["id"], g.user["nombre"], ahora()))
    db.commit()
    registrar("residuos_entregados", "residuos_entregas", cur.lastrowid, f"{fecha} {gestor}")
    flash("Entrega al gestor registrada." + ("" if archivo else " Recuerda subir el certificado cuando te lo den."), "ok")
    return volver


@bp.route("/residuos/baja-vencidos", methods=["POST"])
@roles_required(*JEFES)
def baja_vencidos():
    """Saca del inventario los lotes vencidos elegidos y los anota como residuo farmacéutico.

    En el kardex queda un movimiento 'baja' por cada lote (Utilidades lo
    cuenta como pérdida) y en residuos un solo registro con el peso total.
    """
    volver = redirect(url_for("saneamiento.residuos"))
    ids = [int(x) for x in request.form.getlist("lote_id") if x.isdigit()]
    peso = _numero("cantidad_kg")
    if not ids:
        flash("Marca los lotes vencidos que vas a sacar.", "error")
        return volver
    if not peso or peso <= 0:
        flash("Escribe cuánto pesan en total (kg). Si no tienes balanza, haz un estimado.", "error")
        return volver
    vencidos = {l["id"]: l for l in _vencidos_en_inventario()}
    elegidos = [vencidos[i] for i in ids if i in vencidos]
    if not elegidos:
        flash("Esos lotes ya no están vencidos con unidades.", "error")
        return volver
    db = get_db()
    detalle = []
    for l in elegidos:
        lote = db.execute("SELECT producto_id FROM lotes WHERE id = ?", (l["id"],)).fetchone()
        db.execute("UPDATE lotes SET cantidad_disponible = 0, estado = 'agotado', actualizado_en = ? WHERE id = ?",
                   (ahora(), l["id"]))
        db.execute("INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, referencia, "
                   "usuario_id, usuario_nombre, observaciones, creado_en) VALUES (?,?,?, 'baja', ?, ?, ?, ?, ?, ?)",
                   (ahora(), l["id"], lote["producto_id"], -l["cantidad_disponible"], "Baja por vencimiento",
                    g.user["id"], g.user["nombre"], "Sale como residuo farmacéutico", ahora()))
        detalle.append(f"{l['nombre']} (lote {l['lote'] or '-'}, {l['cantidad_disponible']:g} und)")
    descripcion = "Baja de vencidos: " + "; ".join(detalle)
    cur = db.execute("INSERT INTO residuos_registros (fecha, tipo, cantidad_kg, descripcion, usuario_id, "
                     "usuario_nombre, creado_en) VALUES (?, 'farmaceuticos', ?, ?, ?, ?, ?)",
                     (date.today().isoformat(), round(peso, 3), descripcion[:1000], g.user["id"],
                      g.user["nombre"], ahora()))
    db.commit()
    registrar("baja_vencidos", "residuos_registros", cur.lastrowid, f"{len(elegidos)} lote(s) {peso} kg")
    flash(f"Se dieron de baja {len(elegidos)} lote(s) vencido(s) y quedaron registrados como residuo ({peso:g} kg). "
          "Guárdalos en la caneca roja hasta entregarlos al gestor.", "ok")
    return volver


# ======================================================================
# PDF: planilla de limpieza y consolidado de residuos del mes
# ======================================================================

def _pdf(titulo, nombre_archivo, armar, horizontal=False):
    """Arma un PDF con el encabezado y el pie de siempre; `armar(elementos, estilos)` pone el contenido."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    from .configuracion import obtener_config
    from .pdf_utils import COLOR_SUAVE, encabezado_pdf, pie_de_pagina

    config = obtener_config()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4) if horizontal else A4,
                            leftMargin=1.2 * cm, rightMargin=1.2 * cm, topMargin=1.2 * cm, bottomMargin=1.5 * cm,
                            title=titulo)
    base = getSampleStyleSheet()
    estilos = {
        "celda": ParagraphStyle("Celda", parent=base["Normal"], fontSize=8, leading=9.5),
        "sub": ParagraphStyle("Sub", parent=base["Normal"], fontSize=9, textColor=COLOR_SUAVE),
        "h": ParagraphStyle("H", parent=base["Normal"], fontSize=10.5, spaceBefore=10, spaceAfter=4),
        "ancho": doc.width,
    }
    elementos = list(encabezado_pdf(config, titulo))
    armar(elementos, estilos)
    regente = config.get("regente_nombre") or ""
    if regente:
        elementos.append(Spacer(1, 24))
        elementos.append(Paragraph(
            f"_______________________________________<br/><b>{regente}</b><br/>"
            f"Director Técnico — Tarjeta profesional {config.get('regente_tarjeta') or '—'}", estilos["sub"]))
    doc.build(elementos, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=nombre_archivo)


@bp.route("/limpieza/planilla.pdf")
@login_required
def limpieza_pdf():
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Table

    from .pdf_utils import COLOR_MARCA_SUAVE, estilo_tabla

    primero = _mes(request.args.get("mes"))
    dias, filas = planilla_mes(primero)
    mes_texto = f"{MESES_ES[primero.month]} {primero.year}"

    def armar(el, est):
        el.append(Paragraph(f"Mes: <b>{mes_texto}</b> · X = tarea hecha ese día", est["sub"]))
        # Tabla 1: la cuadrícula (tarea × día)
        ancho_dia = 0.62 * cm
        data = [["Tarea", "Frec."] + [str(d.day) for d in dias] + ["Cumpl."]]
        for f in filas:
            data.append([Paragraph(f["tarea"]["nombre"], est["celda"]), Paragraph(f["frecuencia_texto"][:3] + ".", est["celda"])]
                        + ["X" if d.day in f["marcas"] else "" for d in dias]
                        + [f"{f['hechos']}/{f['periodos']}"])
        resto = est["ancho"] - ancho_dia * len(dias)
        tabla = Table(data, colWidths=[resto - 2.6 * cm, 1.2 * cm] + [ancho_dia] * len(dias) + [1.4 * cm],
                      repeatRows=1)
        reglas = [("ALIGN", (2, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 7.5)]
        # Domingos sombreados para ubicarse rápido
        for i, d in enumerate(dias):
            if d.weekday() == 6:
                reglas.append(("BACKGROUND", (2 + i, 1), (2 + i, -1), COLOR_MARCA_SUAVE))
        tabla.setStyle(estilo_tabla(reglas))
        el.append(tabla)
        # Tabla 2: el detalle (quién y cuándo)
        el.append(Paragraph("Detalle", est["h"]))
        detalle = [["Fecha", "Tarea", "Hecha por", "Observaciones"]]
        for f in filas:
            for dia, r in sorted(f["marcas"].items()):
                detalle.append([f"{dia:02d}/{primero.month:02d}/{primero.year}", f["tarea"]["nombre"],
                                r["usuario_nombre"] or "—", Paragraph(r["observaciones"] or "", est["celda"])])
        detalle = [detalle[0]] + sorted(detalle[1:], key=lambda x: (x[0], x[1]))
        if len(detalle) == 1:
            detalle.append(["—", "Sin registros este mes", "", ""])
        t2 = Table(detalle, colWidths=[2.4 * cm, 6 * cm, 5 * cm, est["ancho"] - 13.4 * cm], repeatRows=1)
        t2.setStyle(estilo_tabla())
        el.append(t2)

    return _pdf("PLANILLA DE LIMPIEZA Y DESINFECCIÓN", f"limpieza_{primero.strftime('%Y_%m')}.pdf", armar,
                horizontal=True)


@bp.route("/residuos/mes.pdf")
@login_required
def residuos_pdf():
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Table

    from .pdf_utils import estilo_tabla

    primero = _mes(request.args.get("mes"))
    registros, entregas, por_tipo = resumen_residuos(primero)
    mes_texto = f"{MESES_ES[primero.month]} {primero.year}"
    f = lambda iso: f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if iso else "—"

    def armar(el, est):
        el.append(Paragraph(f"Mes: <b>{mes_texto}</b> · Resolución 591 de 2024 (MinSalud y MinAmbiente)", est["sub"]))
        el.append(Paragraph("Consolidado del mes", est["h"]))
        data = [["Tipo de residuo", "Clase", "Kilos"]]
        for clave, (texto, peligroso) in TIPOS_RESIDUO.items():
            data.append([Paragraph(texto, est["celda"]), "Peligroso" if peligroso else "No peligroso",
                         f"{por_tipo[clave]:.2f}".replace(".", ",")])
        total = sum(por_tipo.values())
        data.append(["Total", "", f"{total:.2f}".replace(".", ",")])
        t = Table(data, colWidths=[10 * cm, 3 * cm, 2.4 * cm])
        t.setStyle(estilo_tabla([("ALIGN", (2, 0), (2, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
        el.append(t)

        el.append(Paragraph("Registros del mes", est["h"]))
        data = [["Fecha", "Tipo", "Kilos", "Descripción", "Registró"]]
        for r in registros:
            data.append([f(r["fecha"]), Paragraph(TIPOS_RESIDUO[r["tipo"]][0].split(" (")[0], est["celda"]),
                         f"{r['cantidad_kg']:g}".replace(".", ","), Paragraph(r["descripcion"] or "", est["celda"]),
                         r["usuario_nombre"] or "—"])
        if len(data) == 1:
            data.append(["—", "Sin registros", "", "", ""])
        t = Table(data, colWidths=[2.2 * cm, 4 * cm, 1.4 * cm, est["ancho"] - 11.2 * cm, 3.6 * cm], repeatRows=1)
        t.setStyle(estilo_tabla())
        el.append(t)

        el.append(Paragraph("Entregas al gestor autorizado", est["h"]))
        data = [["Fecha", "Gestor", "Qué se entregó", "Kilos", "Certificado"]]
        for e in entregas:
            data.append([f(e["fecha"]), Paragraph(e["gestor"] + (f" · NIT {e['gestor_nit']}" if e["gestor_nit"] else ""),
                                                  est["celda"]),
                         Paragraph(e["tipos"] or "—", est["celda"]),
                         f"{e['cantidad_kg']:g}".replace(".", ",") if e["cantidad_kg"] else "—",
                         e["certificado_numero"] or ("archivo adjunto" if e["archivo"] else "—")])
        if len(data) == 1:
            data.append(["—", "Sin entregas este mes", "", "", ""])
        t = Table(data, colWidths=[2.2 * cm, 5 * cm, est["ancho"] - 12 * cm, 1.4 * cm, 3.4 * cm], repeatRows=1)
        t.setStyle(estilo_tabla())
        el.append(t)

    return _pdf("REGISTRO MENSUAL DE RESIDUOS", f"residuos_{primero.strftime('%Y_%m')}.pdf", armar)
