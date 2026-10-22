"""
GESTIÓN DOCUMENTAL (Fase 4.1)
=============================

PARA QUÉ (para aprender):
    La Secretaría de Salud revisa que la droguería tenga ESCRITOS sus
    procedimientos (recepción técnica, dispensación, devoluciones...), que
    cada uno tenga CÓDIGO y VERSIÓN, que se sepa QUÉ CAMBIÓ en cada versión
    (control de cambios) y que se REVISEN cada cierto tiempo.

    Este módulo guarda todo eso:
      - El LISTADO MAESTRO: todos los documentos, con su estado:
            por_hacer -> todavía no está escrito
            borrador  -> ya hay archivo, falta aprobarlo y firmarlo
            vigente   -> aprobado: es el que se usa
            obsoleto  -> se retiró (su historial se conserva)
      - El HISTORIAL de cada documento: cada versión subida (con su archivo)
        y cada revisión "sin cambios". NADA se borra.
      - La PRÓXIMA REVISIÓN: fecha de aprobación + frecuencia (12 meses por
        defecto). Si se pasa, sale un aviso en el Inicio.
      - Un PDF del listado maestro para mostrarle al inspector.

QUIÉN PUEDE:
    Ver y descargar los documentos: todos (los auxiliares deben poder leer
    los procedimientos). Crear, subir versiones, aprobar y revisar:
    administrador y director técnico.

TABLAS (migración 30 en app/db.py): documentos y documento_versiones.
"""
import os
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import uuid

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_file, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .equipos import estado_calibracion, sumar_meses   # mismas cuentas de fechas que las calibraciones
from .utils_imagenes import guardar_documento

bp = Blueprint("documentos", __name__, url_prefix="/documentos")

TIPOS = {
    "procedimiento": "Procedimiento",
    "formato": "Formato / registro",
    "manual": "Manual",
    "politica": "Política / documento base",
    "plan": "Plan / programa",
    "otro": "Otro",
}

# Texto y color de cada estado (el color usa las mismas "pastillas" de Equipos)
ESTADOS = {
    "por_hacer": ("Por hacer", "gris"),
    "borrador": ("Borrador", "amarillo"),
    "vigente": ("Vigente", "verde"),
    "obsoleto": ("Obsoleto", "gris"),
}

# Revisión del documento vigente (cuando le toca volver a revisarse)
REVISION = {
    "vencida": ("Revisión vencida", "rojo"),
    "por_vencer": ("Revisar pronto", "amarillo"),
    "al_dia": ("Al día", "verde"),
}

# Archivos que se aceptan. Las FOTOS y los PDF los guarda guardar_documento()
# (el mismo de los certificados de calibración). Word y Excel se guardan tal
# cual, revisando que por dentro sean de verdad de ese tipo.
# Versión 1.1.8: también ".jfif" y sus primos (son fotos JPG; ver utils_imagenes.EXT_JPG_OTROS)
EXT_FOTO_PDF = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".jfif", ".jpe", ".pjpeg", ".pjp"}
EXT_OFFICE = {
    # extensión: cómo empieza el archivo por dentro ("firma" del formato)
    ".docx": b"PK\x03\x04", ".xlsx": b"PK\x03\x04", ".odt": b"PK\x03\x04", ".ods": b"PK\x03\x04",
    ".doc": b"\xd0\xcf\x11\xe0", ".xls": b"\xd0\xcf\x11\xe0",
}
MAX_BYTES = 15 * 1024 * 1024   # 15 MB por archivo

