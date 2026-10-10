"""Importación de productos desde Excel (.xlsx) o CSV."""
import csv
import io
import sqlite3
from datetime import datetime

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   send_file, url_for)
from openpyxl import Workbook, load_workbook

from .audit import registrar
from .auth import roles_required
from .db import ahora, get_db

bp = Blueprint("importador", __name__, url_prefix="/productos/importar")

# ===== Columnas esperadas =====
# Orden exacto de columnas en la plantilla / archivo.
COLUMNAS = [
    ("codigo", "Código interno *", "P00001"),
    ("codigo_barras", "Código de barras", "7701234567890"),
    ("nombre", "Nombre *", "Acetaminofén 500 mg"),
    ("descripcion", "Descripción", "Tabletas"),
    ("grupo", "Grupo", "Acetaminofén 500 mg"),
    ("concentracion", "Concentración", "500 mg"),
    ("principio", "Principio activo", "Acetaminofén"),
    ("laboratorio", "Laboratorio", "Genfar"),
    ("forma_farmaceutica", "Forma farmacéutica", "Tableta"),
    ("registro_sanitario", "Registro INVIMA", "INVIMA-2024M-12345"),
    ("registro_vence", "Vence INVIMA (AAAA-MM-DD)", "2027-12-31"),
    # ---- CÓMO SE VENDE (igual que la ficha del producto) ----
    # Primero la UNIDAD DE VENTA (lo que vende el POS al tocar el producto:
    # Sello x 10, Frasco, Unidad) y su precio. Después si se vende suelto.
    # Por dentro el inventario se cuenta en "Unidad" (sin decimales):
    # al recibir una caja x 300 entran 30 sellos (= 300 unidades).
    ("unidad_venta", "Unidad de venta *", "Sobre x 10"),
    ("venta_trae", "¿Cuántas unidades trae?", "10"),
    ("venta_precio", "Precio de venta *", "1600"),
    ("venta_costo", "Costo de la unidad de venta", "1000"),
    ("venta_maximo", "Precio máximo regulado", ""),
    ("vende_suelto", "¿Se vende suelto? (SI/NO)", "SI"),
    ("precio_suelto", "Precio de 1 unidad suelta (opcional)", ""),
    ("iva_tipo", "IVA tipo (gravado/excluido/exento)", "gravado"),
    ("iva_tarifa", "IVA tarifa %", "19"),
    ("stock_minimo", "Stock mínimo (en unidades)", "50"),
    ("requiere_formula", "¿Requiere fórmula? (SI/NO)", "NO"),
    ("cadena_frio", "¿Cadena de frío? (SI/NO)", "NO"),
    ("control_especial", "¿Control especial? (SI/NO)", "NO"),
    ("maneja_vencimiento", "¿Maneja vencimiento? (SI/NO)", "SI"),
    ("categorias", "Categorías (separadas por coma)", "Analgésicos"),
    ("observaciones", "Observaciones", ""),
    # Otras formas de VENDER el mismo producto con su propio precio (opcional)
    ("pres2", "Otra presentación", "Caja x 100"),
    ("pres2_trae", "Otra presentación trae", "100"),
    ("pres2_precio", "Otra presentación precio", "15000"),
    ("pres3", "Otra presentación 2", ""),
    ("pres3_trae", "Otra presentación 2 trae", ""),
    ("pres3_precio", "Otra presentación 2 precio", ""),
]
# Columnas del formato ANTERIOR (precio de 1 tableta + presentaciones). No salen
# en la plantilla, pero si un archivo viejo las trae se siguen entendiendo.
COLUMNAS_ANTIGUAS = [
    ("unidad_inventario", "Unidad de inventario", "Tableta"),
    ("precio_compra", "Costo de 1 unidad", "120"),
    ("precio_venta", "Precio de 1 unidad", "200"),
    ("precio_maximo", "Precio máximo de 1 unidad", ""),
    ("vender_como", "Se vende normalmente por", "Sobre x 10"),
]
TODAS_LAS_COLUMNAS = COLUMNAS + COLUMNAS_ANTIGUAS
# Las presentaciones extra que acepta el archivo (2 y 3)
PRESENTACIONES_EXTRA = ("pres2", "pres3")
ENCABEZADOS = [c[1] for c in COLUMNAS]


