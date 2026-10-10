"""Caja menor: fondo permanente de dinero del negocio.

La caja menor es un fondo separado de la caja del POS. Al abrir la caja del POS
se saca dinero de la caja menor, y al cerrarla el efectivo vuelve a la caja
menor. También se pueden registrar aportes, retiros y gastos pagados
directamente desde este fondo.
"""
from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .formato import pesos
from .db import ahora, get_db

bp = Blueprint("caja_menor", __name__, url_prefix="/caja-menor")

# Metadatos de cada tipo de movimiento para la vista.
TIPOS = {
    "aporte":       ("Aporte",           "➕", "in"),
    "retiro":       ("Retiro",           "➖", "out"),
    "apertura_pos": ("Apertura de POS",  "🛒", "out"),
    "cierre_pos":   ("Cierre de POS",    "🏁", "in"),
    "gasto":        ("Gasto pagado",     "💸", "out"),
}

def saldo_actual(db=None):
    """Devuelve el saldo actual de la caja menor."""
    db = db or get_db()
    fila = db.execute(
        "SELECT "
        "COALESCE(SUM(CASE WHEN tipo IN ('aporte', 'cierre_pos') THEN monto ELSE 0 END), 0) AS entradas, "
        "COALESCE(SUM(CASE WHEN tipo IN ('retiro', 'apertura_pos', 'gasto') THEN monto ELSE 0 END), 0) AS salidas "
        "FROM caja_menor_movimientos"
    ).fetchone()
    return float(fila["entradas"] or 0) - float(fila["salidas"] or 0)

def registrar_movimiento(db, tipo, monto, motivo=None, caja_id=None, gasto_id=None):
    """Registra un movimiento en la caja menor. Devuelve el id del movimiento creado."""
    usuario_id = g.user["id"] if g.get("user") else None
    usuario_nombre = g.user["nombre"] if g.get("user") else None
    cur = db.execute(
        "INSERT INTO caja_menor_movimientos "
        "(fecha, tipo, monto, motivo, caja_id, gasto_id, usuario_id, usuario_nombre, creado_en) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (ahora(), tipo, monto, motivo, caja_id, gasto_id,
         usuario_id, usuario_nombre, ahora()),
    )
    return cur.lastrowid

# ============================================================
# Vista principal
# ============================================================

@bp.route("/")
@login_required
@roles_required("administrador", "director_tecnico")
def index():
    db = get_db()
    saldo = saldo_actual(db)
    movimientos = db.execute(
        "SELECT * FROM caja_menor_movimientos ORDER BY id DESC LIMIT 200"
    ).fetchall()

    # Totales por tipo (para mostrar resumen)
    resumen = db.execute(
        "SELECT tipo, COUNT(*) AS n, COALESCE(SUM(monto), 0) AS total "
        "FROM caja_menor_movimientos GROUP BY tipo"
    ).fetchall()

    return render_template("caja_menor/index.html",
                           saldo=saldo, movimientos=movimientos,
                           tipos=TIPOS, resumen=resumen)

# ============================================================
# Aportes y retiros manuales
# ============================================================

@bp.route("/aporte", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def aporte():
    try:
        monto = float((request.form.get("monto") or "0").replace(",", "."))
    except ValueError:
        monto = 0
    motivo = (request.form.get("motivo") or "").strip() or "Aporte manual"
    if monto <= 0:
        flash("El monto debe ser mayor a cero.", "error")
        return redirect(url_for("caja_menor.index"))

    db = get_db()
    mov_id = registrar_movimiento(db, "aporte", monto, motivo)
    db.commit()
    registrar("caja_menor_aporte", "caja_menor_movimientos", mov_id,
              f"monto={monto} motivo={motivo}")
    flash(f"Aporte de {pesos(monto)} registrado.", "ok")
    return redirect(url_for("caja_menor.index"))

@bp.route("/retiro", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def retiro():
    try:
        monto = float((request.form.get("monto") or "0").replace(",", "."))
    except ValueError:
        monto = 0
    motivo = (request.form.get("motivo") or "").strip()
    if monto <= 0:
        flash("El monto debe ser mayor a cero.", "error")
        return redirect(url_for("caja_menor.index"))
    if not motivo:
        flash("Debes indicar el motivo del retiro.", "error")
        return redirect(url_for("caja_menor.index"))

    # ¿Es plata que se lleva el dueño (su ganancia)? Si sí, se marca para
    # mostrarla aparte en el estado de resultados (Reportes → Utilidades).
    # Si es solo consignar o mover plata, queda sin marcar.
    es_dueno = 1 if request.form.get("retiro_dueno") else 0

    db = get_db()
    mov_id = registrar_movimiento(db, "retiro", monto, motivo)
    db.execute("UPDATE caja_menor_movimientos SET retiro_dueno = ? WHERE id = ?", (es_dueno, mov_id))
    db.commit()
    registrar("caja_menor_retiro", "caja_menor_movimientos", mov_id,
              f"monto={monto} motivo={motivo}" + (" retiro_del_dueño" if es_dueno else ""))
    flash(f"Retiro de {pesos(monto)} registrado.", "ok")
    return redirect(url_for("caja_menor.index"))