# Listado sugerido: el mismo del documento "Documentos base del Sistema de
# Gestión de Calidad". Con el botón "Cargar listado sugerido" se crean los
# que falten (en estado "por hacer"), así no hay que escribirlos uno por uno.
LISTADO_SUGERIDO = [
    # (código, nombre, tipo, proceso)
    ("SGC-DOC-001", "Documentos base del sistema de calidad (misión, visión, política, mapa de procesos)", "politica", "Dirección técnica"),
    ("SGC-DOC-002", "Manual de funciones y perfiles de cargo", "manual", "Talento humano"),
    ("SGC-DOC-003", "Matriz de riesgos", "otro", "Evaluación y mejora"),
    ("PR-01", "Selección de medicamentos y productos", "procedimiento", "Selección"),
    ("PR-02", "Adquisición y evaluación de proveedores", "procedimiento", "Adquisición"),
    ("PR-03", "Recepción técnica y administrativa", "procedimiento", "Recepción técnica"),
    ("PR-04", "Almacenamiento", "procedimiento", "Almacenamiento"),
    ("PR-05", "Control de temperatura y humedad", "procedimiento", "Almacenamiento"),
    ("PR-06", "Control de fechas de vencimiento", "procedimiento", "Almacenamiento"),
    ("PR-07", "Dispensación", "procedimiento", "Dispensación"),
    ("PR-08", "Devoluciones a proveedores y de clientes", "procedimiento", "Devoluciones"),
    ("PR-09", "Cadena de frío", "procedimiento", "Almacenamiento"),
    ("PR-10", "Inventarios y conteos físicos", "procedimiento", "Inventarios"),
    ("PR-11", "Calibración y verificación de equipos", "procedimiento", "Equipos"),
    ("PR-12", "Limpieza, saneamiento y control de plagas", "procedimiento", "Saneamiento"),
    ("PR-13", "Manejo de residuos (PGIRHS)", "plan", "Saneamiento"),
    ("PR-14", "Farmacovigilancia", "procedimiento", "Dispensación"),
    ("PR-15", "Quejas, reclamos y satisfacción del usuario", "procedimiento", "Evaluación y mejora"),
    ("PR-16", "Capacitación del personal", "procedimiento", "Talento humano"),
    ("PR-17", "Autoinspección y acciones correctivas", "procedimiento", "Evaluación y mejora"),
    ("PR-18", "Control de documentos y registros", "procedimiento", "Gestión documental"),
    ("FT-03-01", "Acta de recepción técnica", "formato", "Recepción técnica"),
    ("FT-05-01", "Registro mensual de temperatura y humedad", "formato", "Almacenamiento"),
    ("FT-06-01", "Semáforo de vencimientos", "formato", "Almacenamiento"),
    ("FT-07-01", "Comprobante de venta y cotización", "formato", "Dispensación"),
    ("FT-08-01", "Acta de devolución", "formato", "Devoluciones"),
    ("FT-10-01", "Acta de conteo de inventario", "formato", "Inventarios"),
    ("FT-11-01", "Hoja de vida y calibración de equipos", "formato", "Equipos"),
]


# ----------------------------------------------------------------------
# Ayudas
# ----------------------------------------------------------------------