def _abrir_archivo(nombre_archivo, contenido):
    """Devuelve una lista de filas (diccionarios) leyendo .xlsx o .csv."""
    nombre = nombre_archivo.lower()

    if nombre.endswith(".xlsx"):
        try:
            wb = load_workbook(io.BytesIO(contenido), data_only=True)
        except Exception as e:
            return None, f"No se pudo leer el archivo Excel: {e}"
        hoja = wb.active
        filas_raw = list(hoja.iter_rows(values_only=True))
        if not filas_raw:
            return None, "El archivo está vacío."
        encabezados = [str(c).strip() if c is not None else "" for c in filas_raw[0]]
        return _filas_a_dict(encabezados, filas_raw[1:]), None

    elif nombre.endswith(".csv"):
        try:
            texto = contenido.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                texto = contenido.decode("latin-1")
            except UnicodeDecodeError:
                return None, "No se pudo decodificar el CSV. Guarda el archivo en UTF-8."
        lector = list(csv.reader(io.StringIO(texto)))
        if not lector:
            return None, "El archivo está vacío."
        encabezados = [str(c).strip() for c in lector[0]]
        return _filas_a_dict(encabezados, lector[1:]), None

    return None, "Formato no soportado. Usa .xlsx o .csv."


def _filas_a_dict(encabezados, filas):
    """Convierte las filas en diccionarios {encabezado: valor}."""
    resultado = []
    for fila in filas:
        d = {}
        for i, valor in enumerate(fila):
            if i >= len(encabezados):
                break
            clave = encabezados[i]
            d[clave] = str(valor).strip() if valor is not None else ""
        resultado.append(d)
    return resultado


