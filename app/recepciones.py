"""Recepción técnica: ingreso de mercancía, cuarentena, aprobación, PDF."""
import json
import os
from datetime import datetime

from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template,
                   request, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .utiles import obtener_o_404, siguiente_numero   # versión 1.1.15: ayudas comunes (app/utiles.py)
from . import presentaciones as pres

bp = Blueprint("recepciones", __name__, url_prefix="/recepciones")

ESTADOS = {
    "borrador": "Borrador",
    "cuarentena": "En cuarentena",
    "aprobada": "Aprobada",
    "rechazada": "Rechazada",
}
EMPAQUES = {"bueno": "Bueno", "dañado": "Dañado", "roto": "Roto", "otro": "Otro"}
RESULTADOS = {"aceptado": "Aceptado", "cuarentena": "Cuarentena", "rechazado": "Rechazado"}


# ---------- Helpers ----------

def _siguiente_numero():
    return siguiente_numero(get_db(), "recepciones", "REC")


def _obtener(rec_id):
    return obtener_o_404("recepciones", rec_id)


def _lineas_de(rec_id):
    return get_db().execute(
        "SELECT rl.*, "
        "p.codigo AS producto_codigo, p.nombre AS producto_nombre, "
        "p.registro_sanitario AS producto_registro, p.maneja_vencimiento, "
        "p.concentracion, p.cadena_frio, p.control_especial, p.requiere_formula, "
        "p.codigo_barras, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre, "
        "COALESCE((SELECT GROUP_CONCAT(c.nombre, ' + ') FROM (SELECT c2.nombre FROM producto_principios pp2 JOIN catalogos c2 ON c2.id = pp2.catalogo_id WHERE pp2.producto_id = p.id ORDER BY pp2.orden) c), (SELECT nombre FROM catalogos WHERE id = p.principio_id)) AS principio_nombre, "
        "(SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad_nombre "
        "FROM recepcion_lineas rl JOIN productos p ON p.id = rl.producto_id "
        "WHERE rl.recepcion_id = ? ORDER BY rl.id",
        (rec_id,),
    ).fetchall()


def _productos():
    return get_db().execute(
        "SELECT p.id, p.codigo, p.nombre, p.concentracion, p.maneja_vencimiento, "
        "p.cadena_frio, p.control_especial, p.registro_sanitario, p.registro_vence, "
        "p.precio_venta, p.codigo_barras, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre, "
        "(SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad_nombre "
        "FROM productos p WHERE p.activo = 1 ORDER BY p.nombre COLLATE ES"
    ).fetchall()


def _proveedores():
    return get_db().execute(
        "SELECT id, nit, razon_social, plazo_dias FROM proveedores WHERE activo = 1 "
        "ORDER BY razon_social COLLATE ES"
    ).fetchall()


def _unidades():
    # "Unidad" primero y después por tamaño (Sello x 4, Caja x 10, Sello x 10...): app/nombres.py
    from .nombres import orden_unidades
    return orden_unidades(get_db().execute(
        "SELECT id, nombre, cantidad FROM unidades_medida WHERE activo = 1").fetchall())


def _laboratorios():
    return get_db().execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'laboratorio' AND activo = 1 "
        "ORDER BY nombre COLLATE ES"
    ).fetchall()


def _catalogo(tipo):
    return get_db().execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = ? AND activo = 1 ORDER BY nombre COLLATE ES",
        (tipo,)).fetchall()


def _contexto_form(rec=None):
    return {
        "proveedores": _proveedores(),
        "productos": _productos(),
        "unidades": _unidades(),
        "laboratorios": _laboratorios(),
        # Para la ventana "Completar datos" de cada línea (datos técnicos del producto)
        "principios": _catalogo("principio"),
        "formas": _catalogo("forma_farmaceutica"),
        "estados": ESTADOS,
        "empaques": EMPAQUES,
        "resultados": RESULTADOS,
        # Versión 1.1.7: de dónde puede salir la plata si la factura se paga de contado
        "origenes_pago": __import__("app.cuentas_pagar", fromlist=["ORIGENES"]).ORIGENES,
        "numero_sugerido": _siguiente_numero() if not rec else None,
        "recepcion": rec,
        "lineas": _lineas_de(rec["id"]) if rec else [],
    }


def _guardar_foto(archivo, rec_id):
    if not archivo or not archivo.filename:
        return None
    ext = os.path.splitext(archivo.filename)[1].lower()
    # Versión 1.1.8: una foto ".jfif" (o .jpe, .pjpeg, .pjp) es una foto JPG con otro
    # nombre (así las guarda Windows al bajarlas de internet): se guarda como ".jpg".
    from .utils_imagenes import EXT_JPG_OTROS
    if ext in EXT_JPG_OTROS:
        ext = ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".pdf"):
        return None
    from .utils_imagenes import carpeta_uploads
    destino_dir = os.path.join(str(carpeta_uploads()), "recepciones")
    os.makedirs(destino_dir, exist_ok=True)
    ruta = os.path.join(destino_dir, f"{rec_id}{ext}")
    archivo.save(ruta)
    return f"uploads/recepciones/{rec_id}{ext}"


