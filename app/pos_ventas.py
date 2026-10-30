"""POS · VENTAS: cobrar, venta libre, comprobante, tirilla, cajón y anular.

Versión 1.1.15: esto estaba en app/pos.py (que tenía más de 1.600 líneas). Ahora el POS
está repartido en tres archivos, por tema, y las direcciones (/pos/...) son las mismas:
    pos.py           -> la caja: abrir, cerrar, movimientos de plata, gastos, otros ingresos
    pos_productos.py -> buscar productos, ficha «i» y «Editar producto»
    pos_ventas.py    -> (este) cobrar, venta libre, comprobante, tirilla, cajón, anular
Las rutas se registran en el mismo blueprint "pos" (bp), por eso url_for('pos.…') no cambia.
"""
from datetime import date
import json

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from . import presentaciones as pres
from .audit import registrar
from .auth import login_required, roles_required
from .configuracion import obtener_config
from .db import ahora, get_db
from .formato import pesos
# Lo que comparten las tres partes del POS (está en app/pos.py)
from .pos import (bp, _VentaError, _json_error, _fmt_cant, _a_pesos, _caja_abierta,
                  SQL_LOTE_VENDIBLE, _siguiente_consecutivo_venta, _pagos_mixtos, NOMBRES_PAGO, FORMAS_PAGO)


@bp.route("/api/abrir-cajon", methods=["POST"])
@login_required
def api_abrir_cajon():
    """Abre el cajón monedero sin imprimir (ver app/cajon.py).

    motivo = "cobro" (lo llama el POS después de cobrar) o "manual" (botón del menú ☰).
    Queda en la bitácora quién lo abrió y por qué: así se controla el efectivo.
    """
    from . import cajon
    motivo = "cobro" if request.form.get("motivo") == "cobro" else "manual"
    if _caja_abierta() is None:
        return _json_error("No hay caja abierta.")
    cfg = obtener_config()
    ok, error = cajon.abrir(cfg.get("impresora_tirillas"), cfg.get("cajon_orden") or "estandar")
    registrar("cajon_abierto", "cajas", None, f"motivo={motivo}" + ("" if ok else f" error={error}"))
    # "impresora": a cuál le llegó la orden (el POS lo muestra para revisar que sea la correcta)
    return jsonify({"ok": True, "impresora": cajon.impresora_usada(cfg.get("impresora_tirillas"))}) \
        if ok else _json_error(error)