def _mapear_columnas(encabezados):
    """Empareja los encabezados del archivo con los campos esperados.

    Devuelve un diccionario {campo_sistema: nombre_columna_en_archivo}.
    Acepta variantes: 'nombre', 'Nombre', 'NOMBRE', sin tildes.
    """
    import unicodedata

    def normalizar(s):
        s = unicodedata.normalize("NFKD", str(s))
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = s.lower().strip().replace("*", "").replace("(", "").replace(")", "")
        s = s.replace("?", "").replace("¿", "").replace("%", "pct")
        return " ".join(s.split())

    mapa = {}
    for campo, etiqueta, _ej in TODAS_LAS_COLUMNAS:
        variantes = [normalizar(etiqueta), normalizar(campo)]
        # Alias manuales
        alias = {
            "codigo": ["codigo interno", "cod interno", "cod", "referencia", "sku"],
            "codigo_barras": ["barras", "codigo de barras", "ean", "ean13", "upc"],
            "nombre": ["nombre del producto", "producto", "descripcion producto"],
            "descripcion": ["descripcion corta"],
            "concentracion": ["concentracion mg", "dosis"],
            "principio": ["principio activo", "dci", "generico", "denominacion"],
            "laboratorio": ["laboratorio fabricante", "marca", "fabricante"],
            "forma_farmaceutica": ["forma farmaceutica", "forma", "presentacion"],
            "registro_sanitario": ["registro", "invima", "registro invima", "rs"],
            "registro_vence": ["vence registro", "vence rs", "vencimiento rs"],
            "precio_compra": ["costo de 1 unidad"],
            "unidad_venta": ["unidad de venta", "se vende por", "presentacion de venta", "unidad"],
            "venta_precio": ["precio", "precio venta", "pvp"],
            "venta_costo": ["costo", "precio costo", "precio compra", "precio de compra"],
            "venta_trae": ["trae", "cuantas trae", "unidades que trae"],
            "precio_suelto": ["precio suelto", "precio unidad suelta", "precio de 1 unidad suelta"],
            "pres2": ["presentacion 2"], "pres2_trae": ["presentacion 2 trae"],
            "pres2_precio": ["presentacion 2 precio"],
            "pres3": ["presentacion 3"], "pres3_trae": ["presentacion 3 trae"],
            "pres3_precio": ["presentacion 3 precio"],
            "precio_venta": ["precio de 1 unidad"],
            "precio_maximo": ["precio maximo", "pvp maximo", "precio regulado"],
            "unidad_inventario": ["unidad minima", "unidad de inventario"],
            "vender_como": ["vender como", "vender por defecto", "presentacion por defecto",
                            "el pos lo vende como"],
            "vende_suelto": ["se vende suelto", "vende suelto", "suelto", "fraccionable"],
            "iva_tipo": ["iva", "tipo iva"],
            "iva_tarifa": ["tarifa iva", "iva pct", "porcentaje iva"],
            "stock_minimo": ["minimo", "stock min", "minimo stock"],
            "requiere_formula": ["formula", "requiere formula", "con formula"],
            "cadena_frio": ["frio", "cadena de frio", "refrigerado"],
            "control_especial": ["control", "control especial", "fne", "psicotropico"],
            "maneja_vencimiento": ["vence", "maneja vencimiento", "con vencimiento"],
            "categorias": ["categoria", "categorias", "linea", "grupo categoria"],
            "observaciones": ["obs", "notas", "comentarios"],
        }
        for v in variantes + alias.get(campo, []):
            if v in mapa.values():
                continue
            for enc in encabezados:
                if enc in mapa.values():          # ese encabezado ya lo tomó otra columna
                    continue
                if normalizar(enc) == v:
                    mapa[campo] = enc
                    break
            if campo in mapa:
                break
    return mapa


def _bool(valor):
    """Convierte una cadena a 1/0."""
    if valor is None:
        return 0
    v = str(valor).strip().lower()
    return 1 if v in ("si", "sí", "s", "1", "yes", "true", "x", "verdadero") else 0


def _num(valor, defecto=0.0):
    """'1.800' -> 1800 (punto de miles) ; '2,5' -> 2.5 ; '$ 15.000' -> 15000 ; vacío -> defecto."""
    import re
    if valor is None or valor == "":
        return defecto
    t = str(valor).replace("$", "").replace(" ", "").strip()
    # Los puntos se quitan solo cuando son de miles (grupos de 3 cifras): 1.800 / 15.000
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "")
    try:
        return float(t.replace(",", "."))
    except (ValueError, TypeError):
        return defecto


def _obtener_id_catalogo(db, tipo, nombre, cache):
    """Devuelve el id del catálogo, creándolo si no existe. Usa cache."""
    if not nombre:
        return None
    clave = (tipo, nombre.strip().lower())
    if clave in cache:
        return cache[clave]
    fila = db.execute(
        "SELECT id FROM catalogos WHERE tipo = ? AND LOWER(TRIM(nombre)) = LOWER(TRIM(?)) LIMIT 1",
        (tipo, nombre.strip()),
    ).fetchone()
    if fila:
        cache[clave] = fila["id"]
        return fila["id"]
    cur = db.execute(
        "INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES (?, ?, 1, ?)",
        (tipo, nombre.strip(), ahora()),
    )
    cache[clave] = cur.lastrowid
    return cur.lastrowid


