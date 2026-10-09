"""Punto de venta (POS): cajas, ventas, movimientos, gastos y cobro."""
import json
from datetime import date, datetime

from flask import (Blueprint, abort, flash, g, jsonify, redirect,
                   render_template, request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .caja_menor import registrar_movimiento as _cm_mov
from .caja_menor import saldo_actual as _cm_saldo
from .configuracion import obtener_config
from .db import ahora, get_db

bp = Blueprint("pos", __name__, url_prefix="/pos")

# Denominaciones del peso colombiano (2026)
BILLETES_CO = [100000, 50000, 20000, 10000, 5000, 2000]
MONEDAS_CO = [1000, 500, 200, 100, 50]
DENOMINACIONES_CO = BILLETES_CO + MONEDAS_CO

def _parsear_denominaciones():
    """Lee el JSON de denominaciones del formulario y devuelve (total, detalle_str)."""
    try:
        raw = request.form.get("denominaciones", "{}")
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    detalle = {}
    total = 0
    for valor in DENOMINACIONES_CO:
        try:
            cantidad = int(data.get(str(valor), 0) or 0)
        except (ValueError, TypeError):
            cantidad = 0
        if cantidad > 0:
            subtotal = valor * cantidad
            total += subtotal
            detalle[str(valor)] = {"cantidad": cantidad, "subtotal": subtotal}
    return total, json.dumps(detalle, ensure_ascii=False)

def _caja_abierta():
    return get_db().execute(
        "SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1"
    ).fetchone()

def _siguiente_numero_caja():
    db = get_db()
    fila = db.execute(
        "SELECT numero FROM cajas ORDER BY CAST(numero AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return "1001"
    try:
        return str(int(fila["numero"]) + 1)
    except ValueError:
        return "1001"

def _siguiente_consecutivo_venta():
    db = get_db()
    fila = db.execute(
        "SELECT consecutivo FROM ventas ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return "V-0001"
    try:
        n = int(fila["consecutivo"].split("-")[1]) + 1
    except (ValueError, IndexError):
        return "V-0001"
    return f"V-{n:04d}"

def _resumen_caja(caja):
    """Devuelve el resumen completo del turno: ventas, movimientos, totales por forma de pago."""
    db = get_db()

    ventas_por_pago = db.execute(
        "SELECT forma_pago, COUNT(*) AS n, COALESCE(SUM(total), 0) AS total "
        "FROM ventas WHERE caja_id = ? AND estado = 'completada' "
        "GROUP BY forma_pago",
        (caja["id"],),
    ).fetchall()

    total_ventas_n = sum(p["n"] for p in ventas_por_pago)
    total_ventas = sum(p["total"] for p in ventas_por_pago)

    movs = db.execute(
        "SELECT * FROM caja_movimientos WHERE caja_id = ? ORDER BY id DESC",
        (caja["id"],),
    ).fetchall()

    ingresos_efectivo = sum(m["monto"] for m in movs if m["tipo"] == "ingreso" and m["forma_pago"] == "efectivo")
    salidas_efectivo = sum(m["monto"] for m in movs if m["tipo"] == "salida" and m["forma_pago"] == "efectivo")
    ingresos_nequi = sum(m["monto"] for m in movs if m["tipo"] == "ingreso" and m["forma_pago"] == "nequi")
    salidas_nequi = sum(m["monto"] for m in movs if m["tipo"] == "salida" and m["forma_pago"] == "nequi")
    ingresos_davivienda = sum(m["monto"] for m in movs if m["tipo"] == "ingreso" and m["forma_pago"] == "davivienda")
    salidas_davivienda = sum(m["monto"] for m in movs if m["tipo"] == "salida" and m["forma_pago"] == "davivienda")

    def _por_pago(nombre):
        return next((p for p in ventas_por_pago if p["forma_pago"] == nombre), None)

    v_efectivo = _por_pago("efectivo")
    v_nequi = _por_pago("nequi")
    v_davivienda = _por_pago("davivienda")
    v_tarjeta = _por_pago("tarjeta")

    efectivo_esperado = (caja["efectivo_inicial"] or 0) + \
                        (v_efectivo["total"] if v_efectivo else 0) + \
                        ingresos_efectivo - salidas_efectivo