def _lineas_previas_formulario(form=None):
    """Lee las líneas del formulario tal cual (sin validar) para repintarlas al fallar.

    form: de dónde se leen. Por defecto, lo que llegó del navegador (request.form).
    Versión 1.1.8: también puede ser una recepción EN ESPERA (lo guardado otro día).
    """
    form = request.form if form is None else form
    prod_ids = form.getlist("linea_producto_id")
    lotes = form.getlist("linea_lote")
    vencimientos = form.getlist("linea_vencimiento")
    cant_rec = form.getlist("linea_cantidad_recibida")
    costos = form.getlist("linea_costo")
    temps_ing = form.getlist("linea_temperatura_ingreso")
    empaques = form.getlist("linea_empaque")
    resultados = form.getlist("linea_resultado")
    motivos = form.getlist("linea_motivo")
    presentaciones = form.getlist("linea_presentacion")
    factores_otros = form.getlist("linea_factor_otro")
    ivas = form.getlist("linea_iva")            # IVA % de cada línea (versión 1.1.6)

    db = get_db()
    lineas = []
    for i, pid in enumerate(prod_ids):
        if not pid or not pid.isdigit():
            continue
        p = db.execute(
            "SELECT codigo, nombre, concentracion, registro_sanitario, registro_vence, "
            "maneja_vencimiento, cadena_frio, control_especial "
            "FROM productos WHERE id = ?", (int(pid),)
        ).fetchone()
        if p is None:
            continue

        def v(lista, idx):
            return lista[idx] if idx < len(lista) else ""

        lineas.append({
            "producto_id": int(pid),
            "producto_codigo": p["codigo"],
            "producto_nombre": p["nombre"],
            "concentracion": p["concentracion"] or "",
            "registro_sanitario": p["registro_sanitario"] or "",
            "registro_vence": p["registro_vence"] or "",
            "maneja_vencimiento": p["maneja_vencimiento"],
            "cadena_frio": p["cadena_frio"],
            "control_especial": p["control_especial"],
            "lote": v(lotes, i),
            "vencimiento": v(vencimientos, i),
            "cantidad_recibida": v(cant_rec, i) or "0",
            "costo_unitario": v(costos, i) or "0",
            "iva_tarifa": v(ivas, i) or "0",
            "temperatura_ingreso": v(temps_ing, i),
            "estado_empaque": v(empaques, i) or "bueno",
            "resultado": v(resultados, i) or "aceptado",
            "motivo_rechazo": v(motivos, i),
            # "otra" = una caja que no está en la ficha, con su "cuántas trae" escrito
            # "u12" = una unidad de medida cualquiera (CAJA X 12) que no está en la ficha
            "presentacion_id": (int(v(presentaciones, i)) if v(presentaciones, i).isdigit()
                                else v(presentaciones, i) if (v(presentaciones, i) == "otra"
                                                              or v(presentaciones, i).startswith("u")) else 0),
            "factor_otro": v(factores_otros, i),
            "presentaciones": _presentaciones_simples(int(pid)),
        })
    return lineas


def _presentacion_por_unidad(producto_id, unidad_id):
    """"Viene en" una unidad de medida cualquiera (ej. CAJA X 12).

    Si el producto ya la tiene como presentación, se usa ese "cuántas trae".
    Si no: cantidad de la unidad ÷ cantidad de la unidad del inventario
    (CAJA X 12 sobre Unidad -> 12). Devuelve {nombre, factor} o None.
    """
    db = get_db()
    u = db.execute("SELECT id, nombre, cantidad FROM unidades_medida WHERE id = ?", (unidad_id,)).fetchone()
    if u is None:
        return None
    propia = db.execute("SELECT factor FROM producto_presentaciones WHERE producto_id = ? AND unidad_id = ?",
                        (producto_id, unidad_id)).fetchone()
    if propia:
        return {"nombre": u["nombre"], "factor": float(propia["factor"])}
    base = db.execute("SELECT um.id, um.nombre, um.cantidad FROM productos p JOIN unidades_medida um "
                      "ON um.id = p.unidad_venta_id WHERE p.id = ?", (producto_id,)).fetchone()
    if base and base["id"] == unidad_id:
        return {"nombre": u["nombre"], "factor": 1.0}
    cant_base = pres.cantidad_efectiva(base["nombre"], base["cantidad"]) if base else 1.0
    return {"nombre": u["nombre"], "factor": round(pres.cantidad_efectiva(u["nombre"], u["cantidad"]) / cant_base, 4)}


