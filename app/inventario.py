"""Inventario por lote, kardex, vencimientos y ajustes."""
from datetime import datetime, date, timedelta

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db

bp = Blueprint("inventario", __name__, url_prefix="/inventario")

ESTADOS_LOTE = {
    "cuarentena": "Cuarentena",
    "disponible": "Disponible",
    "bloqueado": "Bloqueado",
    "agotado": "Agotado",
    "rechazado": "Rechazado",
}


def _dias_para_vencer(vencimiento_str):
    """Devuelve los días que faltan para el vencimiento (negativo si ya venció)."""
    if not vencimiento_str:
        return None
    try:
        f = datetime.strptime(vencimiento_str[:10], "%Y-%m-%d").date()
        return (f - date.today()).days
    except (ValueError, TypeError):
        return None


def _semaforo(dias, estado):
    """Devuelve (clase, texto)."""
    if estado == "agotado" or estado == "rechazado":
        return ("gris", "Agotado")
    if estado == "cuarentena":
        return ("amarillo", "Cuarentena")
    if estado == "bloqueado":
        return ("rojo", "Bloqueado")
    if dias is None:
        return ("verde", "Sin vencimiento")
    if dias < 0:
        return ("negro", "VENCIDO")
    if dias <= 30:
        return ("rojo", f"{dias} días")
    if dias <= 90:
        return ("amarillo", f"{dias} días")
    return ("verde", f"{dias} días")


def _obtener_lote(lote_id):
    fila = get_db().execute(
        "SELECT l.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre, "
        "p.concentracion, p.requiere_formula, p.cadena_frio, p.control_especial, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre "
        "FROM lotes l JOIN productos p ON p.id = l.producto_id WHERE l.id = ?",
        (lote_id,),
    ).fetchone()
    if fila is None:
        abort(404)
    return fila


# ---------- Resumen ----------

@bp.route("/")
@login_required
def inicio():
    db = get_db()

    total_productos = db.execute(
        "SELECT COUNT(*) FROM productos WHERE activo = 1"
    ).fetchone()[0]

    total_lotes = db.execute(
        "SELECT COUNT(*) FROM lotes WHERE cantidad_disponible > 0"
    ).fetchone()[0]

    # Lotes por vencer (disponibles, en los próximos 90 días)
    hoy = date.today().isoformat()
    limite_30 = (date.today() + timedelta(days=30)).isoformat()
    limite_90 = (date.today() + timedelta(days=90)).isoformat()

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

    cuarentena = db.execute(
        "SELECT COUNT(*) FROM lotes WHERE estado = 'cuarentena' AND cantidad_disponible > 0"
    ).fetchone()[0]

    bloqueados = db.execute(
        "SELECT COUNT(*) FROM lotes WHERE estado = 'bloqueado' AND cantidad_disponible > 0"
    ).fetchone()[0]

    # Top de productos con lotes por vencer
    alertas_vencimiento = db.execute(
        "SELECT l.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre "
        "FROM lotes l JOIN productos p ON p.id = l.producto_id "
        "WHERE l.estado = 'disponible' AND l.cantidad_disponible > 0 "
        "AND l.vencimiento IS NOT NULL AND l.vencimiento <= ? "
        "ORDER BY l.vencimiento LIMIT 15",
        (limite_90,),
    ).fetchall()

    return render_template(
        "inventario/inicio.html",
        total_productos=total_productos,
        total_lotes=total_lotes,
        por_vencer_30=por_vencer_30,
        por_vencer_90=por_vencer_90,
        vencidos=vencidos,
        cuarentena=cuarentena,
        bloqueados=bloqueados,
        alertas_vencimiento=alertas_vencimiento,
        estados=ESTADOS_LOTE,
    )


# ---------- Lista de lotes ----------