def _unidad_id(db, nombre, cache):
    """Id de la unidad de medida por su nombre (Tableta, Sobre x 10...). Si no
    existe, se crea. Si el nombre trae "x 10", esa es su cantidad."""
    import re
    nombre = " ".join(str(nombre or "").split())
    if not nombre:
        return None
    clave = ("unidad", nombre.lower())
    if clave in cache:
        return cache[clave]
    fila = db.execute("SELECT id FROM unidades_medida WHERE nombre = ? COLLATE NOCASE LIMIT 1", (nombre,)).fetchone()
    if fila is None:
        m = re.search(r"x\s*(\d+(?:[.,]\d+)?)\s*$", nombre, re.I)
        cantidad = float(m.group(1).replace(",", ".")) if m else 1
        fila = {"id": db.execute("INSERT INTO unidades_medida (nombre, cantidad, referencia_id, activo, creado_en) "
                                 "VALUES (?, ?, NULL, 1, ?)", (nombre, cantidad, ahora())).lastrowid}
    cache[clave] = fila["id"]
    return fila["id"]


def _unidad_por_defecto(db):
    fila = db.execute(
        "SELECT id FROM unidades_medida WHERE nombre = 'Unidad' LIMIT 1"
    ).fetchone()
    return fila["id"] if fila else None


def _modo_nuevo(fila, mapa):
    """¿La fila viene con "Unidad de venta" (formato nuevo, como la ficha)?"""
    return bool("unidad_venta" in mapa and (fila.get(mapa["unidad_venta"], "") or "").strip())


def _venta_de_fila(db, fila, mapa, cache, unidad_basica):
    """Formato nuevo -> como se guarda (igual que productos._traducir_venta).

    Ej: "Sobre x 10" a $1.600, costo $1.000, suelto SI
        -> se cuenta en Unidad; precio de 1 unidad $160; costo $100;
           presentación Sobre x 10 (trae 10) a $1.600, que el POS vende por defecto.
    Si la unidad de venta trae 1 (Frasco), se vende y se cuenta en Frasco.
    """
    venta_uid = _unidad_id(db, fila.get(mapa["unidad_venta"], ""), cache)
    trae = _num(fila.get(mapa.get("venta_trae", "")), 0)
    if trae <= 1:
        fila_u = db.execute("SELECT cantidad FROM unidades_medida WHERE id = ?", (venta_uid,)).fetchone()
        trae = float(fila_u["cantidad"] or 1) if fila_u and venta_uid != unidad_basica else 1
    factor = trae if trae > 1 and unidad_basica else 1
    precio = _num(fila.get(mapa.get("venta_precio", "")), 0)
    costo = _num(fila.get(mapa.get("venta_costo", "")), 0)
    maximo = _num(fila.get(mapa.get("venta_maximo", "")), 0)
    texto_suelto = str(fila.get(mapa.get("vende_suelto", ""), "") or "").strip()
    suelto = 1 if (factor <= 1 or not texto_suelto) else _bool(texto_suelto)
    precio_suelto = _num(fila.get(mapa.get("precio_suelto", "")), 0)
    return {
        "venta_uid": venta_uid, "factor": factor, "precio": precio, "maximo": maximo or None,
        "base_uid": unidad_basica if factor > 1 else venta_uid,
        "vende_suelto": suelto,
        "precio_venta": precio_suelto if (factor > 1 and suelto and precio_suelto > 0) else round(precio / factor, 2),
        "precio_compra": round(costo / factor, 4),
        "precio_maximo": round(maximo / factor, 2) if maximo else None,
    }