@bp.route("/api/abrir-cajon-apertura", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico", "auxiliar")
def api_abrir_cajon_apertura():
    """Abre el cajón monedero ANTES de abrir la caja (versión 1.1.8, pedido de Fernando).

    En la mañana la caja del programa está cerrada y el cajón físico también:
    para contar la plata con la que se empieza hay que abrirlo. El botón
    "Abrir cajón" del POS (api_abrir_cajon, arriba) solo sirve con la caja abierta,
    por eso la pantalla "Abrir caja" usa este otro, que funciona con la caja cerrada.
    Lo puede usar quien pueda abrir caja, y queda en la bitácora (motivo=apertura).
    """
    from . import cajon
    cfg = obtener_config()
    ok, error = cajon.abrir(cfg.get("impresora_tirillas"), cfg.get("cajon_orden") or "estandar")
    registrar("cajon_abierto", "cajas", None, "motivo=apertura (contar antes de abrir caja)"
              + ("" if ok else f" error={error}"))
    return jsonify({"ok": True, "impresora": cajon.impresora_usada(cfg.get("impresora_tirillas"))}) \
        if ok else _json_error(error)


@bp.route("/api/cobrar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico", "auxiliar")
def api_cobrar():
    """Registra una venta completa. O se guarda TODO, o no se guarda NADA."""
    caja = _caja_abierta()
    if caja is None:
        return _json_error("No hay caja abierta.")

    try:
        carrito = json.loads(request.form.get("carrito", "[]"))
    except (json.JSONDecodeError, TypeError):
        return _json_error("El carrito llegó dañado. Intenta de nuevo.")
    if not isinstance(carrito, list) or not carrito:
        return _json_error("El carrito está vacío.")

    forma_pago = (request.form.get("forma_pago") or "").strip().lower()
    if forma_pago not in FORMAS_PAGO:
        return _json_error("Forma de pago inválida.")

    cliente_nombre = (request.form.get("cliente_nombre") or "").strip() or "Consumidor final"
    cliente_doc = (request.form.get("cliente_documento") or "").strip() or None
    observaciones = (request.form.get("observaciones") or "").strip() or None

    db = get_db()
    # ---- VENTA A CRÉDITO: necesita un cliente registrado y activo ----
    cliente_credito, saldo_previo = None, 0.0
    if forma_pago == "credito":
        from . import cartera
        cliente_credito = db.execute("SELECT * FROM clientes WHERE id = ? AND activo = 1",
                                     (request.form.get("cliente_id", type=int),)).fetchone()
        if cliente_credito is None:
            return _json_error("Para vender a crédito escoge un cliente registrado (Cartera → Nuevo cliente).")
        saldo_previo = cartera.saldo(cliente_credito["id"])     # lo que ya debía
        cliente_nombre = cliente_credito["nombre"]
        cliente_doc = cliente_credito["documento"]

    hoy = date.today().isoformat()
    cambios_precio = []   # textos para la bitácora si el cajero cambió algún precio
    ventas_libres = []    # textos para la bitácora de cada línea de venta libre

    db.execute("BEGIN IMMEDIATE")
    try:
        consecutivo = _siguiente_consecutivo_venta()
        cur = db.execute(
            "INSERT INTO ventas (consecutivo, fecha, caja_id, cliente_nombre, cliente_documento, "
            "subtotal, descuento, iva, total, forma_pago, observaciones, usuario_id, "
            "usuario_nombre, estado, creado_en) "
            "VALUES (?,?,?,?,?,0,0,0,0,?,?,?,?,'completada',?)",
            (consecutivo, ahora(), caja["id"], cliente_nombre, cliente_doc, forma_pago,
             observaciones, g.user["id"], g.user["nombre"], ahora()),
        )
        venta_id = cur.lastrowid

        sum_subtotal = sum_descuento = sum_iva = sum_total = 0

        for item in carrito:
            # ---- VENTA LIBRE: algo que no está en el inventario ----
            # (una inyectología, una toma de presión...). No descuenta stock.
            if isinstance(item, dict) and item.get("libre"):
                base, descuento, iva_valor, total_linea, texto = _guardar_linea_libre(db, venta_id, item)
                ventas_libres.append(texto)
                sum_subtotal += base
                sum_descuento += descuento
                sum_iva += iva_valor
                sum_total += total_linea
                continue
            try:
                producto_id = int(item.get("producto_id"))
                # 0 = unidad principal; otro número = sobre, caja... (producto_presentaciones)
                presentacion_id = int(item.get("presentacion_id") or 0)
                cantidad = round(float(item.get("cantidad")), 4)
                desc_pct = float(item.get("descuento_pct") or 0)
            except (TypeError, ValueError, AttributeError):
                raise _VentaError("Hay una línea del carrito con datos inválidos.")
            if cantidad <= 0:
                raise _VentaError("La cantidad de cada producto debe ser mayor a cero.")
            if not 0 <= desc_pct <= 100:
                raise _VentaError("El descuento debe estar entre 0 y 100 %.")

            prod = db.execute(
                "SELECT * FROM productos WHERE id = ? AND activo = 1", (producto_id,)
            ).fetchone()
            if prod is None:
                raise _VentaError("Uno de los productos ya no existe o está inactivo.")
            nombre = prod["nombre"]
            if prod["control_especial"]:
                raise _VentaError(f"{nombre}: es de control especial y todavía no se puede "
                                  "vender desde el POS (falta el libro de control).")
            # ---- PRESENTACIÓN: unidad, sobre, caja... ----
            # El precio y el precio máximo salen de la presentación elegida.
            # "factor" dice cuántas unidades del inventario se descuentan por
            # cada una que se vende (1 caja x 100 -> 100 unidades).
            presentacion = pres.presentacion_para_vender(producto_id, presentacion_id)
            if presentacion is None:
                raise _VentaError(f"{nombre}: esa presentación ya no existe. "
                                  "Quítalo del carrito y agrégalo de nuevo.")
            if not presentacion.get("vendible", True):
                raise _VentaError(f"{nombre}: no se vende suelto. Véndelo por "
                                  "una de sus presentaciones (sobre, caja...).")
            factor = float(presentacion["factor"])
            if presentacion_id != pres.PRINCIPAL:
                nombre = f"{nombre} ({presentacion['nombre']})"
            precio = presentacion["precio"]
            if precio <= 0:
                raise _VentaError(f"{nombre}: no tiene precio de venta.")

            # ---- CAMBIO DE PRECIO AL VENDER (Opción B) ----
            # Por defecto el precio SIEMPRE es el que está en la base de datos
            # (el navegador no puede imponerlo). Solo si el cajero cambió el
            # precio a propósito, llegan dos campos especiales:
            #   precio_nuevo  -> el precio que escribió
            #   motivo_precio -> por qué lo cambió (obligatorio)
            # Cualquier otro campo de precio que mande el navegador se ignora.
            precio_original = precio
            motivo_precio = None
            if item.get("precio_nuevo") not in (None, ""):
                try:
                    precio_nuevo = float(item.get("precio_nuevo"))
                except (TypeError, ValueError):
                    raise _VentaError(f"{nombre}: el precio nuevo no es válido.")
                if precio_nuevo <= 0:
                    raise _VentaError(f"{nombre}: el precio nuevo debe ser mayor a cero.")
                # Solo cuenta como "cambio" si de verdad es distinto (más de 1 centavo)
                if abs(precio_nuevo - precio_original) > 0.01:
                    motivo_precio = str(item.get("motivo_precio") or "").strip()
                    if len(motivo_precio) < 3:
                        raise _VentaError(f"{nombre}: indica el motivo del cambio de precio.")
                    # Los medicamentos tienen un precio máximo regulado: nunca se supera.
                    tope = presentacion["precio_maximo"]
                    if tope > 0 and precio_nuevo > tope + 0.01:
                        raise _VentaError(
                            f"{nombre}: el precio ({pesos(precio_nuevo)}) supera el precio "
                            f"máximo permitido ({pesos(tope)}).")
                    precio = precio_nuevo
                    cambios_precio.append(
                        f"{prod['codigo']} {nombre}: {pesos(precio_original)} -> "
                        f"{pesos(precio_nuevo)} (motivo: {motivo_precio})")

            lotes = db.execute(
                "SELECT l.id, l.lote, l.vencimiento, l.cantidad_disponible FROM lotes l "
                f"WHERE l.producto_id = ? AND {SQL_LOTE_VENDIBLE} "
                "ORDER BY (l.vencimiento IS NULL OR l.vencimiento = ''), l.vencimiento, l.id",
                (producto_id, hoy),
            ).fetchall()
            # Unidades del inventario que salen: cantidad vendida x factor.
            # Si en esta venta hay otra línea del mismo producto (ej: 1 caja y
            # 5 sueltas), sus unidades YA se restaron de los lotes más abajo
            # (dentro de esta misma transacción), así que "disponible" ya lo refleja.
            unidades = round(cantidad * factor, 4)
            disponible = sum(l["cantidad_disponible"] for l in lotes)
            if unidades > disponible + 1e-9:
                if factor == 1:
                    raise _VentaError(f"{nombre}: solo hay {_fmt_cant(disponible)} disponible(s) "
                                      f"y pediste {_fmt_cant(cantidad)}.")
                raise _VentaError(f"{nombre}: pediste {_fmt_cant(cantidad)} = "
                                  f"{_fmt_cant(unidades)} unidades y solo hay "
                                  f"{_fmt_cant(max(disponible, 0))}.")

            pendiente = unidades
            asignaciones = []
            for l in lotes:
                if pendiente <= 1e-9:
                    break
                toma = round(min(pendiente, l["cantidad_disponible"]), 4)
                asignaciones.append({"lote_id": l["id"], "lote": l["lote"],
                                     "vencimiento": l["vencimiento"], "cantidad": toma})
                pendiente -= toma

            bruto = cantidad * precio
            descuento = _a_pesos(bruto * desc_pct / 100)
            total_linea = _a_pesos(bruto) - descuento
            tarifa = float(prod["iva_tarifa"] or 0)
            if prod["iva_tipo"] == "gravado" and tarifa > 0:
                base = _a_pesos(total_linea / (1 + tarifa / 100))
                iva_valor = total_linea - base
            else:
                base, iva_valor = total_linea, 0

            db.execute(
                "INSERT INTO venta_lineas (venta_id, producto_id, producto_codigo, producto_nombre, "
                "presentacion, presentacion_id, factor, cantidad, precio_unitario, descuento_linea, "
                "iva_tipo, iva_tarifa, subtotal, iva_valor, total, lotes_json, "
                "precio_original, motivo_precio) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (venta_id, producto_id, prod["codigo"], prod["nombre"], presentacion["nombre"],
                 presentacion_id or None, factor, cantidad, precio, descuento,
                 prod["iva_tipo"], tarifa, base, iva_valor, total_linea,
                 json.dumps(asignaciones, ensure_ascii=False),
                 precio_original, motivo_precio),
            )

            for a in asignaciones:
                db.execute(
                    "UPDATE lotes SET cantidad_disponible = cantidad_disponible - ?, "
                    "actualizado_en = ? WHERE id = ?",
                    (a["cantidad"], ahora(), a["lote_id"]),
                )
                db.execute(
                    "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, "
                    "cantidad, referencia, referencia_id, usuario_id, usuario_nombre, creado_en) "
                    "VALUES (?,?,?, 'venta', ?, ?, ?, ?, ?, ?)",
                    (ahora(), a["lote_id"], producto_id, -a["cantidad"], f"Venta {consecutivo}",
                     venta_id, g.user["id"], g.user["nombre"], ahora()),
                )

            sum_subtotal += base
            sum_descuento += descuento
            sum_iva += iva_valor
            sum_total += total_linea

        if forma_pago == "efectivo":
            recibido_txt = (request.form.get("monto_recibido") or "").strip()
            try:
                recibido = float(recibido_txt.replace(",", ".")) if recibido_txt else float(sum_total)
            except ValueError:
                raise _VentaError("El monto recibido no es válido.")
            if recibido + 1e-9 < sum_total:
                raise _VentaError(f"El efectivo recibido ({pesos(recibido)}) no alcanza para "
                                  f"el total ({pesos(sum_total)}).")
            cambio = recibido - sum_total
        elif forma_pago == "credito":
            # No se recibe plata: queda debiendo. Si tiene cupo, no puede pasarse.
            if cliente_credito["cupo"] is not None and saldo_previo + sum_total > cliente_credito["cupo"] + 0.5:
                disponible = max(cliente_credito["cupo"] - saldo_previo, 0)
                raise _VentaError(
                    f"{cliente_credito['nombre']} no tiene cupo suficiente: debe {pesos(saldo_previo)}, "
                    f"su cupo es {pesos(cliente_credito['cupo'])} y le quedan {pesos(disponible)} disponibles.")
            recibido, cambio = 0.0, 0.0
            db.execute("UPDATE ventas SET cliente_id = ? WHERE id = ?", (cliente_credito["id"], venta_id))
        elif forma_pago == "mixto":
            # Una parte por Nequi/Davivienda/tarjeta y el resto en efectivo: se guarda cada parte
            partes, recibido, cambio = _pagos_mixtos(request.form, sum_total)
            for forma, monto in partes:
                db.execute("INSERT INTO venta_pagos (venta_id, forma_pago, monto, creado_en) VALUES (?,?,?,?)",
                           (venta_id, forma, monto, ahora()))
        else:
            recibido, cambio = float(sum_total), 0.0

        # ¿Era una cotización cargada en el POS? Queda "convertida" (ver app/cotizaciones.py)
        from . import cotizaciones
        cotizaciones.marcar_convertida(db, request.form.get("cotizacion_id", type=int), venta_id)

        db.execute(
            "UPDATE ventas SET subtotal = ?, descuento = ?, iva = ?, total = ?, "
            "monto_recibido = ?, cambio = ? WHERE id = ?",
            (sum_subtotal, sum_descuento, sum_iva, sum_total, recibido, cambio, venta_id),
        )
        db.commit()
    except _VentaError as e:
        db.rollback()
        return _json_error(str(e))
    except Exception:
        db.rollback()
        raise

    registrar("venta_creada", "ventas", venta_id,
              f"consecutivo={consecutivo} total={sum_total} forma_pago={forma_pago}")
    # Opción B: cualquiera puede cambiar el precio, pero SIEMPRE queda registrado.
    for texto in cambios_precio:
        registrar("venta_precio_modificado", "ventas", venta_id,
                  f"{consecutivo} · {texto}")
    for texto in ventas_libres:
        registrar("venta_libre", "ventas", venta_id, f"{consecutivo} · {texto}")
    return jsonify({"ok": True, "venta_id": venta_id, "consecutivo": consecutivo,
                    "total": sum_total, "cambio": cambio,
                    "url_comprobante": url_for("pos.comprobante", venta_id=venta_id)})