@bp.route("/lotes")
@login_required
def lotes():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "").strip()
    vencimiento = request.args.get("vencimiento", "").strip()  # '30', '90', 'vencidos'

    cond, params = [], []
    if estado and estado in ESTADOS_LOTE:
        cond.append("l.estado = ?")
        params.append(estado)
    if q:
        cond.append("(p.codigo LIKE ? OR p.nombre LIKE ? OR l.lote LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]

    hoy = date.today().isoformat()
    if vencimiento == "vencidos":
        cond.append("l.vencimiento IS NOT NULL AND l.vencimiento < ?")
        params.append(hoy)
    elif vencimiento == "30":
        limite = (date.today() + timedelta(days=30)).isoformat()
        cond.append("l.vencimiento IS NOT NULL AND l.vencimiento <= ? AND l.vencimiento >= ?")
        params += [limite, hoy]
    elif vencimiento == "90":
        limite = (date.today() + timedelta(days=90)).isoformat()
        cond.append("l.vencimiento IS NOT NULL AND l.vencimiento <= ? AND l.vencimiento >= ?")
        params += [limite, hoy]

    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    filas = get_db().execute(
        "SELECT l.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre, "
        "p.concentracion, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre "
        "FROM lotes l JOIN productos p ON p.id = l.producto_id "
        f"{where} ORDER BY l.vencimiento IS NULL, l.vencimiento, p.nombre "
        "LIMIT 500",
        params,
    ).fetchall()

    # Añadimos el semáforo calculado a cada fila
    lotes_procesados = []
    for f in filas:
        d = dict(f)
        dias = _dias_para_vencer(f["vencimiento"])
        color, texto = _semaforo(dias, f["estado"])
        d["dias"] = dias
        d["semaforo_color"] = color
        d["semaforo_texto"] = texto
        lotes_procesados.append(d)

    return render_template("inventario/lotes.html",
                           filas=lotes_procesados, q=q, estado=estado,
                           vencimiento=vencimiento, estados=ESTADOS_LOTE)


# ---------- Ver detalle de un lote ----------

@bp.route("/lotes/<int:lote_id>")
@login_required
def lote_ver(lote_id):
    lote = _obtener_lote(lote_id)
    dias = _dias_para_vencer(lote["vencimiento"])
    color, texto = _semaforo(dias, lote["estado"])

    movimientos = get_db().execute(
        "SELECT * FROM movimientos_inventario WHERE lote_id = ? ORDER BY id DESC LIMIT 100",
        (lote_id,),
    ).fetchall()

    return render_template("inventario/lote_ver.html",
                           lote=lote, movimientos=movimientos,
                           dias=dias, semaforo_color=color, semaforo_texto=texto,
                           estados=ESTADOS_LOTE)


# ---------- Acciones sobre lotes ----------

@bp.route("/lotes/<int:lote_id>/bloquear", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def lote_bloquear(lote_id):
    lote = _obtener_lote(lote_id)
    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        flash("Debes indicar el motivo del bloqueo.", "error")
        return redirect(url_for("inventario.lote_ver", lote_id=lote_id))

    db = get_db()
    db.execute(
        "UPDATE lotes SET estado = 'bloqueado', motivo_bloqueo = ?, actualizado_en = ? WHERE id = ?",
        (motivo, ahora(), lote_id),
    )
    db.commit()
    registrar("lote_bloqueado", "lotes", lote_id,
              f"producto={lote['producto_nombre']} lote={lote['lote']} motivo={motivo}")
    flash(f"Lote bloqueado: {motivo}", "ok")
    return redirect(url_for("inventario.lote_ver", lote_id=lote_id))


@bp.route("/lotes/<int:lote_id>/desbloquear", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def lote_desbloquear(lote_id):
    lote = _obtener_lote(lote_id)
    if lote["estado"] != "bloqueado":
        flash("El lote no está bloqueado.", "error")
        return redirect(url_for("inventario.lote_ver", lote_id=lote_id))

    db = get_db()
    db.execute(
        "UPDATE lotes SET estado = 'disponible', motivo_bloqueo = NULL, actualizado_en = ? WHERE id = ?",
        (ahora(), lote_id),
    )
    db.commit()
    registrar("lote_desbloqueado", "lotes", lote_id,
              f"producto={lote['producto_nombre']} lote={lote['lote']}")
    flash("Lote desbloqueado y disponible.", "ok")
    return redirect(url_for("inventario.lote_ver", lote_id=lote_id))


@bp.route("/lotes/<int:lote_id>/liberar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def lote_liberar(lote_id):
    """Libera un lote que estaba en CUARENTENA: pasa a 'disponible' (ya se puede vender)
    y se anota la entrada de stock en el kardex (movimientos_inventario)."""
    lote = _obtener_lote(lote_id)
    if lote["estado"] != "cuarentena":
        flash("Solo se pueden liberar lotes en cuarentena.", "error")
        return redirect(url_for("inventario.lote_ver", lote_id=lote_id))

    db = get_db()
    # 1) Cambiamos el estado del lote.
    db.execute(
        "UPDATE lotes SET estado = 'disponible', actualizado_en = ? WHERE id = ?",
        (ahora(), lote_id),
    )
    # 2) Anotamos la entrada en el kardex (hasta ahora no se había registrado).
    db.execute(
        "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, "
        "referencia, referencia_id, usuario_id, usuario_nombre, creado_en) "
        "VALUES (?,?,?, 'recepcion', ?, ?, ?, ?, ?, ?)",
        (ahora(), lote_id, lote["producto_id"], lote["cantidad_disponible"],
         "Liberado de cuarentena", lote["recepcion_id"], g.user["id"], g.user["nombre"], ahora()),
    )
    db.commit()
    registrar("lote_liberado", "lotes", lote_id,
              f"producto={lote['producto_nombre']} lote={lote['lote']}")
    flash("Lote liberado de cuarentena y disponible para la venta.", "ok")
    return redirect(url_for("inventario.lote_ver", lote_id=lote_id))


@bp.route("/lotes/<int:lote_id>/ajustar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def lote_ajustar(lote_id):
    lote = _obtener_lote(lote_id)
    try:
        nueva_cantidad = float((request.form.get("cantidad") or "0").replace(",", "."))
    except ValueError:
        flash("Cantidad inválida.", "error")
        return redirect(url_for("inventario.lote_ver", lote_id=lote_id))

    if nueva_cantidad < 0:
        flash("La cantidad no puede ser negativa.", "error")
        return redirect(url_for("inventario.lote_ver", lote_id=lote_id))

    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        flash("Debes indicar el motivo del ajuste.", "error")
        return redirect(url_for("inventario.lote_ver", lote_id=lote_id))

    diferencia = nueva_cantidad - lote["cantidad_disponible"]
    if abs(diferencia) < 0.001:
        flash("La cantidad es igual a la actual. No hay cambios.", "error")
        return redirect(url_for("inventario.lote_ver", lote_id=lote_id))

    db = get_db()
    nuevo_estado = lote["estado"]
    if nueva_cantidad == 0 and lote["estado"] == "disponible":
        nuevo_estado = "agotado"

    db.execute(
        "UPDATE lotes SET cantidad_disponible = ?, estado = ?, actualizado_en = ? WHERE id = ?",
        (nueva_cantidad, nuevo_estado, ahora(), lote_id),
    )
    db.execute(
        "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, "
        "referencia, usuario_id, usuario_nombre, observaciones, creado_en) "
        "VALUES (?,?,?, 'ajuste', ?, ?, ?, ?, ?, ?)",
        (ahora(), lote_id, lote["producto_id"], diferencia, "Ajuste manual",
         g.user["id"], g.user["nombre"], motivo, ahora()),
    )
    db.commit()
    registrar("lote_ajustado", "lotes", lote_id,
              f"producto={lote['producto_nombre']} antes={lote['cantidad_disponible']} "
              f"despues={nueva_cantidad} motivo={motivo}")
    flash(f"Lote ajustado: {lote['cantidad_disponible']} → {nueva_cantidad}", "ok")
    return redirect(url_for("inventario.lote_ver", lote_id=lote_id))


# ---------- Kardex ----------

@bp.route("/kardex")
@login_required
def kardex_buscar():
    return render_template("inventario/kardex_buscar.html")


@bp.route("/kardex/<int:producto_id>")
@login_required
def kardex(producto_id):
    db = get_db()
    producto = db.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if producto is None:
        abort(404)

    movimientos = db.execute(
        "SELECT m.*, l.lote AS lote_nombre, l.vencimiento AS lote_vencimiento "
        "FROM movimientos_inventario m LEFT JOIN lotes l ON l.id = m.lote_id "
        "WHERE m.producto_id = ? ORDER BY m.id DESC LIMIT 500",
        (producto_id,),
    ).fetchall()

    # Saldo actual
    total_lotes = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(cantidad_disponible), 0) AS total "
        "FROM lotes WHERE producto_id = ? AND estado IN ('disponible', 'cuarentena', 'bloqueado')",
        (producto_id,),
    ).fetchone()

    lotes = db.execute(
        "SELECT * FROM lotes WHERE producto_id = ? AND cantidad_disponible > 0 "
        "ORDER BY vencimiento IS NULL, vencimiento",
        (producto_id,),
    ).fetchall()

    return render_template("inventario/kardex.html",
                           producto=producto, movimientos=movimientos,
                           total_lotes=total_lotes, lotes=lotes,
                           estados=ESTADOS_LOTE)


# ---------- Vencimientos (semáforo) ----------

@bp.route("/vencimientos")
@login_required
def vencimientos():
    hoy = date.today()
    db = get_db()

    # Agrupar por rangos
    lotes = db.execute(
        "SELECT l.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre "
        "FROM lotes l JOIN productos p ON p.id = l.producto_id "
        "WHERE l.cantidad_disponible > 0 AND l.estado IN ('disponible', 'cuarentena', 'bloqueado') "
        "ORDER BY l.vencimiento IS NULL, l.vencimiento LIMIT 500"
    ).fetchall()

    grupos = {"vencidos": [], "rojo": [], "amarillo": [], "verde": [], "sin": []}
    for f in lotes:
        dias = _dias_para_vencer(f["vencimiento"])
        color, texto = _semaforo(dias, f["estado"])
        item = dict(f)
        item["dias"] = dias
        item["semaforo_color"] = color
        item["semaforo_texto"] = texto
        if dias is None:
            grupos["sin"].append(item)
        elif dias < 0:
            grupos["vencidos"].append(item)
        elif dias <= 30:
            grupos["rojo"].append(item)
        elif dias <= 90:
            grupos["amarillo"].append(item)
        else:
            grupos["verde"].append(item)

    return render_template("inventario/vencimientos.html", grupos=grupos,
                           total=len(lotes))