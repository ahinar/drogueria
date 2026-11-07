"""CONFIGURACIÓN → FORMAS DE PAGO (versión 1.1.17, pedido de Fernando).

QUÉ SE PUEDE HACER
------------------
  1. AGREGAR UNA CUENTA nueva (Bancolombia, Nu, Bre-B...): nombre, ícono, saldo
     inicial y desde qué fecha. Aparece sola en el cobro del POS, el pago mixto,
     el cierre de caja, Bancos, gastos, abonos, devoluciones y reportes.
  2. OCULTAR una forma de pago que no se usa (ej. Tarjeta si no hay datáfono, o
     una cuenta que se cerró). Deja de OFRECERSE para cosas nuevas, pero NO SE BORRA:
     las ventas viejas pagadas así siguen en los reportes y la cuenta sigue en
     Bancos con su saldo. Se puede volver a mostrar cuando quiera.
  3. CAMBIAR EL ORDEN de las cuentas (la más usada de primera).
  4. Cambiar el nombre o el ícono de una cuenta.

POR QUÉ NO SE PUEDE BORRAR
--------------------------
Si se borrara «Nequi», las ventas, gastos y abonos que dicen «nequi» quedarían sin
saber qué eran, y Bancos dejaría de cuadrar. Por eso solo se oculta.

DÓNDE SE GUARDA
---------------
  - Las cuentas: tabla cuentas_bancarias (clave, nombre, icono, orden, oculta...).
  - Tarjeta, transferencia, crédito y mixto ocultas: config «formas_ocultas»
    (ej. "tarjeta,mixto"). El efectivo no se puede ocultar.
La lectura de todo esto está en app/formas_pago.py.
"""
import re
import unicodedata
from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from . import formas_pago as fp
from .audit import registrar
from .auth import roles_required
from .db import ahora, get_db
from .formato import pesos
from .utiles import leer_numero

bp = Blueprint("formas_pago_cfg", __name__, url_prefix="/configuracion/formas-pago")

# Íconos para escoger (emojis: se ven igual en todo el programa, sin imágenes)
ICONOS = ["🏦", "📱", "🔴", "🟣", "🟡", "🟢", "🔵", "💜", "💳", "🏧", "💰", "🪙", "📲", "⭐"]


