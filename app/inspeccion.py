"""MODO INSPECCIÓN (versión 1.1.16).

PARA QUÉ
--------
Cuando llega la Secretaría de Salud (o el INVIMA) piden «muéstreme las planillas
de temperatura, la limpieza, los residuos, el certificado de fumigación...».
Esta página junta TODO en un solo lugar y deja descargarlo en UN archivo .zip:

  - Planilla mensual de temperaturas (una por cada zona activa)
  - Planilla de limpieza del mes y registro de residuos del mes
  - Semáforo de vencimientos (de hoy)
  - Listado maestro de documentos y plan de capacitaciones del año
  - Certificados escaneados: última fumigación, última calibración de cada
    equipo y entregas de residuos del año
  - (Opcional) los archivos de los documentos vigentes

Además muestra «lo que el inspector vería pendiente»: las mismas alertas de
calidad de la página de Alertas (calibraciones vencidas, limpieza atrasada...),
para arreglarlas ANTES de que lleguen.

CÓMO ARMA LOS PDF (sin repetir código)
--------------------------------------
Cada PDF ya existe en su módulo (reportes, saneamiento, documentos...). En vez de
copiar ese código, aquí se «llama» a la misma página que genera el PDF, como si
alguien la hubiera abierto en el navegador, y se guarda lo que devuelve. Eso hace
_pdf_de(): crea una petición de mentiras (test_request_context) con los datos del
mes y ejecuta la función de esa página. El usuario (g.user) es el mismo que está
descargando, así que se respetan los permisos.
"""
import io
import zipfile
from datetime import date

from flask import (Blueprint, current_app, flash, g, redirect, render_template, request,
                   send_file, url_for)

from .audit import registrar
from .auth import login_required
from .db import get_db
from .utils_imagenes import ruta_de

bp = Blueprint("inspeccion", __name__, url_prefix="/inspeccion")

# Las alertas (app/alertas.py) que tienen que ver con lo que revisa el inspector
ALERTAS_CALIDAD = ("lotes_vencidos", "precio_maximo", "invima_vencido", "invima_por_vencer",
                   "proveedor_vencido", "calibracion_vencida", "calibracion_por_vencer",
                   "documentos_por_revisar", "limpieza_pendiente", "plagas_", "residuos_sin_entregar",
                   "capacitaciones_atrasadas", "pqrs_vencidas", "farmacovigilancia_graves",
                   "farmacovigilancia_por_reportar", "cuarentena")

# Lo que se puede incluir en el .zip: (clave, texto en pantalla, ¿marcado de una vez?)
PARTES = [
    ("temperaturas", "🌡️ Planillas de temperatura del mes (una por zona)", True),
    ("limpieza", "🧽 Planilla de limpieza del mes", True),
    ("residuos", "♻️ Registro de residuos del mes", True),
    ("vencimientos", "📅 Semáforo de vencimientos (de hoy)", True),
    ("documentos", "🗂️ Listado maestro de documentos", True),
    ("capacitaciones", "🎓 Plan de capacitaciones del año", True),
    ("certificados", "📎 Certificados: fumigación, calibraciones y entregas de residuos", True),
    ("archivos_documentos", "📚 Archivos de los documentos vigentes (puede pesar bastante)", False),
]


def _mes_elegido():
    """'2026-10' del formulario → (2026, 10). Si no viene o viene malo, el mes actual."""
    try:
        anio, mes = (int(x) for x in (request.values.get("mes") or "").split("-"))
        date(anio, mes, 1)
        return anio, mes
    except ValueError:
        hoy = date.today()
        return hoy.year, hoy.month


def _alertas_calidad():
    """Las alertas de calidad pendientes (las rojas primero)."""
    from .alertas import calcular_alertas
    return [a for a in calcular_alertas(g.user["rol"]) if a["clave"].startswith(ALERTAS_CALIDAD)]


def _zonas():
    return get_db().execute("SELECT id, nombre FROM zonas_temperatura WHERE activa = 1 ORDER BY nombre").fetchall()


@bp.route("/")
@login_required
def inicio():
    anio, mes = _mes_elegido()
    return render_template("inspeccion/index.html", mes=f"{anio}-{mes:02d}", partes=PARTES,
                           alertas=_alertas_calidad(), zonas=_zonas(), certificados=_certificados(anio))


# ---------------------------------------------------------------------
# Armar el .zip
# ---------------------------------------------------------------------

def _pdf_de(endpoint, **args):
    """Ejecuta la página que genera un PDF y devuelve sus bytes (o None si no salió un PDF).

    endpoint: el nombre de la página, por ejemplo 'saneamiento.limpieza_pdf'.
    args:     lo que iría en la dirección (?mes=2026-10&zona_id=1...).
    """
    vista = current_app.view_functions[endpoint]
    with current_app.test_request_context(url_for(endpoint), query_string=args):
        respuesta = current_app.make_response(vista())
        respuesta.direct_passthrough = False        # (para poder leer el archivo que manda send_file)
        datos = respuesta.get_data()
        respuesta.close()
    return datos if datos.startswith(b"%PDF") else None