# Tarifas de IVA que se pueden escoger en una venta libre (0 = sin IVA)
TARIFAS_LIBRE = (0, 5, 19)


def _guardar_linea_libre(db, venta_id, item):
    """Guarda una línea de VENTA LIBRE y devuelve (base, descuento, iva, total, texto).

    Lo que manda el navegador:
      descripcion  -> qué se vendió (ej: "Inyectología")
      precio       -> precio de CADA UNA, con IVA incluido
      cantidad, descuento_pct
      iva_tarifa   -> 0, 5 o 19
      costo        -> (opcional) cuánto le cuesta a la droguería cada una
      venta_rapida_id -> (opcional, versión 1.1.13) de cuál VENTA RÁPIDA salió
                         (Fotocopia, Dulcería...). Sirve para el reporte de Ventas.
    Aquí el precio SÍ lo pone el cajero (no hay un precio guardado con qué
    compararlo), por eso no se pide motivo; todo queda en la bitácora.
    """
    descripcion = " ".join(str(item.get("descripcion") or "").split())[:120]
    if len(descripcion) < 3:
        raise _VentaError("Venta libre: escribe qué se está vendiendo (mínimo 3 letras).")
    try:
        precio = float(item.get("precio"))
        cantidad = round(float(item.get("cantidad")), 4)
        desc_pct = float(item.get("descuento_pct") or 0)
        tarifa = float(item.get("iva_tarifa") or 0)
        costo_txt = item.get("costo")
        costo = float(costo_txt) if costo_txt not in (None, "") else None
    except (TypeError, ValueError):
        raise _VentaError(f"{descripcion}: hay un dato inválido en la venta libre.")
    if precio <= 0:
        raise _VentaError(f"{descripcion}: el precio debe ser mayor a cero.")
    if cantidad <= 0:
        raise _VentaError(f"{descripcion}: la cantidad debe ser mayor a cero.")
    if not 0 <= desc_pct <= 100:
        raise _VentaError("El descuento debe estar entre 0 y 100 %.")
    if tarifa not in TARIFAS_LIBRE:
        raise _VentaError(f"{descripcion}: la tarifa de IVA debe ser 0, 5 o 19 %.")
    if costo is not None and costo < 0:
        raise _VentaError(f"{descripcion}: el costo no puede ser negativo.")

    # ¿Salió de una venta rápida? Solo se guarda si de verdad existe.
    vr_id = item.get("venta_rapida_id")
    vr_id = int(vr_id) if str(vr_id or "").isdigit() else None
    if vr_id and not db.execute("SELECT 1 FROM ventas_rapidas WHERE id = ?", (vr_id,)).fetchone():
        vr_id = None

    # Mismas cuentas que una línea normal (ver más abajo en api_cobrar)
    bruto = cantidad * precio
    descuento = _a_pesos(bruto * desc_pct / 100)
    total_linea = _a_pesos(bruto) - descuento
    if tarifa > 0:
        base = _a_pesos(total_linea / (1 + tarifa / 100))
        iva_valor = total_linea - base
    else:
        base, iva_valor = total_linea, 0

    db.execute(
        "INSERT INTO venta_lineas (venta_id, producto_id, producto_codigo, producto_nombre, "
        "presentacion, factor, cantidad, precio_unitario, descuento_linea, iva_tipo, iva_tarifa, "
        "subtotal, iva_valor, total, lotes_json, precio_original, es_libre, costo_libre, venta_rapida_id) "
        "VALUES (?, NULL, 'LIBRE', ?, NULL, 1, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, 1, ?, ?)",
        (venta_id, descripcion, cantidad, precio, descuento,
         "gravado" if tarifa > 0 else "excluido", tarifa, base, iva_valor, total_linea,
         precio, costo, vr_id),
    )
    texto = f"{descripcion}: {_fmt_cant(cantidad)} x {pesos(precio)} = {pesos(total_linea)}"
    return base, descuento, iva_valor, total_linea, texto