def _leer_lineas_formulario():
    """Lee y valida las líneas."""
    prod_ids = request.form.getlist("linea_producto_id")
    lotes = request.form.getlist("linea_lote")
    vencimientos = request.form.getlist("linea_vencimiento")
    cant_rec = request.form.getlist("linea_cantidad_recibida")
    costos = request.form.getlist("linea_costo")
    temps_ing = request.form.getlist("linea_temperatura_ingreso")
    empaques = request.form.getlist("linea_empaque")
    resultados = request.form.getlist("linea_resultado")
    motivos = request.form.getlist("linea_motivo")
    obs_lineas = request.form.getlist("linea_observaciones")
    # "Viene en": id de la presentación (0 = unidad de inventario, otro = sobre, caja...)
    presentaciones = request.form.getlist("linea_presentacion")
    # Si escogieron "Otra caja…": cuántas unidades trae esa caja (ej. 300)
    factores_otros = request.form.getlist("linea_factor_otro")
    # ---- IVA (versión 1.1.6) ----
    # linea_iva = % de IVA de cada línea (0, 5, 19...). precios_con_iva = la factura
    # ya trae el IVA dentro del costo. declara_iva (Configuración) decide qué costo
    # se usa para la utilidad: con IVA (no declara) o sin IVA (sí declara).
    ivas = request.form.getlist("linea_iva")
    precios_con_iva = bool(request.form.get("precios_con_iva"))
    from .configuracion import obtener_config
    declara_iva = obtener_config().get("declara_iva") == "si"

    lineas, errores = [], []
    for i, pid in enumerate(prod_ids):
        if not pid or not pid.isdigit():
            continue

        def v(lista, idx):
            return lista[idx] if idx < len(lista) else ""

        try:
            cr = float(v(cant_rec, i).replace(",", ".") or 0)
        except ValueError:
            cr = 0
        try:
            co = float(v(costos, i).replace(",", ".") or 0)
        except ValueError:
            co = 0

        try:
            t_ing = float(v(temps_ing, i).replace(",", ".")) if v(temps_ing, i) else None
        except ValueError:
            t_ing = None

        # ---- VALIDACIONES (reglas del proyecto) ----
        # Buscamos el producto para saber su nombre y si maneja vencimiento.
        prod = get_db().execute(
            "SELECT nombre, maneja_vencimiento FROM productos WHERE id = ?", (int(pid),)
        ).fetchone()
        nombre = prod["nombre"] if prod else f"producto {pid}"
        lote_txt = v(lotes, i).strip()
        venc_txt = v(vencimientos, i).strip()

        if prod is None:
            errores.append(f"El producto {pid} no existe.")
        if cr <= 0:
            errores.append(f"{nombre}: la cantidad recibida debe ser mayor a cero.")
        if co <= 0:
            errores.append(f"{nombre}: el costo unitario debe ser mayor a cero.")
        # Si el producto maneja vencimiento, lote y fecha son obligatorios.
        if prod and prod["maneja_vencimiento"] and (not lote_txt or not venc_txt):
            errores.append(f"{nombre}: debes indicar el lote y la fecha de vencimiento.")
        # La fecha debe tener formato AAAA-MM-DD (así la entrega el calendario del formulario).
        if venc_txt:
            try:
                datetime.strptime(venc_txt, "%Y-%m-%d")
            except ValueError:
                errores.append(f"{nombre}: la fecha de vencimiento no es válida.")

        # ---- PRESENTACIÓN EN QUE LLEGÓ (ej: 3 Caja x 100 a $25.000 c/u) ----
        # Se guarda TODO en unidades de inventario: 3 cajas x 100 = 300 tabletas
        # y el costo por tableta = $25.000 / 100 = $250. Así el resto del
        # programa (lotes, kardex, utilidades) sigue igual.
        pres_txt = v(presentaciones, i)
        # La UdM ("Viene en") es obligatoria (versión 1.1.3). La pantalla siempre
        # manda este campo; si no llegó ninguno (formularios viejos), se usa la unidad.
        if presentaciones and pres_txt in ("", "nueva"):
            errores.append(f"{nombre}: escoge en qué unidad llegó (UdM).")
        if pres_txt == "otra":
            # Caja que no está en la ficha (hoy llegó x 300, otro día x 100)
            try:
                factor_otro = float(v(factores_otros, i).replace(",", ".") or 0)
            except ValueError:
                factor_otro = 0
            if factor_otro <= 1:
                errores.append(f"{nombre}: escribe cuántas unidades trae la caja (más de 1).")
                factor_otro = 1
            presentacion = {"nombre": f"Caja x {factor_otro:g}", "factor": factor_otro}
        elif pres_txt.startswith("u") and pres_txt[1:].isdigit():
            # Cualquier unidad de medida (ej. "CAJA X 12"), aunque no esté en la ficha:
            # así lo pidió Fernando. Cuántas trae sale de la unidad.
            presentacion = _presentacion_por_unidad(int(pid), int(pres_txt[1:]))
            if presentacion is None:
                errores.append(f"{nombre}: esa unidad no existe.")
            elif presentacion["factor"] < 1:
                errores.append(f"{nombre}: la unidad {presentacion['nombre']} es más pequeña que la del inventario.")
        else:
            presentacion = pres.presentacion_para_vender(int(pid), int(pres_txt)) if pres_txt.isdigit() else None
        if presentacion is None:
            presentacion = {"nombre": None, "factor": 1}
        factor = float(presentacion["factor"] or 1)

        # IVA de la línea y los dos costos (por unidad de inventario)
        try:
            iva = float(v(ivas, i).replace(",", ".") or 0)
        except ValueError:
            iva = 0.0
        if not 0 <= iva <= 100:
            errores.append(f"{nombre}: el IVA debe estar entre 0 y 100 %.")
            iva = 0.0
        tasa = iva / 100
        costo_sin = co / (1 + tasa) if precios_con_iva else co      # por la unidad en que llegó (caja)
        costo_con = costo_sin * (1 + tasa)

        lineas.append({
            "producto_id": int(pid),
            "iva_tarifa": iva,
            "costo_sin_iva": costo_sin / factor,
            "costo_con_iva": costo_con / factor,
            "lote": v(lotes, i).strip() or None,
            "vencimiento": v(vencimientos, i).strip() or None,
            "cantidad_facturada": round(cr * factor, 4),
            "cantidad_recibida": round(cr * factor, 4),
            # Costo para la UTILIDAD: con IVA si no declara IVA; sin IVA si lo declara
            "costo_unitario": (costo_sin if declara_iva else costo_con) / factor,
            "presentacion": presentacion["nombre"] if factor != 1 else None,
            "factor": factor,
            "temperatura_ingreso": t_ing,
            "estado_empaque": v(empaques, i) or "bueno",
            "resultado": v(resultados, i) or "aceptado",
            "motivo_rechazo": v(motivos, i).strip() or None,
            "observaciones": v(obs_lineas, i).strip() or None,
        })
    return lineas, errores


