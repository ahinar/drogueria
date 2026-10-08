"""Home / Dashboard principal."""
from datetime import datetime, date
from datetime import timedelta
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
    from .temperaturas import _turno_de_hora, _ya_registro_turno_hoy  # import local

    hoy = date.today().isoformat()
    ahora_dt = datetime.now()
    dia_semana = ahora_dt.isoweekday()

    zonas = db.execute(
        "SELECT id, nombre, horarios, dias_semana, minutos_tolerancia "
        "FROM zonas_temperatura WHERE activa = 1"
    ).fetchall()

    pendientes = []
    for z in zonas:
        if str(dia_semana) not in (z["dias_semana"] or "").split(","):
            continue
        horarios = [h.strip() for h in (z["horarios"] or "").split(",") if h.strip()]
        for h in horarios:
            try:
                hh, mm = map(int, h.split(":"))
            except ValueError:
                continue
            programada = ahora_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            tolerancia = z["minutos_tolerancia"] or 30
            if ahora_dt < programada + timedelta(minutes=tolerancia):
                continue
            turno = _turno_de_hora(h)
            if _ya_registro_turno_hoy(z["id"], turno):
                continue
            pendientes.append({"zona": z["nombre"], "hora": h, "turno": turno})

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
    """Productos activos + alertas reales de inventario."""
    from datetime import date, timedelta
    total = db.execute("SELECT COUNT(*) FROM productos WHERE activo = 1").fetchone()[0]

    hoy = date.today().isoformat()
    limite_30 = (date.today() + timedelta(days=30)).isoformat()
    limite_90 = (date.today() + timedelta(days=90)).isoformat()

    try:
        por_vencer_30 = db.execute(
            "SELECT COUNT(*) FROM lotes WHERE estado = 'disponible' "
            "AND cantidad_disponible > 0 AND vencimiento IS NOT NULL "
            "AND vencimiento <= ? AND vencimiento >= ?",
            (limite_30, hoy),
        ).fetchone()[0]

        por_vencer_90 = db.execute(
            "SELECT COUNT(*) FROM lotes WHERE estado = 'disponible' "
            "AND cantidad_disponible > 0 AND vencimiento IS NOT NULL "
            "AND vencimiento <= ? AND vencimiento >= ?",
            (limite_90, hoy),
        ).fetchone()[0]

        vencidos = db.execute(
            "SELECT COUNT(*) FROM lotes WHERE cantidad_disponible > 0 "
            "AND vencimiento IS NOT NULL AND vencimiento < ?",
            (hoy,),
        ).fetchone()[0]

        total_lotes = db.execute(
            "SELECT COUNT(*) FROM lotes WHERE cantidad_disponible > 0"
        ).fetchone()[0]
    except Exception:
        por_vencer_30 = por_vencer_90 = vencidos = total_lotes = 0

    return {
        "total": total,
        "por_vencer_30": por_vencer_30,
        "por_vencer_90": por_vencer_90,
        "vencidos": vencidos,
        "total_lotes": total_lotes,
    }


def _ventas_hoy(db):
    """Ventas del día: cantidad y total de las ventas COMPLETADAS (las anuladas no cuentan)."""
    hoy = date.today().isoformat()
    try:
        fila = db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total "
            "FROM ventas WHERE fecha LIKE ? AND estado = 'completada'",
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