def _venta_o_404(venta_id):
    venta = get_db().execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    if venta is None:
        abort(404)
    return venta

@bp.route("/venta/<int:venta_id>")
@login_required
def comprobante(venta_id):
    """Comprobante de venta (interno, sin valor tributario), listo para imprimir."""
    venta = _venta_o_404(venta_id)
    lineas = get_db().execute(
        "SELECT * FROM venta_lineas WHERE venta_id = ? ORDER BY id", (venta_id,)
    ).fetchall()
    # Si fue a crédito, mostramos cuánto debe en total el cliente (ver app/cartera.py)
    saldo_cliente = None
    if venta["forma_pago"] == "credito" and venta["cliente_id"]:
        from . import cartera
        saldo_cliente = cartera.saldo(venta["cliente_id"])
    return render_template("pos/comprobante.html", venta=venta, lineas=lineas,
                           config=obtener_config(), saldo_cliente=saldo_cliente,
                           pagos=pagos_de_venta(venta_id), nombres_pago=NOMBRES_PAGO)


def pagos_de_venta(venta_id):
    """Partes de un PAGO MIXTO: [{"forma_pago": "nequi", "monto": 20000}, ...] (vacío si no es mixto)."""
    return get_db().execute(
        "SELECT forma_pago, monto FROM venta_pagos WHERE venta_id = ? "
        "ORDER BY CASE forma_pago WHEN 'efectivo' THEN 9 ELSE 0 END, id", (venta_id,)).fetchall()