# ---------- Lista ----------

@bp.route("/")
@login_required
def lista():
    q = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "")
    sql = (
        "SELECT r.*, p.razon_social AS proveedor_nombre "
        "FROM recepciones r JOIN proveedores p ON p.id = r.proveedor_id"
    )
    cond, params = [], []
    if filtro and filtro in ESTADOS:
        cond.append("r.estado = ?")
        params.append(filtro)
    if q:
        cond.append("(r.numero LIKE ? OR r.factura_numero LIKE ? OR p.razon_social LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY r.id DESC LIMIT 200"
    filas = get_db().execute(sql, params).fetchall()
    # Versión 1.1.8: las recepciones EN ESPERA (a medias) van arriba, con "Continuar"
    en_espera = get_db().execute(
        "SELECT e.*, p.razon_social AS proveedor_nombre FROM recepciones_espera e "
        "LEFT JOIN proveedores p ON p.id = e.proveedor_id "
        "ORDER BY COALESCE(e.actualizado_en, e.creado_en) DESC").fetchall()
    return render_template("recepciones/lista.html", filas=filas, q=q, filtro=filtro,
                           estados=ESTADOS, en_espera=en_espera)


# ---------- Nueva ----------

@bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    if request.method == "POST":
        # Versión 1.1.8: si esta recepción venía "en espera", aquí llega su número
        # (campo oculto espera_id). Al guardarla de verdad, la espera se borra.
        espera_id = request.form.get("espera_id", "").strip()
        espera_id = int(espera_id) if espera_id.isdigit() else None
        # Botón "Guardar en espera": guarda lo escrito hasta ahora SIN revisar nada
        # y SIN tocar el inventario. Se sigue después con "Continuar".
        if request.form.get("accion") == "espera":
            return _guardar_en_espera(espera_id)
        # Versión 1.1.9: si esta pantalla ya confirmó su recepción (doble clic, o
        # volver atrás y darle otra vez), no se crea una segunda recepción igual.
        token = _token_de(request.form)
        ya = _ya_confirmada(token)
        if ya:
            flash(f"Esa recepción ya estaba confirmada: {ya['numero']}.", "ok")
            return redirect(url_for("recepciones.ver", rec_id=ya["id"]))

        proveedor_id = request.form.get("proveedor_id", "").strip()
        factura = request.form.get("factura_numero", "").strip() or None
        remision = request.form.get("remision_numero", "").strip() or None
        temperatura = request.form.get("temperatura_llegada", "").strip()
        observaciones = request.form.get("observaciones", "").strip() or None
        numero = request.form.get("numero", "").strip() or _siguiente_numero()

        lineas, errores = _leer_lineas_formulario()
        error_cabecera = None

        # Pago de la factura (versión 1.1.7): a crédito (con vencimiento) o de contado
        pago_modo = request.form.get("pago_modo", "credito")
        pago_vence = request.form.get("pago_vence", "").strip()
        pago_origen = request.form.get("pago_origen", "").strip()
        from .cuentas_pagar import ORIGENES as ORIGENES_PAGO, registrar_pago, total_de_lineas
        caja_abierta = get_db().execute("SELECT 1 FROM cajas WHERE estado = 'abierta'").fetchone()

        if not factura and not remision:
            error_cabecera = "Debes indicar el número de factura o el número de remisión."
        elif not lineas:
            error_cabecera = "Debes agregar al menos una línea."
        elif errores:
            # Todos los errores de una vez (versión 1.1.3). Antes solo salía el primero:
            # se corregía y al guardar aparecía el siguiente.
            error_cabecera = errores[0] if len(errores) == 1 else errores
        elif pago_modo == "contado" and pago_origen not in ORIGENES_PAGO:
            error_cabecera = "La factura es de contado: escoge de dónde salió la plata."
        elif pago_modo == "contado" and pago_origen == "caja_pos" and not caja_abierta:
            error_cabecera = "No hay caja del POS abierta: escoge otro lugar de donde salió la plata."

        if not error_cabecera:
            db = get_db()
            try:
                temp_llegada = None
                if temperatura:
                    try:
                        temp_llegada = float(temperatura.replace(",", "."))
                    except ValueError:
                        pass

                cur = db.execute(
                    "INSERT INTO recepciones (numero, fecha, proveedor_id, factura_numero, "
                    "remision_numero, temperatura_llegada, estado, recibido_por, "
                    "recibido_por_nombre, observaciones, creado_en, precios_con_iva) "
                    "VALUES (?,?,?,?,?,?, 'cuarentena', ?, ?, ?, ?, ?)",
                    (numero, ahora(), int(proveedor_id), factura, remision, temp_llegada,
                     g.user["id"], g.user["nombre"], observaciones, ahora(),
                     1 if request.form.get("precios_con_iva") else 0),
                )
                rec_id = cur.lastrowid

                for l in lineas:
                    db.execute(
                        "INSERT INTO recepcion_lineas (recepcion_id, producto_id, lote, vencimiento, "
                        "cantidad_facturada, cantidad_recibida, costo_unitario, estado_empaque, "
                        "resultado, motivo_rechazo, observaciones, temperatura_ingreso, presentacion, factor, "
                        "iva_tarifa, costo_sin_iva, costo_con_iva) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rec_id, l["producto_id"], l["lote"], l["vencimiento"],
                         l["cantidad_facturada"], l["cantidad_recibida"], l["costo_unitario"],
                         l["estado_empaque"], l["resultado"], l["motivo_rechazo"],
                         l["observaciones"], l["temperatura_ingreso"], l["presentacion"], l["factor"],
                         l["iva_tarifa"], l["costo_sin_iva"], l["costo_con_iva"]),
                    )

                # ---- Pago de la factura (versión 1.1.7) ----
                total_pagar = total_de_lineas(lineas)
                if total_pagar <= 0:
                    estado_pago, vence = "no_aplica", None
                elif pago_modo == "contado":
                    estado_pago, vence = "pagada", None
                else:
                    # Sin fecha escrita: hoy + el plazo del proveedor (30 días si no tiene)
                    if not pago_vence:
                        from .cuentas_pagar import vence_sugerido
                        plazo = db.execute("SELECT plazo_dias FROM proveedores WHERE id = ?",
                                           (int(proveedor_id),)).fetchone()
                        pago_vence = vence_sugerido(ahora(), (plazo["plazo_dias"] if plazo else 0) or 30)
                    estado_pago, vence = "pendiente", pago_vence
                db.execute("UPDATE recepciones SET total_pagar = ?, pago_estado = ?, pago_vence = ?, "
                           "borrador_token = ? WHERE id = ?", (total_pagar, estado_pago, vence, token, rec_id))
                if estado_pago == "pagada":
                    rec_fila = db.execute("SELECT * FROM recepciones WHERE id = ?", (rec_id,)).fetchone()
                    _, error_pago = registrar_pago(db, rec_fila, total_pagar, ahora(), pago_origen,
                                                   "Pagada de contado al recibir")
                    if error_pago:
                        raise ValueError(error_pago)
                # Versión 1.1.8: la recepción venía "en espera": ya quedó guardada de
                # verdad, así que la espera se borra (en el mismo commit: o todo o nada).
                # (1.1.9: también la que guardó el guardado automático, por su clave)
                db.execute("DELETE FROM recepciones_espera WHERE id = ? OR (token IS NOT NULL AND token = ?)",
                           (espera_id or 0, token or ""))
                db.commit()

                archivo = request.files.get("foto")
                if archivo and archivo.filename:
                    ruta = _guardar_foto(archivo, rec_id)
                    if ruta:
                        db.execute("UPDATE recepciones SET foto_ruta = ? WHERE id = ?", (ruta, rec_id))
                        db.commit()

                registrar("recepcion_creada", "recepciones", rec_id,
                          f"numero={numero} proveedor={proveedor_id}"
                          + (f" (venía en espera #{espera_id})" if espera_id else ""))
                flash(f"Recepción {numero} CONFIRMADA. Quedó en cuarentena, pendiente de aprobación.", "ok")
                return redirect(url_for("recepciones.ver", rec_id=rec_id))
            except Exception as e:
                db.rollback()          # que no quede nada a medias (ni la recepción ni el pago)
                error_cabecera = f"Error al guardar: {e}"

        valores_previos = {
            "numero": numero,
            "proveedor_id": proveedor_id,
            "factura_numero": factura or "",
            "remision_numero": remision or "",
            "temperatura_llegada": temperatura,
            "observaciones": observaciones or "",
            "precios_con_iva": bool(request.form.get("precios_con_iva")),
            "pago_modo": pago_modo, "pago_vence": pago_vence, "pago_origen": pago_origen,
        }
        return render_template(
            "recepciones/form.html",
            **_contexto_form(),
            error_cabecera=error_cabecera,
            valores_previos=valores_previos,
            lineas_previas=_lineas_previas_formulario(),
            espera=_espera_o_none(espera_id),
            borrador_token=token or _token_nuevo(),
        )

    # ---- Versión 1.1.8: CONTINUAR una recepción que quedó en espera ----
    # /recepciones/nueva?espera=3 abre el formulario con todo lo que se había escrito.
    espera_txt = request.args.get("espera", "")
    if espera_txt.isdigit():
        fila = _espera_o_none(int(espera_txt))
        if fila is None:
            flash("Esa recepción en espera ya no existe (quizá ya se terminó o se descartó).", "error")
            return redirect(url_for("recepciones.lista"))
        form = _form_de_espera(fila)
        # Las abiertas de la versión 1.1.8 no tenían clave: se les pone una
        token = fila["token"]
        if not token:
            token = _token_nuevo()
            get_db().execute("UPDATE recepciones_espera SET token = ? WHERE id = ?", (token, fila["id"]))
            get_db().commit()
        return render_template(
            "recepciones/form.html",
            **_contexto_form(),
            valores_previos=_valores_previos(form),
            lineas_previas=_lineas_previas_formulario(form),
            espera=fila,
            borrador_token=token,
        )
    return render_template("recepciones/form.html", **_contexto_form(), borrador_token=_token_nuevo())