def _validar_fila(fila, mapa):
    errores = []
    codigo = fila.get(mapa.get("codigo", ""), "").strip()
    nombre = fila.get(mapa.get("nombre", ""), "").strip()
    if not codigo:
        errores.append("Falta el código")
    if not nombre:
        errores.append("Falta el nombre")
    iva_tipo = (fila.get(mapa.get("iva_tipo", ""), "") or "gravado").strip().lower()
    if iva_tipo not in ("gravado", "excluido", "exento"):
        iva_tipo = "gravado"
    if _bool(fila.get(mapa.get("control_especial", ""))) and not fila.get(mapa.get("registro_sanitario", "")):
        errores.append("Control especial requiere Registro INVIMA")
    if _modo_nuevo(fila, mapa):
        # Formato nuevo: la unidad de venta necesita su precio
        if _num(fila.get(mapa.get("venta_precio", "")), 0) <= 0:
            errores.append("Falta el precio de venta")
    # Formato anterior: si NO se vende suelto, debe tener al menos una presentación (sobre, caja...)
    elif "vende_suelto" in mapa and str(fila.get(mapa["vende_suelto"], "")).strip() \
            and not _bool(fila.get(mapa["vende_suelto"])) \
            and not any((fila.get(mapa.get(p, ""), "") or "").strip() for p in PRESENTACIONES_EXTRA):
        errores.append("No se vende suelto pero no tiene presentaciones (ej. Sobre x 10)")
    # Presentaciones 2 y 3: si tienen nombre, deben traer más de 1 unidad y tener precio
    for p in PRESENTACIONES_EXTRA:
        nombre_p = (fila.get(mapa.get(p, ""), "") or "").strip()
        if not nombre_p:
            continue
        if _num(fila.get(mapa.get(p + "_trae", "")), 0) <= 1:
            errores.append(f"{nombre_p}: '¿cuántas trae?' debe ser mayor que 1")
        if _num(fila.get(mapa.get(p + "_precio", "")), 0) <= 0:
            errores.append(f"{nombre_p}: falta el precio")
    return errores


@bp.route("/")
@roles_required("administrador", "director_tecnico")
def inicio():
    return render_template("importador/inicio.html", columnas=COLUMNAS)


@bp.route("/plantilla")
@roles_required("administrador", "director_tecnico")
def plantilla():
    """Genera y descarga la plantilla en Excel y CSV."""
    formato = request.args.get("formato", "xlsx").lower()

    if formato == "csv":
        buffer = io.StringIO()
        escritor = csv.writer(buffer)
        escritor.writerow(ENCABEZADOS)
        # Fila de ejemplo
        # Fila de ejemplo: sale de la 3.ª parte de cada columna en COLUMNAS
        escritor.writerow([ejemplo for _c, _e, ejemplo in COLUMNAS])
        data = buffer.getvalue().encode("utf-8-sig")
        return send_file(
            io.BytesIO(data), mimetype="text/csv",
            as_attachment=True, download_name="plantilla_productos.csv"
        )

    # xlsx por defecto
    wb = Workbook()
    hoja = wb.active
    hoja.title = "Productos"
    hoja.append(ENCABEZADOS)
    # Fila de ejemplo (los números van como números, para que Excel no los marque)
    def _como_numero(texto):
        try:
            # los códigos de barras (8 cifras o más) se dejan como texto
            return int(texto) if str(texto).isdigit() and len(str(texto)) < 8 else texto
        except ValueError:
            return texto
    hoja.append([_como_numero(ejemplo) or None for _c, _e, ejemplo in COLUMNAS])
    # Ajustar ancho de columnas
    for i, enc in enumerate(ENCABEZADOS, 1):
        letra = hoja.cell(row=1, column=i).column_letter
        hoja.column_dimensions[letra].width = min(max(len(enc) + 3, 12), 32)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name="plantilla_productos.xlsx",
    )