def _imprimir_directo(venta_id):
    """Manda la tirilla de la venta a la impresora del PC principal y lo anota en la bitácora."""
    from .tirilla_directa import imprimir_venta
    ok, error = imprimir_venta(venta_id)
    registrar("tirilla_impresa", "ventas", venta_id, "directa" + ("" if ok else f" error={error}"))
    return ok, error


@bp.route("/api/imprimir-tirilla", methods=["POST"])
@login_required
def api_imprimir_tirilla():
    """Imprime la tirilla DIRECTA (app/tirilla_directa.py) en la impresora del PC principal.

    venta_id = número de la venta, o "ultima" (botón «Reimprimir último»).
    La usa el POS desde cualquier computador: el del mostrador o el portátil.
    """
    pedido = (request.form.get("venta_id") or "").strip()
    if pedido == "ultima":
        fila = get_db().execute("SELECT id FROM ventas ORDER BY id DESC LIMIT 1").fetchone()
        if fila is None:
            return _json_error("Todavía no hay ventas.")
        venta_id = fila["id"]
    elif pedido.isdigit():
        venta_id = int(pedido)
    else:
        return _json_error("Venta inválida.")
    ok, error = _imprimir_directo(venta_id)
    return jsonify({"ok": True}) if ok else _json_error(error)