def _token_nuevo():
    """Clave al azar para una pantalla de recepción nueva (ej. '9f2c41d07ab35e10')."""
    import secrets
    return secrets.token_hex(8)


# ---------- Versión 1.1.8: RECEPCIONES EN ESPERA (desde la 1.1.9: «ABIERTAS») ----------
# Desde la 1.1.9 funciona como el conteo de inventario: la recepción queda ABIERTA
# y se GUARDA SOLA mientras se recibe (api_borrador, más abajo). En la lista sale
# «Continuar recibiendo» y solo se cierra al darle «Confirmar recepción».
# Cómo funciona (para aprender):
#   1. En el formulario, el botón "Guardar en espera" manda TODO lo escrito.
#   2. _guardar_en_espera() lo convierte en texto JSON y lo guarda en la tabla
#      recepciones_espera (no en "recepciones": todavía no es una recepción).
#      No se revisa nada (puede haber líneas a medias) y no se toca el inventario.
#   3. En Recepciones aparece la lista "En espera" con el botón "Continuar".
#   4. Continuar abre /recepciones/nueva?espera=ID: _form_de_espera() vuelve a
#      armar el formulario con lo guardado y la pantalla lo pinta igualito.
#   5. Al darle "Guardar recepción" se crea la recepción normal (cuarentena,
#      Acta, pago...) y la espera se borra.

