"""VENTAS: buscar cualquier venta, ver su detalle al lado y corregirla (versión 1.1.14).

PARA QUÉ (pedido de Fernando)
-----------------------------
Antes «Últimas ventas» solo mostraba las ventas de la caja abierta y cada venta
se abría en otra pestaña. Ahora:
  - A la IZQUIERDA, la lista de ventas, con buscador: fechas, número, cliente o
    producto, forma de pago y estado (completada o anulada).
  - A la DERECHA, el carrito de la venta escogida (productos, totales, cómo pagó),
    sin salir de la pantalla. Lo trae static/js/ventas.js desde /ventas/<id>/panel.
  - ABAJO del carrito: las devoluciones de esa venta (y el formulario para hacer
    una) y CORREGIR EL PAGO, por ejemplo: «el cliente pagó por Daviplata y lo
    registré como efectivo».

CORREGIR EL PAGO (corregir_pago, más abajo)
------------------------------------------
  - Cambia ventas.forma_pago (y sus partes, si es mixto, en venta_pagos).
  - Guarda la historia en venta_correcciones_pago (antes, después, motivo, quién).
  - Los saldos se arreglan SOLOS porque se calculan desde las ventas: el cierre de
    la caja abierta, Bancos (Nequi, Davivienda, Daviplata) y los reportes.
  - Si la caja de esa venta YA SE CERRÓ, el efectivo contado no cambia (eso fue lo
    que de verdad había), pero sí el esperado. Ejemplo: se registró $10.000 en
    efectivo que en realidad llegaron por Daviplata. Al cerrar faltaron $10.000 y
    quedaron como gasto «Faltante de caja». Al corregir, la caja cuadra: el gasto
    automático se anula y se vuelve a calcular (ver _rehacer_diferencia).
  - NO se corrige hacia o desde CRÉDITO (fiado): eso cambia la deuda del cliente
    y se maneja en Cartera.
  - Quién puede: administrador y director técnico siempre; los demás, solo
    mientras la caja de esa venta siga abierta (su propio turno).
"""
from datetime import date, timedelta

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   url_for)

from .audit import registrar
from .auth import login_required
from .db import ahora, get_db
from .formato import pesos
from . import formas_pago as fp

bp = Blueprint("ventas", __name__, url_prefix="/ventas")

JEFES = ("administrador", "director_tecnico")
ESTADOS = {"": "Todas", "completada": "Completadas", "anulada": "Anuladas"}
LIMITE = 300            # máximo de ventas en la lista (la búsqueda acota el resto)


# ---------------------------------------------------------------------
# Leer
# ---------------------------------------------------------------------

def _filtros():
    """Lee los filtros de la dirección. Sin fechas: los últimos 7 días."""
    hoy = date.today()
    f = {
        "desde": (request.args.get("desde") or (hoy - timedelta(days=6)).isoformat())[:10],
        "hasta": (request.args.get("hasta") or hoy.isoformat())[:10],
        "q": " ".join((request.args.get("q") or "").split())[:80],
        "forma": request.args.get("forma") if request.args.get("forma") in fp.FORMAS_VENTA else "",
        "estado": request.args.get("estado") if request.args.get("estado") in ESTADOS else "",
        "caja": request.args.get("caja", type=int),
    }
    return f