def _clave_de(nombre):
    """'Banco de Bogotá' → 'banco_de_bogota' (la palabra que se guarda en la base de datos)."""
    sin_tildes = unicodedata.normalize("NFD", nombre.lower())
    sin_tildes = "".join(ch for ch in sin_tildes if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", sin_tildes).strip("_")[:30]


def _ocultas_fijas():
    fila = get_db().execute("SELECT valor FROM config WHERE clave = 'formas_ocultas'").fetchone()
    return {x for x in ((fila[0] if fila else "") or "").split(",") if x in fp.OCULTABLES}


def _guardar_ocultas_fijas(ocultas):
    db = get_db()
    db.execute("INSERT INTO config (clave, valor) VALUES ('formas_ocultas', ?) "
               "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor", (",".join(sorted(ocultas)),))


@bp.route("/")
@roles_required("administrador")
def ver():
    from .bancos import saldo
    db = get_db()
    cuentas = [dict(c, saldo=saldo(db, c)) for c in db.execute(
        "SELECT * FROM cuentas_bancarias WHERE activa = 1 ORDER BY COALESCE(orden, id), id")]
    ocultas = _ocultas_fijas()
    fijas = [{"clave": k, "nombre": fp.FIJAS[k][0], "icono": fp.FIJAS[k][1], "oculta": k in ocultas}
             for k in fp.OCULTABLES]
    return render_template("configuracion/formas_pago.html", cuentas=cuentas, fijas=fijas, iconos=ICONOS,
                           hoy=date.today().isoformat())


@bp.route("/agregar", methods=["POST"])
@roles_required("administrador")
def agregar():
    """Cuenta nueva: nombre, ícono, saldo inicial y desde cuándo."""
    db = get_db()
    nombre = " ".join((request.form.get("nombre") or "").split())[:40]
    icono = request.form.get("icono") if request.form.get("icono") in ICONOS else "🏦"
    clave = _clave_de(nombre)
    if len(nombre) < 2 or not clave:
        flash("Escribe el nombre de la cuenta (ej. Bancolombia).", "error")
        return redirect(url_for("formas_pago_cfg.ver"))
    existente = db.execute("SELECT nombre, activa FROM cuentas_bancarias WHERE clave = ? OR LOWER(nombre) = LOWER(?)",
                           (clave, nombre)).fetchone()
    if clave in fp.RESERVADAS or existente:
        flash(f"Ya existe una forma de pago llamada «{existente['nombre'] if existente else nombre}».", "error")
        return redirect(url_for("formas_pago_cfg.ver"))
    texto = (request.form.get("saldo_inicial") or "").strip()
    saldo = leer_numero(texto.lstrip("-"), vacio=0.0)
    if saldo is None:
        flash("Escribe el saldo inicial como un número (ej. 250000), o déjalo vacío.", "error")
        return redirect(url_for("formas_pago_cfg.ver"))
    if texto.startswith("-"):
        saldo = -saldo
    fecha = (request.form.get("fecha_inicial") or date.today().isoformat()).strip()
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        flash("La fecha de arranque no es válida.", "error")
        return redirect(url_for("formas_pago_cfg.ver"))
    orden = db.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM cuentas_bancarias").fetchone()[0]
    cur = db.execute("INSERT INTO cuentas_bancarias (clave, nombre, icono, orden, oculta, saldo_inicial, fecha_inicial, "
                     "activa, creado_en) VALUES (?, ?, ?, ?, 0, ?, ?, 1, ?)",
                     (clave, nombre, icono, orden, saldo, fecha, ahora()))
    db.commit()
    fp.olvidar()
    registrar("forma_pago_agregada", "cuentas_bancarias", cur.lastrowid,
              f"{nombre} ({clave}) saldo_inicial={saldo} desde={fecha}")
    flash(f"Cuenta {icono} {nombre} agregada: ya sale en el cobro del POS y en Bancos "
          f"(arranca el {fecha} con {pesos(saldo)}).", "ok")
    return redirect(url_for("formas_pago_cfg.ver"))


@bp.route("/<clave>/editar", methods=["POST"])
@roles_required("administrador")
def editar(clave):
    """Cambiar el nombre o el ícono de una cuenta (la clave NO cambia: es la que está en lo viejo)."""
    db = get_db()
    c = db.execute("SELECT * FROM cuentas_bancarias WHERE clave = ?", (clave,)).fetchone()
    if c is None:
        flash("Esa cuenta no existe.", "error")
        return redirect(url_for("formas_pago_cfg.ver"))
    nombre = " ".join((request.form.get("nombre") or "").split())[:40] or c["nombre"]
    icono = request.form.get("icono") if request.form.get("icono") in ICONOS else (c["icono"] or "🏦")
    otro = db.execute("SELECT 1 FROM cuentas_bancarias WHERE LOWER(nombre) = LOWER(?) AND id <> ?",
                      (nombre, c["id"])).fetchone()
    if otro or _clave_de(nombre) in fp.RESERVADAS:
        flash(f"Ya existe una forma de pago llamada «{nombre}».", "error")
        return redirect(url_for("formas_pago_cfg.ver"))
    db.execute("UPDATE cuentas_bancarias SET nombre = ?, icono = ?, actualizado_en = ? WHERE id = ?",
               (nombre, icono, ahora(), c["id"]))
    db.commit()
    fp.olvidar()
    registrar("forma_pago_editada", "cuentas_bancarias", c["id"], f"{c['nombre']} → {nombre} {icono}")
    flash(f"Cuenta guardada: {icono} {nombre}.", "ok")
    return redirect(url_for("formas_pago_cfg.ver"))


@bp.route("/<clave>/mostrar", methods=["POST"])
@roles_required("administrador")
def mostrar(clave):
    """Ocultar o volver a mostrar una forma de pago (?ocultar=1 o 0)."""
    db = get_db()
    ocultar = request.form.get("ocultar") == "1"
    if clave == "efectivo":
        flash("El efectivo no se puede ocultar: siempre hay caja.", "error")
        return redirect(url_for("formas_pago_cfg.ver"))
    if clave in fp.OCULTABLES:
        ocultas = _ocultas_fijas()
        (ocultas.add if ocultar else ocultas.discard)(clave)
        _guardar_ocultas_fijas(ocultas)
        nombre = fp.FIJAS[clave][0]
    else:
        c = db.execute("SELECT * FROM cuentas_bancarias WHERE clave = ?", (clave,)).fetchone()
        if c is None:
            flash("Esa cuenta no existe.", "error")
            return redirect(url_for("formas_pago_cfg.ver"))
        db.execute("UPDATE cuentas_bancarias SET oculta = ?, actualizado_en = ? WHERE id = ?",
                   (1 if ocultar else 0, ahora(), c["id"]))
        nombre = c["nombre"]
    db.commit()
    fp.olvidar()
    registrar("forma_pago_oculta" if ocultar else "forma_pago_visible", "formas_pago", None, clave)
    if ocultar:
        flash(f"{nombre} quedó oculta: ya no sale para cobrar ni registrar cosas nuevas. Lo de antes sigue "
              f"en los reportes{' y su saldo en Bancos' if clave not in fp.OCULTABLES else ''}.", "ok")
    else:
        flash(f"{nombre} se vuelve a mostrar.", "ok")
    return redirect(url_for("formas_pago_cfg.ver"))


@bp.route("/<clave>/mover", methods=["POST"])
@roles_required("administrador")
def mover(clave):
    """Subir o bajar una cuenta en la lista (?hacia=arriba o abajo)."""
    db = get_db()
    ids = [f["id"] for f in db.execute(
        "SELECT id FROM cuentas_bancarias WHERE activa = 1 ORDER BY COALESCE(orden, id), id")]
    fila = db.execute("SELECT id FROM cuentas_bancarias WHERE clave = ?", (clave,)).fetchone()
    if fila is None or fila["id"] not in ids:
        return redirect(url_for("formas_pago_cfg.ver"))
    i = ids.index(fila["id"])
    j = i - 1 if request.form.get("hacia") == "arriba" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]           # se cambian de puesto
        for puesto, cuenta_id in enumerate(ids, start=1):
            db.execute("UPDATE cuentas_bancarias SET orden = ? WHERE id = ?", (puesto, cuenta_id))
        db.commit()
        fp.olvidar()
    return redirect(url_for("formas_pago_cfg.ver"))