def _espera_o_none(espera_id):
    """La fila de recepciones_espera con ese id (o None si no hay)."""
    if not espera_id:
        return None
    return get_db().execute(
        "SELECT e.*, p.razon_social AS proveedor_nombre FROM recepciones_espera e "
        "LEFT JOIN proveedores p ON p.id = e.proveedor_id WHERE e.id = ?", (espera_id,)).fetchone()


def _form_de_espera(fila):
    """Vuelve a armar el formulario (con varias líneas) a partir del JSON guardado.

    Se guarda así: {"linea_lote": ["L1", "L2"], "proveedor_id": ["3"], ...}
    (cada campo con la lista de sus valores, porque las líneas repiten el nombre).
    MultiDict es el mismo tipo de objeto que request.form: así el resto del
    código lo lee igual que si acabara de llegar del navegador.
    """
    from werkzeug.datastructures import MultiDict
    try:
        datos = json.loads(fila["datos"] or "{}")
    except ValueError:
        datos = {}
    return MultiDict([(campo, valor) for campo, valores in datos.items() for valor in valores])


def _valores_previos(form):
    """Los datos generales (proveedor, factura, pago...) para volver a pintarlos."""
    numero = (form.get("numero") or "").strip()
    # Mientras estuvo en espera pudieron guardarse otras recepciones: si su número
    # ya lo tiene otra, se le pone el siguiente libre.
    if not numero or get_db().execute("SELECT 1 FROM recepciones WHERE numero = ?", (numero,)).fetchone():
        numero = _siguiente_numero()
    return {
        "numero": numero,
        "proveedor_id": (form.get("proveedor_id") or "").strip(),
        "factura_numero": (form.get("factura_numero") or "").strip(),
        "remision_numero": (form.get("remision_numero") or "").strip(),
        "temperatura_llegada": (form.get("temperatura_llegada") or "").strip(),
        "observaciones": (form.get("observaciones") or "").strip(),
        "precios_con_iva": bool(form.get("precios_con_iva")),
        "pago_modo": form.get("pago_modo", "credito"),
        "pago_vence": (form.get("pago_vence") or "").strip(),
        "pago_origen": (form.get("pago_origen") or "").strip(),
    }


def _token_de(form):
    """La clave al azar de la pantalla de recepción (versión 1.1.9, ver migración 40)."""
    return (form.get("borrador_token") or "").strip()[:40] or None


def _ya_confirmada(token):
    """La recepción que ya se confirmó desde esta misma pantalla (o None)."""
    if not token:
        return None
    return get_db().execute("SELECT id, numero FROM recepciones WHERE borrador_token = ?", (token,)).fetchone()


def _guardar_borrador(form, espera_id, token):
    """Guarda lo escrito como recepción ABIERTA (sin confirmar). No hace commit.

    Versión 1.1.9: lo usan el botón «Guardar y seguir después» y el guardado
    AUTOMÁTICO que hace la pantalla mientras se va recibiendo.
    Devuelve (id de la recepción abierta, número de líneas), o (None, 0) si no
    hay nada escrito todavía (ni proveedor, ni factura, ni productos).
    """
    # Todos los campos con todos sus valores (las líneas repiten nombre), menos los
    # de control: la clave de seguridad (_csrf), el botón y el número de la espera.
    datos = {campo: form.getlist(campo) for campo in form.keys()
             if campo not in ("_csrf", "accion", "espera_id")}
    total_lineas = sum(1 for pid in form.getlist("linea_producto_id") if pid.strip().isdigit())
    proveedor = (form.get("proveedor_id") or "").strip()
    proveedor = int(proveedor) if proveedor.isdigit() else None
    factura = ((form.get("factura_numero") or "").strip()
               or (form.get("remision_numero") or "").strip() or None)
    if not total_lineas and not proveedor and not factura:
        return None, 0

    db = get_db()
    texto = json.dumps(datos, ensure_ascii=False)
    # ¿Ya existe esta recepción abierta? Por su número, o por la clave de la pantalla
    # (si el primer guardado automático todavía no le había avisado el número).
    fila = _espera_o_none(espera_id) if espera_id else None
    if fila is None and token:
        fila = db.execute("SELECT * FROM recepciones_espera WHERE token = ?", (token,)).fetchone()
    if fila is not None:
        db.execute("UPDATE recepciones_espera SET proveedor_id = ?, factura_numero = ?, total_lineas = ?, "
                   "datos = ?, token = COALESCE(token, ?), actualizado_por_nombre = ?, actualizado_en = ? "
                   "WHERE id = ?",
                   (proveedor, factura, total_lineas, texto, token, g.user["nombre"], ahora(), fila["id"]))
        return fila["id"], total_lineas
    cur = db.execute("INSERT INTO recepciones_espera (proveedor_id, factura_numero, total_lineas, datos, "
                     "token, creado_por, creado_por_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?)",
                     (proveedor, factura, total_lineas, texto, token, g.user["id"], g.user["nombre"], ahora()))
    return cur.lastrowid, total_lineas