@bp.route("/previsualizar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def previsualizar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Debes seleccionar un archivo.", "error")
        return redirect(url_for("importador.inicio"))

    contenido = archivo.read()
    filas, error = _abrir_archivo(archivo.filename, contenido)
    if error:
        flash(error, "error")
        return redirect(url_for("importador.inicio"))

    if not filas:
        flash("El archivo no tiene filas de datos.", "error")
        return redirect(url_for("importador.inicio"))

    # Detectar encabezados disponibles
    encabezados = list(filas[0].keys())
    mapa = _mapear_columnas(encabezados)

    if "codigo" not in mapa or "nombre" not in mapa:
        flash(
            f"No se pudieron reconocer las columnas obligatorias. "
            f"Se esperan al menos 'Código' y 'Nombre'. "
            f"Encabezados encontrados: {', '.join(encabezados[:8])}...",
            "error"
        )
        return redirect(url_for("importador.inicio"))

    # Analizar cada fila
    db = get_db()
    analisis = []
    total = len(filas)
    validas = 0
    duplicadas = 0
    con_error = 0

    for i, fila in enumerate(filas, 1):
        codigo = (fila.get(mapa.get("codigo", ""), "") or "").strip()
        nombre = (fila.get(mapa.get("nombre", ""), "") or "").strip()
        errores = _validar_fila(fila, mapa)

        existe = None
        if codigo:
            existe = db.execute(
                "SELECT id FROM productos WHERE LOWER(TRIM(codigo)) = LOWER(TRIM(?)) LIMIT 1",
                (codigo,),
            ).fetchone()

        estado = "ok"
        if errores:
            estado = "error"
            con_error += 1
        elif existe:
            estado = "duplicado"
            duplicadas += 1
        else:
            validas += 1

        analisis.append({
            "fila": i,
            "codigo": codigo,
            "nombre": nombre,
            "estado": estado,
            "errores": errores,
        })

    # Guardar el archivo temporalmente para el paso de confirmación
    # Lo cargamos en memoria y lo volvemos a leer en confirmar, así que guardamos
    # los datos clave en un archivo temporal por sesión.
    import json
    from flask import session
    # Solo guardamos el análisis (sin el contenido del archivo), y en el siguiente paso
    # volvemos a leer el archivo desde el cliente.
    # PERO: para simplificar, guardamos los datos completos en un archivo temporal.
    import tempfile
    import os as _os

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"filas": filas, "mapa": mapa}, tmp, ensure_ascii=False)
    tmp.close()
    session["importador_tmp"] = tmp.name

    return render_template(
        "importador/previsualizar.html",
        analisis=analisis[:50],
        total=total,
        validas=validas,
        duplicadas=duplicadas,
        con_error=con_error,
        encabezados=encabezados,
        mapa=mapa,
    )