@bp.route("/venta/<int:venta_id>/imprimir", methods=["POST"])
@login_required
def imprimir_directo(venta_id):
    """Botón «Imprimir en el mostrador» de la página del comprobante."""
    _venta_o_404(venta_id)
    ok, error = _imprimir_directo(venta_id)
    if ok:
        return redirect(url_for("pos.comprobante", venta_id=venta_id, impresa=1))
    return redirect(url_for("pos.comprobante", venta_id=venta_id, error=error))


@bp.route("/venta/ultima")
@login_required
def ultima_venta():
    """Atajo para 'Reimprimir último'."""
    fila = get_db().execute("SELECT id FROM ventas ORDER BY id DESC LIMIT 1").fetchone()
    if fila is None:
        flash("Todavía no hay ventas.", "error")
        return redirect(url_for("pos.index"))
    return redirect(url_for("pos.comprobante", venta_id=fila["id"]))

@bp.route("/ventas")
@login_required
def ventas_lista():
    """Versión 1.1.14: «Últimas ventas» es ahora la pantalla Ventas (app/ventas.py), con
    la lista a la izquierda y el carrito de la venta escogida a la derecha. Esta dirección
    vieja lleva allá, mostrando las ventas de la caja abierta (o de la última)."""
    caja = _caja_abierta() or get_db().execute("SELECT * FROM cajas ORDER BY id DESC LIMIT 1").fetchone()
    return redirect(url_for("ventas.lista", caja=caja["id"]) if caja else url_for("ventas.lista"))