def _guardar_en_espera(espera_id):
    """Botón «Guardar y seguir después»: guarda la recepción ABIERTA y vuelve a la lista."""
    token = _token_de(request.form)
    ya = _ya_confirmada(token)
    if ya:
        flash(f"Esta recepción ya se había confirmado ({ya['numero']}).", "ok")
        return redirect(url_for("recepciones.ver", rec_id=ya["id"]))
    espera_id, total_lineas = _guardar_borrador(request.form, espera_id, token)
    if espera_id is None:
        flash("No hay nada escrito para guardar.", "error")
        return redirect(url_for("recepciones.nueva"))
    get_db().commit()
    registrar("recepcion_en_espera", "recepciones_espera", espera_id, f"lineas={total_lineas}")

    flash(f"Recepción ABIERTA guardada con {total_lineas} línea(s). Todavía no entró nada al "
          f"inventario. Para seguir, dale «Continuar recibiendo» en la lista de abajo.", "ok")
    archivo = request.files.get("foto")
    if archivo and archivo.filename:
        flash("La foto del empaque/factura no se guarda mientras la recepción está abierta: "
              "adjúntala al confirmar.", "error")
    return redirect(url_for("recepciones.lista"))


@bp.route("/api/borrador", methods=["POST"])
@login_required
def api_borrador():
    """GUARDADO AUTOMÁTICO (versión 1.1.9), como el conteo de inventario.

    La pantalla de recepción llama aquí sola, unos segundos después de cada cambio
    (y al salir de la página). Así nada se pierde aunque se cierre la ventana o se
    vaya la luz: queda como recepción ABIERTA hasta que se le dé «Confirmar recepción».
    Devuelve el número de la recepción abierta para que la pantalla lo recuerde.
    """
    form = request.form
    token = _token_de(form)
    if _ya_confirmada(token):
        # Llegó tarde: la recepción ya se confirmó. No se crea otra abierta.
        return jsonify({"ok": False, "confirmada": True})
    espera_txt = (form.get("espera_id") or "").strip()
    espera_id, total_lineas = _guardar_borrador(form, int(espera_txt) if espera_txt.isdigit() else None, token)
    if espera_id is None:
        return jsonify({"ok": True, "vacia": True})
    get_db().commit()
    # Justo en ese instante se pudo haber confirmado (dos pedidos al tiempo): si ya
    # está confirmada, la abierta que se acaba de guardar sobra y se borra.
    if _ya_confirmada(token):
        get_db().execute("DELETE FROM recepciones_espera WHERE id = ?", (espera_id,))
        get_db().commit()
        return jsonify({"ok": False, "confirmada": True})
    return jsonify({"ok": True, "espera_id": espera_id, "lineas": total_lineas, "hora": ahora()[11:16]})


@bp.route("/espera/<int:espera_id>/descartar", methods=["POST"])
@login_required
def descartar_espera(espera_id):
    """Borra una recepción en espera (por ejemplo, si se metió por error)."""
    fila = _espera_o_none(espera_id)
    if fila is None:
        abort(404)
    db = get_db()
    db.execute("DELETE FROM recepciones_espera WHERE id = ?", (espera_id,))
    db.commit()
    registrar("recepcion_espera_descartada", "recepciones_espera", espera_id,
              f"factura={fila['factura_numero'] or '—'} lineas={fila['total_lineas']}")
    flash("Recepción en espera descartada.", "ok")
    return redirect(url_for("recepciones.lista"))


# ---------- Ver detalle ----------

@bp.route("/<int:rec_id>")
@login_required
def ver(rec_id):
    rec = _obtener(rec_id)
    lineas = _lineas_de(rec_id)
    proveedor = get_db().execute(
        "SELECT * FROM proveedores WHERE id = ?", (rec["proveedor_id"],)
    ).fetchone()
    # Versión 1.1.7: el pago de esta factura (si ya se pagó)
    from .cuentas_pagar import ORIGENES
    pago = get_db().execute("SELECT * FROM pagos_proveedores WHERE recepcion_id = ? AND anulado = 0 "
                            "ORDER BY id DESC LIMIT 1", (rec_id,)).fetchone()
    return render_template("recepciones/ver.html",
                           rec=rec, lineas=lineas, proveedor=proveedor, pago=pago, origenes_pago=ORIGENES,
                           estados=ESTADOS, empaques=EMPAQUES, resultados=RESULTADOS)


# ---------- Aprobar ----------

