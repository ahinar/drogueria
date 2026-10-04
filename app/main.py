"""Home / Dashboard principal."""
from datetime import datetime, date

from flask import Blueprint, render_template

from .auth import login_required
from .db import get_db

bp = Blueprint("main", __name__)

MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _saludo():
    h = datetime.now().hour
    if h < 12:
        return "Buenos días"
    if h < 19:
        return "Buenas tardes"
    return "Buenas noches"


def _fecha_larga_es():
    """Ej: 'domingo, 4 de octubre de 2026'"""
    d = datetime.now()
    return f"{DIAS_ES[d.weekday()]}, {d.day} de {MESES_ES[d.month - 1]} de {d.year}"


def _estado_temperatura(db):
    """Consulta si hoy ya se registró la temperatura de las zonas activas."""
    hoy = date.today().isoformat()
    zonas = db.execute(
        "SELECT id, nombre, horarios FROM zonas_temperatura WHERE activa = 1"
    ).fetchall()

    pendientes = []
    for z in zonas:
        horarios = [h.strip() for h in (z["horarios"] or "").split(",") if h.strip()]
        for h in horarios:
            existe = db.execute(
                "SELECT 1 FROM temperatura_registros "
                "WHERE zona_id = ? AND fecha LIKE ? LIMIT 1",
                (z["id"], f"{hoy}%"),
            ).fetchone()
            if not existe:
                try:
                    hh, mm = map(int, h.split(":"))
                    programada = datetime.now().replace(hour=hh, minute=mm, second=0)
                    if datetime.now() > programada:
                        pendientes.append({"zona": z["nombre"], "hora": h})
                        break
                except ValueError:
                    continue

    ultima = db.execute(
        "SELECT r.*, z.nombre AS zona_nombre "
        "FROM temperatura_registros r JOIN zonas_temperatura z ON z.id = r.zona_id "
        "ORDER BY r.id DESC LIMIT 1"
    ).fetchone()

    return {
        "pendientes": pendientes,
        "al_dia": len(pendientes) == 0 and len(zonas) > 0,
        "ultima": ultima,
        "zonas_activas": len(zonas),
    }


def _productos_alertas(db):
    """Productos activos y con stock bajo."""
    total = db.execute("SELECT COUNT(*) FROM productos WHERE activo = 1").fetchone()[0]
    con_minimo = db.execute(
        "SELECT COUNT(*) FROM productos WHERE activo = 1 AND stock_minimo > 0"
    ).fetchone()[0]
    return {"total": total, "con_minimo": con_minimo}


def _ventas_hoy(db):
    """Ventas del día (pendiente Fase 2). Devuelve 0 si la tabla no existe aún."""
    hoy = date.today().isoformat()
    try:
        fila = db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total "
            "FROM ventas WHERE fecha LIKE ? AND estado = 'interna'",
            (f"{hoy}%",),
        ).fetchone()
        return {"cantidad": fila["n"], "total": fila["total"], "disponible": True}
    except Exception:
        return {"cantidad": 0, "total": 0, "disponible": False}


@bp.route("/")
@login_required
def inicio():
    db = get_db()

    temperatura = _estado_temperatura(db)
    productos = _productos_alertas(db)
    ventas = _ventas_hoy(db)

    # Últimos productos creados
    ultimos_productos = db.execute(
        "SELECT codigo, nombre, creado_en FROM productos "
        "WHERE activo = 1 ORDER BY id DESC LIMIT 5"
    ).fetchall()

    # Últimas temperaturas
    ultimas_temperaturas = db.execute(
        "SELECT r.fecha, r.temperatura, r.humedad, r.dentro_de_rango, z.nombre AS zona_nombre "
        "FROM temperatura_registros r JOIN zonas_temperatura z ON z.id = r.zona_id "
        "ORDER BY r.id DESC LIMIT 5"
    ).fetchall()

    contexto = {
        "saludo": _saludo(),
        "hoy": _fecha_larga_es(),
        "temperatura": temperatura,
        "productos": productos,
        "ventas": ventas,
        "ultimos_productos": ultimos_productos,
        "ultimas_temperaturas": ultimas_temperaturas,
    }
    return render_template("inicio.html", **contexto)

@bp.route("/pos")
@login_required
def pos():
    return render_template("pos_en_construccion.html")