@bp.route("/venta/<int:venta_id>/anular", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def anular_venta(venta_id):
    """Anula una venta: devuelve las unidades a los MISMOS lotes de donde salieron."""
    venta = _venta_o_404(venta_id)
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("Debes escribir el motivo de la anulación.", "error")
        return redirect(url_for("ventas.lista", venta=venta_id))

    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        venta = db.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
        caja = db.execute("SELECT estado FROM cajas WHERE id = ?", (venta["caja_id"],)).fetchone()
        if venta["estado"] != "completada":
            raise _VentaError("Esa venta ya está anulada.")
        # Si ya tuvo una devolución, anularla devolvería esas unidades dos veces
        if db.execute("SELECT 1 FROM devoluciones WHERE venta_id = ?", (venta_id,)).fetchone():
            raise _VentaError("Esa venta tiene una devolución registrada; no se puede anular.")
        if caja["estado"] != "abierta":
            raise _VentaError("Esa venta pertenece a una caja ya cerrada; no se puede anular.")

        lineas = db.execute("SELECT * FROM venta_lineas WHERE venta_id = ?", (venta_id,)).fetchall()
        for linea in lineas:
            for a in json.loads(linea["lotes_json"] or "[]"):
                db.execute(
                    "UPDATE lotes SET cantidad_disponible = cantidad_disponible + ?, "
                    "actualizado_en = ? WHERE id = ?",
                    (a["cantidad"], ahora(), a["lote_id"]),
                )
                db.execute(
                    "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, "
                    "cantidad, referencia, referencia_id, usuario_id, usuario_nombre, "
                    "observaciones, creado_en) VALUES (?,?,?, 'devolucion', ?, ?, ?, ?, ?, ?, ?)",
                    (ahora(), a["lote_id"], linea["producto_id"], a["cantidad"],
                     f"Anulación {venta['consecutivo']}", venta_id, g.user["id"],
                     g.user["nombre"], motivo, ahora()),
                )
        db.execute(
            "UPDATE ventas SET estado = 'anulada', motivo_anulacion = ?, anulada_en = ?, "
            "anulada_por = ?, anulada_por_nombre = ? WHERE id = ?",
            (motivo, ahora(), g.user["id"], g.user["nombre"], venta_id),
        )
        db.commit()
    except _VentaError as e:
        db.rollback()
        flash(str(e), "error")
        return redirect(url_for("ventas.lista", venta=venta_id))
    except Exception:
        db.rollback()
        raise

    registrar("venta_anulada", "ventas", venta_id,
              f"consecutivo={venta['consecutivo']} motivo={motivo}")
    flash(f"Venta {venta['consecutivo']} anulada. El inventario fue devuelto.", "ok")
    return redirect(url_for("ventas.lista", venta=venta_id))