def _certificados(anio):
    """Los archivos escaneados que se adjuntan: (carpeta en el zip, nombre, ruta guardada, texto)."""
    db = get_db()
    lista = []
    # Última fumigación / control de plagas que tenga archivo
    f = db.execute("SELECT fecha, empresa, archivo FROM control_plagas WHERE archivo IS NOT NULL AND archivo <> '' "
                   "ORDER BY fecha DESC LIMIT 1").fetchone()
    if f:
        lista.append(("Certificados", f"Fumigacion_{f['fecha']}", f["archivo"],
                      f"Control de plagas del {f['fecha']} ({f['empresa'] or 'sin empresa'})"))
    # La última calibración de cada equipo activo
    for c in db.execute(
            "SELECT e.nombre, c.fecha, c.archivo FROM equipos e "
            "JOIN calibraciones c ON c.id = (SELECT id FROM calibraciones WHERE equipo_id = e.id "
            "AND archivo IS NOT NULL AND archivo <> '' ORDER BY fecha DESC, id DESC LIMIT 1) "
            "WHERE e.activo = 1 ORDER BY e.nombre"):
        lista.append(("Certificados", f"Calibracion_{c['nombre']}_{c['fecha']}", c["archivo"],
                      f"Calibración de {c['nombre']} del {c['fecha']}"))
    # Entregas de residuos al gestor en el año
    for r in db.execute("SELECT fecha, gestor, archivo FROM residuos_entregas WHERE archivo IS NOT NULL "
                        "AND archivo <> '' AND fecha LIKE ? ORDER BY fecha", (f"{anio}-%",)):
        lista.append(("Certificados", f"Residuos_{r['fecha']}_{r['gestor']}", r["archivo"],
                      f"Entrega de residuos del {r['fecha']} ({r['gestor']})"))
    return lista


def _limpio(texto):
    """Quita del nombre lo que Windows no deja poner en un archivo ( / \\ : * ? \" < > | )."""
    return "".join("_" if ch in '/\\:*?"<>|' else ch for ch in str(texto)).strip()


@bp.route("/descargar", methods=["POST"])
@login_required
def descargar():
    """Arma el .zip con lo que se marcó y lo descarga."""
    anio, mes = _mes_elegido()
    texto_mes = f"{anio}-{mes:02d}"
    elegidas = set(request.form.getlist("partes"))
    if not elegidas:
        flash("Marca al menos una cosa para descargar.", "error")
        return redirect(url_for("inspeccion.inicio", mes=texto_mes))

    # Lista de PDFs a generar: (nombre dentro del zip, página, datos)
    pdfs = []
    if "temperaturas" in elegidas:
        for z in _zonas():
            pdfs.append((f"Temperaturas_{_limpio(z['nombre'])}_{texto_mes}.pdf", "reportes.temperaturas_mensual_pdf",
                         {"zona_id": z["id"], "mes": mes, "anio": anio}))
    if "limpieza" in elegidas:
        pdfs.append((f"Limpieza_{texto_mes}.pdf", "saneamiento.limpieza_pdf", {"mes": texto_mes}))
    if "residuos" in elegidas:
        pdfs.append((f"Residuos_{texto_mes}.pdf", "saneamiento.residuos_pdf", {"mes": texto_mes}))
    if "vencimientos" in elegidas:
        pdfs.append((f"Vencimientos_{date.today().isoformat()}.pdf", "reportes.vencimientos_pdf", {}))
    if "documentos" in elegidas:
        pdfs.append(("Listado_maestro_documentos.pdf", "documentos.listado_pdf", {}))
    if "capacitaciones" in elegidas:
        pdfs.append((f"Plan_capacitaciones_{anio}.pdf", "capacitaciones.plan_pdf", {"anio": anio}))

    memoria = io.BytesIO()
    hechos, fallaron = 0, []
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        # 1) Los PDF que arma el programa
        for numero, (nombre, endpoint, args) in enumerate(pdfs, start=1):
            try:
                datos = _pdf_de(endpoint, **args)
            except Exception:                      # un PDF dañado no debe dañar todo el paquete
                current_app.logger.exception("Modo inspección: falló %s", endpoint)
                datos = None
            if datos:
                z.writestr(f"{numero:02d}_{nombre}", datos)
                hechos += 1
            else:
                fallaron.append(nombre)
        # 2) Los certificados escaneados (tal como se subieron)
        archivos = _certificados(anio) if "certificados" in elegidas else []
        if "archivos_documentos" in elegidas:
            archivos += [("Documentos vigentes", f"{d['codigo']}_{d['nombre']}", d["archivo"], d["nombre"])
                         for d in get_db().execute(
                             "SELECT codigo, nombre, archivo FROM documentos WHERE estado = 'vigente' "
                             "AND archivo IS NOT NULL AND archivo <> '' ORDER BY codigo")]
        for carpeta, nombre, ruta, _texto in archivos:
            fisico = ruta_de(ruta)
            if fisico.is_file():
                z.write(fisico, f"{carpeta}/{_limpio(nombre)}{fisico.suffix.lower()}")
                hechos += 1
            else:
                fallaron.append(f"{nombre} (no se encontró el archivo)")
        # 3) Una nota que explica qué hay (y qué faltó)
        nota = [f"Paquete para inspección · {texto_mes}", f"Generado el {date.today().isoformat()} por {g.user['nombre']}",
                "", f"Archivos incluidos: {hechos}"]
        if fallaron:
            nota += ["", "No se pudieron incluir:"] + [f"  - {x}" for x in fallaron]
        z.writestr("LEAME.txt", "\r\n".join(nota))

    registrar("inspeccion_paquete", "inspeccion", detalle=f"mes={texto_mes} partes={','.join(sorted(elegidas))} "
                                                         f"archivos={hechos} fallaron={len(fallaron)}")
    memoria.seek(0)
    return send_file(memoria, mimetype="application/zip", as_attachment=True,
                     download_name=f"Inspeccion_{texto_mes}.zip")