def buscar(f):
    """Ventas que cumplen los filtros, de la más nueva a la más vieja."""
    cond, params = [], []
    if f["caja"]:
        cond.append("v.caja_id = ?")
        params.append(f["caja"])
    else:
        # fecha < día siguiente: así entra TODO el último día
        hasta = (date.fromisoformat(f["hasta"]) + timedelta(days=1)).isoformat()
        cond += ["v.fecha >= ?", "v.fecha < ?"]
        params += [f["desde"], hasta]
    if f["forma"]:
        cond.append("v.forma_pago = ?")
        params.append(f["forma"])
    if f["estado"]:
        cond.append("v.estado = ?")
        params.append(f["estado"])
    if f["q"]:
        q = f["q"]
        if q.isdigit():                                   # "12" -> V-0012
            q = f"V-{int(q):04d}"
        # Por número de venta, por cliente (nombre o documento) o por un producto que llevó
        cond.append("(v.consecutivo = ? OR PLANO(v.cliente_nombre) LIKE '%' || PLANO(?) || '%' "
                    " OR v.cliente_documento = ? OR EXISTS (SELECT 1 FROM venta_lineas vl "
                    "   WHERE vl.venta_id = v.id AND PLANO(vl.producto_nombre) LIKE '%' || PLANO(?) || '%'))")
        params += [q.upper(), f["q"], f["q"], f["q"]]
    filas = get_db().execute(
        "SELECT v.*, c.numero AS caja_numero, c.estado AS caja_estado, "
        "       (SELECT COUNT(*) FROM devoluciones d WHERE d.venta_id = v.id) AS n_devoluciones "
        "FROM ventas v LEFT JOIN cajas c ON c.id = v.caja_id "
        f"WHERE {' AND '.join(cond)} ORDER BY v.id DESC LIMIT {LIMITE + 1}", params).fetchall()
    return filas[:LIMITE], len(filas) > LIMITE