@bp.route("/confirmar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def confirmar():
    import json
    import os as _os
    from flask import session

    tmp = session.pop("importador_tmp", None)
    if not tmp or not _os.path.exists(tmp):
        flash("La sesión de importación expiró. Vuelve a subir el archivo.", "error")
        return redirect(url_for("importador.inicio"))

    with open(tmp, "r", encoding="utf-8") as f:
        datos = json.load(f)
    _os.unlink(tmp)

    filas = datos["filas"]
    mapa = datos["mapa"]

    db = get_db()
    unidad_default = _unidad_por_defecto(db)
    cache_cat = {}
    importados = 0
    omitidos = 0
    errores = []
    catalogos_nuevos = 0

    for i, fila in enumerate(filas, 1):
        codigo = (fila.get(mapa.get("codigo", ""), "") or "").strip()
        nombre = (fila.get(mapa.get("nombre", ""), "") or "").strip()
        errs = _validar_fila(fila, mapa)
        if errs:
            errores.append(f"Fila {i} ({codigo or 'sin código'}): {', '.join(errs)}")
            continue

        existe = db.execute(
            "SELECT id FROM productos WHERE LOWER(TRIM(codigo)) = LOWER(TRIM(?)) LIMIT 1",
            (codigo,),
        ).fetchone()
        if existe:
            omitidos += 1
            continue

        try:
            principio_id = _obtener_id_catalogo(db, "principio", fila.get(mapa.get("principio", ""), ""), cache_cat)
            laboratorio_id = _obtener_id_catalogo(db, "laboratorio", fila.get(mapa.get("laboratorio", ""), ""), cache_cat)
            forma_id = _obtener_id_catalogo(db, "forma_farmaceutica", fila.get(mapa.get("forma_farmaceutica", ""), ""), cache_cat)

            iva_tipo = (fila.get(mapa.get("iva_tipo", ""), "") or "gravado").strip().lower()
            if iva_tipo not in ("gravado", "excluido", "exento"):
                iva_tipo = "gravado"
            iva_tarifa = _num(fila.get(mapa.get("iva_tarifa", "")), 19 if iva_tipo == "gravado" else 0)

            venta = _venta_de_fila(db, fila, mapa, cache_cat, unidad_default) if _modo_nuevo(fila, mapa) else None
            if venta:
                precio_venta, precio_compra = venta["precio_venta"], venta["precio_compra"]
                precio_maximo = venta["precio_maximo"]
                unidad_base = venta["base_uid"]
            else:
                # Formato anterior: precios de 1 unidad de inventario
                # (un archivo de otro programa con solo "Precio" y "Costo" también sirve)
                precio_venta = (_num(fila.get(mapa.get("precio_venta", "")), 0)
                                or _num(fila.get(mapa.get("venta_precio", "")), 0))
                precio_compra = (_num(fila.get(mapa.get("precio_compra", "")), 0)
                                 or _num(fila.get(mapa.get("venta_costo", "")), 0))
                precio_maximo = _num(fila.get(mapa.get("precio_maximo", "")), 0) or None
                unidad_base = _unidad_id(db, fila.get(mapa.get("unidad_inventario", ""), ""), cache_cat) or unidad_default

            stock_minimo = int(_num(fila.get(mapa.get("stock_minimo", "")), 0))
            requiere_formula = _bool(fila.get(mapa.get("requiere_formula", "")))
            cadena_frio = _bool(fila.get(mapa.get("cadena_frio", "")))
            control_especial = _bool(fila.get(mapa.get("control_especial", "")))
            maneja_v = _bool(fila.get(mapa.get("maneja_vencimiento", "")))
            if maneja_v == 0 and "maneja_vencimiento" not in mapa:
                maneja_v = 1
            if cadena_frio or control_especial:
                maneja_v = 1

            cur = db.execute(
                "INSERT INTO productos (codigo, codigo_barras, nombre, descripcion, grupo, "
                "concentracion, principio_id, laboratorio_id, forma_farmaceutica_id, "
                "registro_sanitario, registro_vence, precio_compra, precio_venta, precio_maximo, "
                "iva_tipo, iva_tarifa, stock_minimo, requiere_formula, cadena_frio, "
                "control_especial, maneja_vencimiento, unidad_venta_id, observaciones, "
                "activo, creado_en, creado_en_importacion) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,1)",
                (codigo,
                 (fila.get(mapa.get("codigo_barras", ""), "") or "").strip() or None,
                 nombre,
                 (fila.get(mapa.get("descripcion", ""), "") or "").strip() or None,
                 (fila.get(mapa.get("grupo", ""), "") or "").strip() or None,
                 (fila.get(mapa.get("concentracion", ""), "") or "").strip() or None,
                 principio_id, laboratorio_id, forma_id,
                 (fila.get(mapa.get("registro_sanitario", ""), "") or "").strip() or None,
                 (fila.get(mapa.get("registro_vence", ""), "") or "").strip() or None,
                 precio_compra, precio_venta, precio_maximo,
                 iva_tipo, iva_tarifa, stock_minimo,
                 requiere_formula, cadena_frio, control_especial, maneja_v,
                 unidad_base,
                 (fila.get(mapa.get("observaciones", ""), "") or "").strip() or None,
                 ahora()),
            )
            pid = cur.lastrowid

            # Presentaciones (Sobre x 10, Caja x 100) y cuál vende el POS por defecto
            vender_como = (fila.get(mapa.get("vender_como", ""), "") or "").strip().lower()
            # ¿Se vende suelto? Vacío = SÍ (como siempre)
            texto_suelto = str(fila.get(mapa.get("vende_suelto", ""), "") or "").strip()
            suelto = 1 if not texto_suelto else _bool(texto_suelto)
            primera_pres = None
            if venta:
                suelto = venta["vende_suelto"]
                db.execute("UPDATE productos SET vende_suelto = ? WHERE id = ?", (suelto, pid))
                if venta["factor"] > 1:
                    # La unidad de venta (Sobre x 10) es una presentación que el POS vende por defecto
                    db.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                               "precio_maximo, creado_en) VALUES (?,?,?,?,?,?)",
                               (pid, venta["venta_uid"], venta["factor"], venta["precio"], venta["maximo"], ahora()))
                    db.execute("UPDATE productos SET venta_defecto_unidad_id = ? WHERE id = ?",
                               (venta["venta_uid"], pid))
            for p in PRESENTACIONES_EXTRA:
                nombre_p = (fila.get(mapa.get(p, ""), "") or "").strip()
                if not nombre_p:
                    continue
                uid = _unidad_id(db, nombre_p, cache_cat)
                if venta and uid in (venta["venta_uid"], venta["base_uid"]):
                    continue                      # ya es la unidad de venta o la mínima
                db.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                           "creado_en) VALUES (?,?,?,?,?)",
                           (pid, uid, _num(fila.get(mapa.get(p + "_trae", "")), 0),
                            _num(fila.get(mapa.get(p + "_precio", "")), 0), ahora()))
                if vender_como and vender_como == nombre_p.lower():
                    db.execute("UPDATE productos SET venta_defecto_unidad_id = ? WHERE id = ?", (uid, pid))
                if primera_pres is None:
                    primera_pres = (uid, _num(fila.get(mapa.get(p + "_trae", "")), 0),
                                    _num(fila.get(mapa.get(p + "_precio", "")), 0))
            if not suelto and not venta:
                # Solo se vende por presentación: si no dijeron cuál, la primera; y si no
                # pusieron precio de 1 unidad, se calcula (precio del sobre ÷ cuántas trae)
                db.execute("UPDATE productos SET vende_suelto = 0, "
                           "venta_defecto_unidad_id = COALESCE(venta_defecto_unidad_id, ?) WHERE id = ?",
                           (primera_pres[0], pid))
                if precio_venta <= 0 and primera_pres[1] > 0:
                    db.execute("UPDATE productos SET precio_venta = ? WHERE id = ?",
                               (round(primera_pres[2] / primera_pres[1], 2), pid))

            # Categorías
            cats = (fila.get(mapa.get("categorias", ""), "") or "").strip()
            if cats:
                for cat in [c.strip() for c in cats.split(",") if c.strip()]:
                    cat_id = _obtener_id_catalogo(db, "categoria", cat, cache_cat)
                    if cat_id:
                        db.execute(
                            "INSERT OR IGNORE INTO productos_categorias (producto_id, catalogo_id) "
                            "VALUES (?, ?)", (pid, cat_id)
                        )

            importados += 1
        except Exception as e:
            errores.append(f"Fila {i} ({codigo}): {e}")

    db.commit()

    # Contar catálogos nuevos (los que no estaban en cache al inicio)
    catalogos_creados = len(cache_cat)

    registrar("productos_importados", detalle=(
        f"importados={importados} omitidos={omitidos} errores={len(errores)} "
        f"catalogos_creados={catalogos_creados}"
    ))

    return render_template(
        "importador/resultado.html",
        importados=importados,
        omitidos=omitidos,
        errores=errores,
        total=importados + omitidos + len(errores),
        catalogos_creados=catalogos_creados,
    )


@bp.route("/reporte-errores", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def reporte_errores():
    """Devuelve un CSV con las líneas de error (enviadas por POST)."""
    errores_texto = request.form.get("errores", "")
    buffer = io.StringIO()
    buffer.write("Errores de importación\n")
    buffer.write(errores_texto)
    data = buffer.getvalue().encode("utf-8-sig")
    return send_file(
        io.BytesIO(data), mimetype="text/csv",
        as_attachment=True, download_name="errores_importacion.csv"
    )