@bp.route("/<int:rec_id>/aprobar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def aprobar(rec_id):
    rec = _obtener(rec_id)
    if rec["estado"] not in ("cuarentena", "borrador"):
        flash("Esta recepción ya fue procesada.", "error")
        return redirect(url_for("recepciones.ver", rec_id=rec_id))

    db = get_db()
    lineas = _lineas_de(rec_id)
    for l in lineas:
        # Según el resultado de la línea, el lote nace en un estado distinto:
        #   rechazado  -> no entra stock
        #   cuarentena -> el lote existe pero NO se puede vender hasta que se libere
        #   aceptado   -> disponible para vender
        if l["resultado"] == "rechazado":
            estado = "rechazado"
            cantidad = 0
        elif l["resultado"] == "cuarentena":
            estado = "cuarentena"
            cantidad = l["cantidad_recibida"]
        else:
            estado = "disponible"
            cantidad = l["cantidad_recibida"]

        cur = db.execute(
            "INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, "
            "cantidad_disponible, costo_unitario, estado, recepcion_id, recepcion_linea_id, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (l["producto_id"], l["lote"], l["vencimiento"], l["cantidad_recibida"],
             cantidad, l["costo_unitario"], estado, rec_id, l["id"], ahora()),
        )
        lote_id = cur.lastrowid

        # El kardex solo registra entradas de stock vendible (lotes disponibles).
        if estado == "disponible" and cantidad > 0:
            db.execute(
                "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, "
                "referencia, referencia_id, usuario_id, usuario_nombre, creado_en) "
                "VALUES (?,?,?, 'recepcion', ?, ?, ?, ?, ?, ?)",
                (ahora(), lote_id, l["producto_id"], cantidad, f"Recepción {rec['numero']}",
                 rec_id, g.user["id"], g.user["nombre"], ahora()),
            )

    db.execute(
        "UPDATE recepciones SET estado = 'aprobada', aprobado_por = ?, aprobado_por_nombre = ?, "
        "aprobado_en = ?, actualizado_en = ? WHERE id = ?",
        (g.user["id"], g.user["nombre"], ahora(), ahora(), rec_id),
    )
    db.commit()

    registrar("recepcion_aprobada", "recepciones", rec_id,
              f"numero={rec['numero']} lotes={len(lineas)}")
    flash(f"Recepción {rec['numero']} aprobada. {len(lineas)} lote(s) creados.", "ok")
    return redirect(url_for("recepciones.ver", rec_id=rec_id))


# ---------- Rechazar ----------

@bp.route("/<int:rec_id>/rechazar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def rechazar(rec_id):
    rec = _obtener(rec_id)
    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        flash("Debes indicar el motivo del rechazo.", "error")
        return redirect(url_for("recepciones.ver", rec_id=rec_id))

    db = get_db()
    db.execute(
        "UPDATE recepciones SET estado = 'rechazada', aprobado_por = ?, aprobado_por_nombre = ?, "
        "aprobado_en = ?, observaciones = COALESCE(observaciones, '') || ' | RECHAZO: ' || ?, "
        "actualizado_en = ? WHERE id = ?",
        (g.user["id"], g.user["nombre"], ahora(), motivo, ahora(), rec_id),
    )
    # Versión 1.1.7: una recepción rechazada no se paga (si ya se había pagado, queda como estaba)
    db.execute("UPDATE recepciones SET pago_estado = 'no_aplica' WHERE id = ? "
               "AND pago_estado IN ('pendiente', 'por_revisar')", (rec_id,))
    db.commit()
    registrar("recepcion_rechazada", "recepciones", rec_id,
              f"numero={rec['numero']} motivo={motivo}")
    flash(f"Recepción {rec['numero']} rechazada.", "ok")
    return redirect(url_for("recepciones.ver", rec_id=rec_id))



def _presentaciones_simples(producto_id):
    """[{id, nombre, factor, defecto, cuenta}] para el selector "Viene en" de cada línea.

    - defecto = True en la forma en que el producto se VENDE normalmente (ej.
      Sello x 10): la recepción muestra la conversión en esa unidad
      ("1 Caja x 150 = 15 Sello x 10").
    - cuenta (solo en la primera, la unidad de inventario) = cuántas unidades
      mínimas trae esa unidad. Casi siempre 1 (Tableta, Unidad), pero si el
      inventario se cuenta en SELLO X 10 es 10: así una CAJA X 150 son 15 sellos.
    """
    opciones = pres.presentaciones_de([producto_id]).get(producto_id, [])
    fila = get_db().execute(
        "SELECT p.venta_defecto_unidad_id, um.nombre, um.cantidad FROM productos p "
        "LEFT JOIN unidades_medida um ON um.id = p.unidad_venta_id WHERE p.id = ?", (producto_id,)).fetchone()
    defecto = pres.id_por_defecto(opciones, fila["venta_defecto_unidad_id"]) if fila else pres.PRINCIPAL
    cuenta = pres.cantidad_efectiva(fila["nombre"], fila["cantidad"]) if fila and fila["nombre"] else 1.0
    return [{"id": o["id"], "nombre": o["nombre"], "factor": o["factor"], "defecto": o["id"] == defecto,
             "cuenta": cuenta if o["id"] == pres.PRINCIPAL else None} for o in opciones]

# ============================================================
# Las demás partes de la recepción (versión 1.1.15): se importan al final para que sus
# rutas queden en este mismo blueprint (bp). Ver recepciones_productos.py y recepciones_acta.py.
# ============================================================
from . import recepciones_acta, recepciones_productos  # noqa: E402,F401