def _obtener(doc_id):
    fila = get_db().execute("SELECT * FROM documentos WHERE id = ?", (doc_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def estado_revision(doc, hoy=None):
    """Para un documento VIGENTE: ('vencida' | 'por_vencer' | 'al_dia', días). Si no es vigente: (None, None)."""
    if doc["estado"] != "vigente" or not doc["proxima_revision"]:
        return None, None
    estado, dias = estado_calibracion(doc["proxima_revision"], hoy)
    return (estado if estado in REVISION else None), dias


def orden(doc):
    """Para ordenar el listado como se lee: documentos base (SGC), procedimientos
    (PR), formatos (FT) y luego los demás; dentro de cada grupo, por código."""
    codigo = doc["codigo"].upper()
    grupo = next((i for i, p in enumerate(("SGC", "PR", "FT")) if codigo.startswith(p)), 3)
    return grupo, codigo


def _con_estado(fila):
    """Fila de documento -> diccionario listo para mostrar (textos y colores)."""
    d = dict(fila)
    d["tipo_texto"] = TIPOS.get(d["tipo"], d["tipo"])
    d["estado_texto"], d["estado_color"] = ESTADOS[d["estado"]]
    d["revision"], d["dias"] = estado_revision(d)
    if d["revision"]:
        d["revision_texto"], d["revision_color"] = REVISION[d["revision"]]
    return d


def siguiente_version(doc_id):
    """La versión que sigue: si la última fue '02', sugiere '03'. Sin versiones: '01'."""
    filas = get_db().execute("SELECT version FROM documento_versiones WHERE documento_id = ? AND tipo = 'version'",
                             (doc_id,)).fetchall()
    numeros = [int(f["version"]) for f in filas if str(f["version"]).isdigit()]
    return f"{(max(numeros) + 1) if numeros else 1:02d}"


def guardar_archivo(archivo):
    """Guarda el archivo de una versión. Devuelve (ruta, error).

    - PDF o foto (escaneo del documento firmado): con guardar_documento().
    - Word / Excel / LibreOffice: tal cual, revisando su "firma" interna para
      que no se cuele otro tipo de archivo con el nombre cambiado.
    """
    if not archivo or not archivo.filename:
        return None, "Adjunta el archivo del documento (PDF, Word, Excel o foto)."
    ext = Path(archivo.filename).suffix.lower()
    if ext in EXT_FOTO_PDF:
        return guardar_documento(archivo, "documentos", max_bytes=MAX_BYTES)
    if ext not in EXT_OFFICE:
        return None, "Ese tipo de archivo no se acepta. Sube PDF, Word (.docx), Excel (.xlsx) o una foto."
    archivo.seek(0, os.SEEK_END)
    peso = archivo.tell()
    archivo.seek(0)
    if peso > MAX_BYTES:
        return None, f"El archivo pesa {peso / 1024 / 1024:.1f} MB. Máximo: {MAX_BYTES / 1024 / 1024:.0f} MB."
    firma = EXT_OFFICE[ext]
    if archivo.read(len(firma)) != firma:
        return None, f"El archivo no parece un {ext} de verdad (¿está dañado?)."
    archivo.seek(0)
    from .utils_imagenes import carpeta_uploads
    carpeta = carpeta_uploads() / "documentos"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}{ext}"
    archivo.save(str(carpeta / nombre))
    return f"uploads/documentos/{nombre}", None


def _fecha_form(nombre, defecto=None):
    """Lee una fecha del formulario (aaaa-mm-dd). Vacía o mala -> defecto."""
    try:
        return date.fromisoformat(request.form.get(nombre) or "")
    except ValueError:
        return defecto


def _hacer_vigente(db, doc, version_id, fecha, aprobo):
    """Deja una versión como la VIGENTE del documento.

    La que estaba vigente pasa a 'reemplazada' (no se borra: queda en el
    historial). El documento copia los datos de la nueva versión y se le
    calcula la próxima revisión = fecha de aprobación + frecuencia.
    """
    db.execute("UPDATE documento_versiones SET estado = 'reemplazada' "
               "WHERE documento_id = ? AND estado = 'vigente' AND id <> ?", (doc["id"], version_id))
    db.execute("UPDATE documento_versiones SET estado = 'vigente', fecha = ?, aprobo = ? WHERE id = ?",
               (fecha.isoformat(), aprobo, version_id))
    v = db.execute("SELECT * FROM documento_versiones WHERE id = ?", (version_id,)).fetchone()
    proxima = sumar_meses(fecha, doc["frecuencia_meses"] or 12)
    db.execute("UPDATE documentos SET estado = 'vigente', version = ?, fecha_aprobacion = ?, "
               "proxima_revision = ?, archivo = ?, elaboro = ?, aprobo = ?, actualizado_en = ? WHERE id = ?",
               (v["version"], fecha.isoformat(), proxima.isoformat(), v["archivo"], v["elaboro"], aprobo,
                ahora(), doc["id"]))
    return proxima


# ----------------------------------------------------------------------
# Lista (listado maestro)
# ----------------------------------------------------------------------

FILTROS = {
    "activos": "Todos (sin obsoletos)",
    "por_hacer": "Por hacer",
    "borrador": "Borradores",
    "vigente": "Vigentes",
    "por_revisar": "Por revisar (revisión vencida o próxima)",
    "obsoleto": "Obsoletos",
}


@bp.route("/")
@login_required
def lista():
    filtro = request.args.get("filtro", "activos")
    q = (request.args.get("q") or "").strip()
    filas = get_db().execute("SELECT * FROM documentos").fetchall()
    todos = sorted((_con_estado(f) for f in filas), key=orden)

    # Conteos para las tarjetas de arriba (sin contar los obsoletos)
    activos = [d for d in todos if d["estado"] != "obsoleto"]
    conteo = {
        "total": len(activos),
        "vigente": sum(1 for d in activos if d["estado"] == "vigente"),
        "borrador": sum(1 for d in activos if d["estado"] == "borrador"),
        "por_hacer": sum(1 for d in activos if d["estado"] == "por_hacer"),
        "por_revisar": sum(1 for d in activos if d["revision"] in ("vencida", "por_vencer")),
    }

    # Filtro elegido
    if filtro == "por_revisar":
        documentos = [d for d in activos if d["revision"] in ("vencida", "por_vencer")]
    elif filtro in ESTADOS:
        documentos = [d for d in todos if d["estado"] == filtro]
    else:
        filtro = "activos"
        documentos = activos
    if q:
        bajo = q.lower()
        documentos = [d for d in documentos if bajo in d["codigo"].lower() or bajo in d["nombre"].lower()
                      or bajo in (d["proceso"] or "").lower()]
    return render_template("documentos/lista.html", documentos=documentos, conteo=conteo,
                           filtro=filtro, filtros=FILTROS, q=q, hay_documentos=bool(todos))


@bp.route("/sugerido", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def cargar_sugerido():
    """Crea los documentos del listado sugerido que todavía no existan (por código)."""
    db = get_db()
    existentes = {f["codigo"].upper() for f in db.execute("SELECT codigo FROM documentos")}
    nuevos = 0
    for codigo, nombre, tipo, proceso in LISTADO_SUGERIDO:
        if codigo.upper() in existentes:
            continue
        db.execute("INSERT INTO documentos (codigo, nombre, tipo, proceso, estado, creado_en) "
                   "VALUES (?,?,?,?, 'por_hacer', ?)", (codigo, nombre, tipo, proceso, ahora()))
        nuevos += 1
    db.commit()
    registrar("documentos_listado_sugerido", "documentos", None, f"creados={nuevos}")
    flash(f"Se agregaron {nuevos} documento(s) del listado sugerido." if nuevos
          else "Ya tenías todos los documentos del listado sugerido.", "ok")
    return redirect(url_for("documentos.lista"))


# ----------------------------------------------------------------------
# Crear y editar los datos de un documento (no su archivo)
# ----------------------------------------------------------------------

def _leer_form():
    try:
        frecuencia = int(request.form.get("frecuencia_meses") or 12)
    except ValueError:
        frecuencia = 0
    return {
        "codigo": (request.form.get("codigo") or "").strip().upper(),
        "nombre": (request.form.get("nombre") or "").strip(),
        "tipo": request.form.get("tipo") or "procedimiento",
        "proceso": (request.form.get("proceso") or "").strip() or None,
        "frecuencia_meses": frecuencia,
        "observaciones": (request.form.get("observaciones") or "").strip() or None,
    }


def _validar(datos, doc_id=None):
    errores = []
    if not datos["codigo"]:
        errores.append("El código es obligatorio (ej: PR-03).")
    elif get_db().execute("SELECT 1 FROM documentos WHERE UPPER(codigo) = ? AND id <> ?",
                          (datos["codigo"], doc_id or 0)).fetchone():
        errores.append(f"Ya existe un documento con el código {datos['codigo']}.")
    if not datos["nombre"]:
        errores.append("El nombre es obligatorio.")
    if datos["tipo"] not in TIPOS:
        errores.append("Tipo de documento no válido.")
    if not 1 <= datos["frecuencia_meses"] <= 60:
        errores.append("La frecuencia de revisión debe estar entre 1 y 60 meses.")
    return errores


@bp.route("/nuevo", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def nuevo():
    datos = None
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            cur = db.execute(
                "INSERT INTO documentos (codigo, nombre, tipo, proceso, frecuencia_meses, observaciones, "
                "estado, creado_en) VALUES (?,?,?,?,?,?, 'por_hacer', ?)",
                (datos["codigo"], datos["nombre"], datos["tipo"], datos["proceso"], datos["frecuencia_meses"],
                 datos["observaciones"], ahora()))
            db.commit()
            registrar("documento_creado", "documentos", cur.lastrowid, f"{datos['codigo']} {datos['nombre']}")
            flash("Documento creado. Ahora sube su archivo.", "ok")
            return redirect(url_for("documentos.ver", doc_id=cur.lastrowid))
        for e in errores:
            flash(e, "error")
    return render_template("documentos/form.html", doc=datos, tipos=TIPOS, nuevo=True)


@bp.route("/<int:doc_id>/editar", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def editar(doc_id):
    doc = _obtener(doc_id)
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos, doc_id)
        if not errores:
            db = get_db()
            # Si cambió la frecuencia y el documento está vigente, se recalcula la próxima revisión
            proxima = doc["proxima_revision"]
            if doc["estado"] == "vigente" and doc["fecha_aprobacion"]:
                ultima = db.execute("SELECT MAX(fecha) f FROM documento_versiones WHERE documento_id = ? "
                                    "AND (estado = 'vigente' OR tipo = 'revision')", (doc_id,)).fetchone()["f"]
                base = date.fromisoformat((ultima or doc["fecha_aprobacion"])[:10])
                proxima = sumar_meses(base, datos["frecuencia_meses"]).isoformat()
            db.execute("UPDATE documentos SET codigo=?, nombre=?, tipo=?, proceso=?, frecuencia_meses=?, "
                       "observaciones=?, proxima_revision=?, actualizado_en=? WHERE id=?",
                       (datos["codigo"], datos["nombre"], datos["tipo"], datos["proceso"],
                        datos["frecuencia_meses"], datos["observaciones"], proxima, ahora(), doc_id))
            db.commit()
            registrar("documento_editado", "documentos", doc_id, f"{datos['codigo']} {datos['nombre']}")
            flash("Datos del documento actualizados.", "ok")
            return redirect(url_for("documentos.ver", doc_id=doc_id))
        for e in errores:
            flash(e, "error")
        doc = dict(doc, **datos)
    return render_template("documentos/form.html", doc=doc, tipos=TIPOS, nuevo=False)


# ----------------------------------------------------------------------
# Ver un documento + historial
# ----------------------------------------------------------------------

@bp.route("/<int:doc_id>")
@login_required
def ver(doc_id):
    doc = _con_estado(_obtener(doc_id))
    historial = get_db().execute(
        "SELECT * FROM documento_versiones WHERE documento_id = ? ORDER BY fecha DESC, id DESC",
        (doc_id,)).fetchall()
    borradores = [v for v in historial if v["estado"] == "borrador"]
    from .configuracion import obtener_config
    config = obtener_config()
    return render_template("documentos/ver.html", doc=doc, historial=historial, borradores=borradores,
                           hoy=date.today().isoformat(), version_sugerida=siguiente_version(doc_id),
                           regente=config.get("regente_nombre") or "",
                           nombre_usuario=g.user["nombre"])


# ----------------------------------------------------------------------
# Subir una versión nueva (con su archivo)
# ----------------------------------------------------------------------

@bp.route("/<int:doc_id>/version", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def subir_version(doc_id):
    doc = _obtener(doc_id)
    volver = redirect(url_for("documentos.ver", doc_id=doc_id))
    if doc["estado"] == "obsoleto":
        flash("El documento está obsoleto. Reactívalo antes de subir una versión.", "error")
        return volver

    version = (request.form.get("version") or "").strip()
    cambio = (request.form.get("cambio") or "").strip()
    elaboro = (request.form.get("elaboro") or "").strip() or None
    aprobo = (request.form.get("aprobo") or "").strip() or None
    estado = "vigente" if request.form.get("estado") == "vigente" else "borrador"
    fecha = _fecha_form("fecha", date.today())

    # --- Validaciones ---
    errores = []
    if not version:
        errores.append("Escribe el número de versión (ej: 01).")
    elif get_db().execute("SELECT 1 FROM documento_versiones WHERE documento_id = ? AND tipo = 'version' "
                          "AND version = ?", (doc_id, version)).fetchone():
        errores.append(f"La versión {version} ya existe. Usa otro número.")
    if not cambio:
        # La primera versión casi siempre es "Emisión inicial"; las siguientes deben decir qué cambió
        primera = not get_db().execute("SELECT 1 FROM documento_versiones WHERE documento_id = ? "
                                       "AND tipo = 'version'", (doc_id,)).fetchone()
        if primera:
            cambio = "Emisión inicial"
        else:
            errores.append("Escribe qué cambió en esta versión (es el control de cambios).")
    if fecha > date.today():
        errores.append("La fecha no puede ser futura.")
    if estado == "vigente" and not aprobo:
        errores.append("Para dejarla vigente, escribe quién la aprobó.")
    if errores:
        for e in errores:
            flash(e, "error")
        return volver

    archivo, error = guardar_archivo(request.files.get("archivo"))
    if error:
        flash(f"No se guardó la versión: {error}", "error")
        return volver

    db = get_db()
    cur = db.execute(
        "INSERT INTO documento_versiones (documento_id, tipo, version, fecha, cambio, elaboro, aprobo, archivo, "
        "estado, usuario_id, usuario_nombre, creado_en) VALUES (?, 'version', ?,?,?,?,?,?,?,?,?,?)",
        (doc_id, version, fecha.isoformat(), cambio, elaboro, aprobo, archivo, estado,
         g.user["id"], g.user["nombre"], ahora()))
    if estado == "vigente":
        proxima = _hacer_vigente(db, doc, cur.lastrowid, fecha, aprobo)
        mensaje = f"Versión {version} vigente. Próxima revisión: {proxima.strftime('%d/%m/%Y')}."
    else:
        if doc["estado"] == "por_hacer":
            db.execute("UPDATE documentos SET estado = 'borrador', actualizado_en = ? WHERE id = ?",
                       (ahora(), doc_id))
        mensaje = f"Borrador {version} guardado. Cuando lo firmen, tócale «Aprobar»."
    db.commit()
    registrar("documento_version", "documentos", doc_id,
              f"{doc['codigo']} v{version} estado={estado} version_id={cur.lastrowid}")
    flash(mensaje, "ok")
    return volver


@bp.route("/<int:doc_id>/version/<int:version_id>/aprobar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def aprobar(doc_id, version_id):
    """Un borrador pasa a vigente (ya se revisó y se firmó)."""
    doc = _obtener(doc_id)
    volver = redirect(url_for("documentos.ver", doc_id=doc_id))
    v = get_db().execute("SELECT * FROM documento_versiones WHERE id = ? AND documento_id = ?",
                         (version_id, doc_id)).fetchone()
    if v is None or v["estado"] != "borrador":
        flash("Esa versión no es un borrador.", "error")
        return volver
    aprobo = (request.form.get("aprobo") or "").strip()
    fecha = _fecha_form("fecha", date.today())
    if not aprobo:
        flash("Escribe quién la aprobó.", "error")
        return volver
    if fecha > date.today():
        flash("La fecha de aprobación no puede ser futura.", "error")
        return volver
    db = get_db()
    proxima = _hacer_vigente(db, doc, version_id, fecha, aprobo)
    db.commit()
    registrar("documento_aprobado", "documentos", doc_id, f"{doc['codigo']} v{v['version']} aprobó={aprobo}")
    flash(f"Versión {v['version']} aprobada y vigente. Próxima revisión: {proxima.strftime('%d/%m/%Y')}.", "ok")
    return volver


# ----------------------------------------------------------------------
# Revisión sin cambios y obsoleto
# ----------------------------------------------------------------------

@bp.route("/<int:doc_id>/revisar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def revisar(doc_id):
    """Se revisó el documento y sigue igual: queda constancia y se corre la próxima revisión."""
    doc = _obtener(doc_id)
    volver = redirect(url_for("documentos.ver", doc_id=doc_id))
    if doc["estado"] != "vigente":
        flash("Solo se revisan los documentos vigentes.", "error")
        return volver
    reviso = (request.form.get("reviso") or "").strip()
    fecha = _fecha_form("fecha", date.today())
    if not reviso:
        flash("Escribe quién lo revisó.", "error")
        return volver
    if fecha > date.today():
        flash("La fecha de revisión no puede ser futura.", "error")
        return volver
    nota = (request.form.get("nota") or "").strip() or "Revisado: sigue vigente sin cambios"
    proxima = sumar_meses(fecha, doc["frecuencia_meses"] or 12)
    db = get_db()
    db.execute(
        "INSERT INTO documento_versiones (documento_id, tipo, version, fecha, cambio, aprobo, estado, "
        "usuario_id, usuario_nombre, creado_en) VALUES (?, 'revision', ?,?,?,?, 'vigente', ?,?,?)",
        (doc_id, doc["version"], fecha.isoformat(), nota, reviso, g.user["id"], g.user["nombre"], ahora()))
    db.execute("UPDATE documentos SET proxima_revision = ?, actualizado_en = ? WHERE id = ?",
               (proxima.isoformat(), ahora(), doc_id))
    db.commit()
    registrar("documento_revisado", "documentos", doc_id, f"{doc['codigo']} revisó={reviso}")
    flash(f"Revisión registrada. Próxima: {proxima.strftime('%d/%m/%Y')}.", "ok")
    return volver


@bp.route("/<int:doc_id>/obsoleto", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def obsoleto(doc_id):
    """Retira un documento (ya no aplica) o lo vuelve a activar. Nunca se borra."""
    doc = _obtener(doc_id)
    db = get_db()
    if doc["estado"] == "obsoleto":
        # Vuelve al estado que le corresponde según lo que tenga
        if doc["version"]:
            nuevo = "vigente"
        elif db.execute("SELECT 1 FROM documento_versiones WHERE documento_id = ?", (doc_id,)).fetchone():
            nuevo = "borrador"
        else:
            nuevo = "por_hacer"
        mensaje = "Documento reactivado."
    else:
        nuevo = "obsoleto"
        mensaje = "Documento marcado como obsoleto (su historial se conserva)."
    db.execute("UPDATE documentos SET estado = ?, actualizado_en = ? WHERE id = ?", (nuevo, ahora(), doc_id))
    db.commit()
    registrar("documento_obsoleto" if nuevo == "obsoleto" else "documento_reactivado", "documentos", doc_id,
              doc["codigo"])
    flash(mensaje, "ok")
    return redirect(url_for("documentos.ver", doc_id=doc_id))


# ----------------------------------------------------------------------
# PDF del listado maestro (para la visita de la Secretaría)
# ----------------------------------------------------------------------

@bp.route("/listado.pdf")
@login_required
def listado_pdf():
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    from .configuracion import obtener_config
    from .pdf_utils import COLOR_SUAVE, encabezado_pdf, estilo_tabla, pie_de_pagina

    config = obtener_config()
    docs = sorted((_con_estado(f) for f in get_db().execute(
        "SELECT * FROM documentos WHERE estado <> 'obsoleto'").fetchall()), key=orden)

    buffer = BytesIO()
    doc_pdf = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1.4 * cm, rightMargin=1.4 * cm,
                                topMargin=1.2 * cm, bottomMargin=1.5 * cm, title="Listado maestro de documentos")
    estilos = getSampleStyleSheet()
    celda = ParagraphStyle("Celda", parent=estilos["Normal"], fontSize=8.5, leading=10)
    sub = ParagraphStyle("Sub", parent=estilos["Normal"], fontSize=9, textColor=COLOR_SUAVE)

    fecha = lambda f: f"{f[8:10]}/{f[5:7]}/{f[0:4]}" if f else "—"
    elementos = list(encabezado_pdf(config, "LISTADO MAESTRO DE DOCUMENTOS"))
    vigentes = sum(1 for d in docs if d["estado"] == "vigente")
    elementos.append(Paragraph(
        f"Corte: <b>{datetime.now().strftime('%d/%m/%Y')}</b> · Documentos: {len(docs)} · Vigentes: {vigentes} · "
        f"Borradores: {sum(1 for d in docs if d['estado'] == 'borrador')} · "
        f"Por hacer: {sum(1 for d in docs if d['estado'] == 'por_hacer')}", sub))
    elementos.append(Spacer(1, 6))

    data = [["Código", "Documento", "Tipo", "Proceso", "Versión", "Aprobado", "Aprobó", "Próx. revisión", "Estado"]]
    for d in docs:
        estado = d["estado_texto"] + (f" · {d['revision_texto']}" if d.get("revision") in ("vencida", "por_vencer") else "")
        data.append([Paragraph(str(x), celda) for x in (
            d["codigo"], d["nombre"], d["tipo_texto"], d["proceso"] or "—", d["version"] or "—",
            fecha(d["fecha_aprobacion"]), d["aprobo"] or "—", fecha(d["proxima_revision"]), estado)])
    if len(data) == 1:
        data.append(["—", "No hay documentos registrados.", "", "", "", "", "", "", ""])
    tabla = Table(data, colWidths=[2.2 * cm, 7.6 * cm, 2.8 * cm, 3.2 * cm, 1.4 * cm, 2.0 * cm, 3.2 * cm,
                                   2.2 * cm, 2.4 * cm], repeatRows=1)
    tabla.setStyle(estilo_tabla())
    elementos.append(tabla)

    regente = config.get("regente_nombre") or ""
    if regente:
        elementos.append(Spacer(1, 24))
        elementos.append(Paragraph(
            f"_______________________________________<br/><b>{regente}</b><br/>"
            f"Director Técnico — Tarjeta profesional {config.get('regente_tarjeta') or '—'}", sub))

    doc_pdf.build(elementos, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=f"listado_maestro_{datetime.now().strftime('%Y%m%d')}.pdf")