def _venta_o_404(venta_id):
    fila = get_db().execute(
        "SELECT v.*, c.numero AS caja_numero, c.estado AS caja_estado FROM ventas v "
        "LEFT JOIN cajas c ON c.id = v.caja_id WHERE v.id = ?", (venta_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def puede_corregir(venta):
    """¿Este usuario puede corregir el pago de esta venta? Devuelve (sí/no, por qué no)."""
    if venta["estado"] != "completada":
        return False, "La venta está anulada."
    if venta["forma_pago"] == "credito":
        return False, "Es una venta a crédito: lo que debe el cliente se arregla en Cartera."
    if g.user["rol"] not in JEFES and venta["caja_estado"] != "abierta":
        return False, "La caja de esta venta ya se cerró: solo el administrador o el director técnico puede corregirla."
    return True, ""


def datos_panel(venta_id):
    """Todo lo que muestra el panel de la derecha para UNA venta."""
    from .devoluciones import FORMAS_REEMBOLSO, _lineas_devolvibles
    from .pos import pagos_de_venta
    db = get_db()
    venta = _venta_o_404(venta_id)
    lineas = db.execute("SELECT * FROM venta_lineas WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    devoluciones = db.execute(
        "SELECT * FROM devoluciones WHERE venta_id = ? ORDER BY id DESC", (venta_id,)).fetchall()
    correcciones = db.execute(
        "SELECT * FROM venta_correcciones_pago WHERE venta_id = ? ORDER BY id DESC", (venta_id,)).fetchall()
    caja_abierta = db.execute("SELECT id FROM cajas WHERE estado = 'abierta' LIMIT 1").fetchone()
    ok, por_que = puede_corregir(venta)
    return {
        "venta": venta, "lineas": lineas, "pagos": pagos_de_venta(venta_id),
        "devoluciones": devoluciones, "correcciones": correcciones,
        "puede_corregir": ok, "por_que_no": por_que,
        "es_jefe": g.user["rol"] in JEFES,
        "caja_abierta": caja_abierta is not None,
        "lineas_devolvibles": _lineas_devolvibles(venta_id) if venta["estado"] == "completada" else [],
        "formas_reembolso": FORMAS_REEMBOLSO,
    }


# ---------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------

@bp.route("/")
@login_required
def lista():
    f = _filtros()
    try:
        ventas, hay_mas = buscar(f)
    except ValueError:                         # fecha mal escrita en la dirección
        flash("Revisa las fechas de la búsqueda.", "error")
        return redirect(url_for("ventas.lista"))
    completadas = [v for v in ventas if v["estado"] == "completada"]
    elegida = request.args.get("venta", type=int)
    panel = datos_panel(elegida) if elegida else None
    return render_template("ventas/index.html", ventas=ventas, hay_mas=hay_mas, f=f, panel=panel,
                           total=sum(v["total"] for v in completadas), n=len(completadas),
                           estados=ESTADOS)


@bp.route("/<int:venta_id>/panel")
@login_required
def panel(venta_id):
    """Solo el panel de la derecha (lo pide static/js/ventas.js al tocar una venta)."""
    return render_template("ventas/_panel.html", p=datos_panel(venta_id))


# ---------------------------------------------------------------------
# Corregir el pago
# ---------------------------------------------------------------------

class _Error(Exception):
    """Algo que el usuario debe corregir; el mensaje se le muestra tal cual."""


def _parte_efectivo(forma, total, partes):
    """Cuánto de la venta fue en EFECTIVO (lo que cuenta para el cierre de caja)."""
    if forma == "efectivo":
        return total
    if forma == "mixto":
        return sum(m for f_, m in partes if f_ == "efectivo")
    return 0


def _texto_pago(forma, partes):
    """'Daviplata' o 'Mixto: Nequi $20.000 + Efectivo $5.000' (para la historia y la bitácora)."""
    if forma != "mixto":
        return fp.nombre(forma)
    return "Mixto: " + " + ".join(f"{fp.nombre(f_)} {pesos(m)}" for f_, m in partes)


def _leer_partes_mixto(formulario, total):
    """Partes de un pago mixto escrito en la corrección. Lo que falta es efectivo."""
    partes = []
    for forma in fp.FORMAS_MIXTO_OTRAS:
        texto = (formulario.get(f"monto_{forma}") or "").strip().replace(".", "").replace(",", ".")
        if not texto:
            continue
        try:
            monto = round(float(texto), 2)
        except ValueError:
            raise _Error(f"El valor de {fp.nombre(forma)} no es válido.")
        if monto < 0:
            raise _Error(f"El valor de {fp.nombre(forma)} no puede ser negativo.")
        if monto > 0:
            partes.append((forma, monto))
    otros = sum(m for _f, m in partes)
    if otros > total + 0.5:
        raise _Error(f"Las partes ({pesos(otros)}) suman más que la venta ({pesos(total)}).")
    efectivo = round(total - otros, 2)
    if efectivo >= 0.5:
        partes.append(("efectivo", efectivo))
    if len(partes) < 2:
        raise _Error("Un pago mixto necesita al menos dos formas. Si fue una sola, escógela arriba.")
    return partes


def corregir_pago(db, venta, nueva, partes, motivo):
    """Cambia la forma de pago de una venta y arregla la caja si ya estaba cerrada. No hace commit."""
    from .pos import pagos_de_venta
    antes_partes = [(p["forma_pago"], p["monto"]) for p in pagos_de_venta(venta["id"])]
    antes = _texto_pago(venta["forma_pago"], antes_partes)
    despues = _texto_pago(nueva, partes)
    if antes == despues:
        raise _Error("La forma de pago escogida es la misma que ya tiene la venta.")

    # venta_pagos guarda las partes SOLO de los pagos mixtos (igual que al cobrar en el POS)
    db.execute("DELETE FROM venta_pagos WHERE venta_id = ?", (venta["id"],))
    for forma, monto in (partes if nueva == "mixto" else []):
        db.execute("INSERT INTO venta_pagos (venta_id, forma_pago, monto, creado_en) VALUES (?,?,?,?)",
                   (venta["id"], forma, monto, ahora()))
    # Si ya no hay efectivo, el "recibido" y el cambio dejan de tener sentido
    efectivo_nuevo = _parte_efectivo(nueva, venta["total"], partes)
    db.execute("UPDATE ventas SET forma_pago = ?, pago_corregido = pago_corregido + 1, "
               "monto_recibido = CASE WHEN ? > 0 THEN monto_recibido ELSE NULL END, "
               "cambio = CASE WHEN ? > 0 THEN cambio ELSE 0 END WHERE id = ?",
               (nueva, efectivo_nuevo, efectivo_nuevo, venta["id"]))
    db.execute("INSERT INTO venta_correcciones_pago (venta_id, antes, despues, motivo, usuario_id, "
               "usuario_nombre, creado_en) VALUES (?,?,?,?,?,?,?)",
               (venta["id"], antes, despues, motivo, g.user["id"], g.user["nombre"], ahora()))

    # ¿Cambió el efectivo de una caja YA CERRADA? Entonces su diferencia cambia.
    cambio_efectivo = efectivo_nuevo - _parte_efectivo(venta["forma_pago"], venta["total"], antes_partes)
    if abs(cambio_efectivo) >= 0.5 and venta["caja_id"]:
        _rehacer_diferencia(db, venta["caja_id"], cambio_efectivo, f"corrección de pago de {venta['consecutivo']}")
    registrar("venta_pago_corregido", "ventas", venta["id"],
              f"{venta['consecutivo']}: {antes} → {despues}. Motivo: {motivo}")
    return antes, despues


def _rehacer_diferencia(db, caja_id, cambio_efectivo, porque):
    """La caja ya se cerró y el efectivo ESPERADO cambió en cambio_efectivo.

    diferencia = contado − esperado. El contado no cambia (fue lo que había), así que
    la diferencia baja lo mismo que subió el esperado. El faltante o sobrante que el
    programa había anotado solo (gasto u otro ingreso) se anula y se vuelve a anotar
    con el valor nuevo (cajas.registrar_diferencia). No mueve plata de ninguna caja.
    """
    from .cajas import registrar_diferencia
    caja = db.execute("SELECT * FROM cajas WHERE id = ?", (caja_id,)).fetchone()
    if caja is None or caja["estado"] != "cerrada" or caja["efectivo_contado"] is None:
        return                                     # caja abierta: el cierre lo calcula solo
    nota = f"Anulado solo por el programa: {porque} ({ahora()[:16]})."
    if caja["diferencia_gasto_id"]:
        db.execute("UPDATE gastos SET activo = 0, observaciones = COALESCE(observaciones, '') || ' ' || ? "
                   "WHERE id = ?", (nota, caja["diferencia_gasto_id"]))
    if caja["diferencia_ingreso_id"]:
        db.execute("UPDATE otros_ingresos SET activo = 0, observaciones = COALESCE(observaciones, '') || ' ' || ? "
                   "WHERE id = ?", (nota, caja["diferencia_ingreso_id"]))
    nueva = round(float(caja["diferencia"] or 0) - cambio_efectivo, 2)
    db.execute("UPDATE cajas SET diferencia = ?, diferencia_revisada = 0, diferencia_gasto_id = NULL, "
               "diferencia_ingreso_id = NULL WHERE id = ?", (nueva, caja_id))
    registrar_diferencia(db, caja_id)
    registrar("caja_diferencia_corregida", "cajas", caja_id,
              f"Caja #{caja['numero']}: diferencia {caja['diferencia']} → {nueva} por {porque}")


@bp.route("/<int:venta_id>/corregir-pago", methods=["POST"])
@login_required
def corregir_pago_ruta(venta_id):
    db = get_db()
    venta = _venta_o_404(venta_id)
    ok, por_que = puede_corregir(venta)
    volver = redirect(url_for("ventas.lista", venta=venta_id, **_filtros_para_volver()))
    if not ok:
        flash(por_que, "error")
        return volver
    nueva = request.form.get("forma_pago") or ""
    motivo = " ".join((request.form.get("motivo") or "").split())[:200]
    try:
        if nueva not in fp.FORMAS_VENTA_SIMPLE + ("mixto",):
            raise _Error("Escoge cómo pagó de verdad el cliente.")
        if len(motivo) < 5:
            raise _Error("Escribe el motivo de la corrección (por ejemplo: «pagó por Daviplata, se marcó efectivo»).")
        partes = (_leer_partes_mixto(request.form, venta["total"]) if nueva == "mixto"
                  else [(nueva, venta["total"])])
        antes, despues = corregir_pago(db, venta, nueva, partes, motivo)
    except _Error as e:
        db.rollback()
        flash(str(e), "error")
        return volver
    db.commit()
    flash(f"Pago de {venta['consecutivo']} corregido: {antes} → {despues}.", "ok")
    return volver


def _filtros_para_volver():
    """Los filtros de la lista viajan en campos ocultos para volver a la misma búsqueda."""
    return {k: request.form.get(f"f_{k}") for k in ("desde", "hasta", "q", "forma", "estado", "caja")
            if request.form.get(f"f_{k}")}
