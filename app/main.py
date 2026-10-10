"""Home / Dashboard principal."""
from datetime import datetime, date
from datetime import timedelta
from flask import Blueprint, g, render_template

from .alertas import calcular_alertas
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
    from .temperaturas import _pendientes  # import local

    zonas = db.execute("SELECT id FROM zonas_temperatura WHERE activa = 1").fetchall()

    # La lista de pendientes sale de la MISMA función que usa la alarma, así el inicio
    # y la alarma nunca se contradicen.
    pendientes = [{"zona": p["zona"], "hora": p["hora"], "turno": p["turno"]}
                  for p in _pendientes()]

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
    # Cuántos tienen "stock mínimo" definido (los únicos que avisan cuando se acaban)
    con_minimo = db.execute(
        "SELECT COUNT(*) FROM productos WHERE activo = 1 AND stock_minimo > 0").fetchone()[0]

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
        "con_minimo": con_minimo,
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


def _resumen_negocio(db):
    """Números del negocio para el Inicio (solo los ve el administrador / DT).

    Ventas (con IVA, sin anuladas) de la semana (desde el lunes) y del mes,
    y la utilidad neta del mes según el estado de resultados (app/utilidades.py).
    """
    from . import utilidades
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    def vendido(desde):
        fila = db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total FROM ventas "
            "WHERE estado = 'completada' AND fecha >= ?", (desde.isoformat(),)).fetchone()
        return {"n": fila["n"], "total": fila["total"]}

    mes = utilidades.calcular(inicio_mes, hoy)
    return {"semana": vendido(lunes), "mes": vendido(inicio_mes),
            "utilidad_mes": mes["utilidad_neta"], "margen_mes": mes["margen_neto"]}


@bp.route("/")
@login_required
def inicio():
    db = get_db()

    temperatura = _estado_temperatura(db)
    productos = _productos_alertas(db)
    ventas = _ventas_hoy(db)
    # Panel "¿Qué hay que atender hoy?" (toda la lógica está en app/alertas.py)
    alertas = calcular_alertas(g.user["rol"])
    # Resumen de plata: solo para administrador y director técnico
    resumen = _resumen_negocio(db) if g.user["rol"] in ("administrador", "director_tecnico") else None

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
        "alertas": alertas,
        "resumen": resumen,
        "alertas_rojas": sum(1 for a in alertas if a["nivel"] == "rojo"),
        "ultimos_productos": ultimos_productos,
        "ultimas_temperaturas": ultimas_temperaturas,
    }
    return render_template("inicio.html", **contexto)