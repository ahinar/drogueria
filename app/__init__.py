"""Sistema de gestión de calidad y POS para droguería."""
import logging
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, render_template, send_from_directory

import config

from . import db as base_datos

log = logging.getLogger("drogueria")

def _clave_secreta(ruta: Path) -> str:
    """Genera una clave secreta al primer arranque y la reutiliza (mantiene las sesiones)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        return ruta.read_text().strip()
    clave = secrets.token_hex(32)
    ruta.write_text(clave)
    return clave

def create_app(test_config=None):
    app = Flask(__name__, static_folder=str(config.STATIC_DIR), static_url_path="/static")
    app.config.update(
        DB_PATH=str(config.DB_PATH),
        BACKUP_DIR=str(config.BACKUP_DIR),
        BACKUP_EXTRA_DIR=config.BACKUP_EXTRA_DIR,
        BACKUP_KEEP=config.BACKUP_KEEP,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=config.SESSION_HORAS),
        # Tamaño máximo de lo que se sube. Alto porque el archivo de productos con
        # fotos puede pesar mucho; cada foto igual se revisa aparte (utils_imagenes.py).
        MAX_CONTENT_LENGTH=300 * 1024 * 1024,
        UPLOADS_DIR=str(config.UPLOADS_DIR),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _clave_secreta(config.SECRET_KEY_FILE)

    base_datos.init_db(app.config["DB_PATH"])
    base_datos.init_app(app)

    # Versión 1.1.6: las cajas cerradas ANTES de esta versión también dejan su
    # sobrante/faltante en la contabilidad (una sola vez cada una). Ver app/cajas.py
    try:
        from .cajas import registrar_pendientes
        conexion = base_datos.conectar(app.config["DB_PATH"])
        try:
            registrar_pendientes(conexion)
        finally:
            conexion.close()
    except Exception:                                # noqa: BLE001 (nunca debe impedir que abra el programa)
        import logging
        logging.exception("No se pudieron registrar las diferencias de caja pendientes")

    # Candado de red: solo entra quien viene de este PC, la red del local o
    # Tailscale; y se anota qué equipos están conectados. Ver app/equipo.py
    from . import equipo
    equipo.init_app(app)

    from . import (admin, apariencia, auth, caja_menor, cartera, catalogos, configuracion,
                   contabilidad, conteos, devoluciones, equipos, importador, inventario, main,
                   otros_ingresos, pos, productos,
                   proveedores, recepciones, reportes, temperaturas, unidades)

    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(productos.bp)
    app.register_blueprint(proveedores.bp)
    app.register_blueprint(temperaturas.bp)
    app.register_blueprint(configuracion.bp)
    app.register_blueprint(reportes.bp)
    app.register_blueprint(catalogos.bp)
    app.register_blueprint(unidades.bp)
    app.register_blueprint(recepciones.bp)
    app.register_blueprint(inventario.bp)
    app.register_blueprint(importador.bp)
    # Cotizaciones (se arman en el POS): ver app/cotizaciones.py
    from . import cotizaciones
    app.register_blueprint(cotizaciones.bp)
    app.register_blueprint(pos.bp)
    app.register_blueprint(contabilidad.bp)
    app.register_blueprint(caja_menor.bp)
    app.register_blueprint(conteos.bp)   # toma de inventario (conteo físico)
    app.register_blueprint(equipos.bp)   # equipos y calibraciones
    app.register_blueprint(devoluciones.bp)   # devoluciones de cliente y a proveedor
    app.register_blueprint(apariencia.bp)     # tema (colores) de cada usuario
    app.register_blueprint(otros_ingresos.bp) # plata que entra y no es venta
    app.register_blueprint(cartera.bp)        # ventas a crédito y abonos (cuentas por cobrar)
    # Versión 1.1.7: Bancos (Nequi y Davivienda) y Cuentas por pagar a proveedores
    from . import bancos, cuentas_pagar
    app.register_blueprint(bancos.bp)
    app.register_blueprint(cuentas_pagar.bp)
    # Fase 4 (calidad): gestión documental. Ver app/documentos.py
    from . import documentos
    app.register_blueprint(documentos.bp)
    # Fase 4.2: saneamiento (limpieza, plagas, residuos). Ver app/saneamiento.py
    from . import saneamiento
    app.register_blueprint(saneamiento.bp)
    # Fase 4.3: capacitaciones y personal. Ver app/capacitaciones.py
    from . import capacitaciones
    app.register_blueprint(capacitaciones.bp)
    # Fase 4.4 y 4.5: quejas (PQRS) y farmacovigilancia. Ver app/pqrs.py y app/farmacovigilancia.py
    from . import farmacovigilancia, pqrs
    app.register_blueprint(pqrs.bp)
    app.register_blueprint(farmacovigilancia.bp)
    # Versión 1.1.2: instalar el programa como aplicación desde Chrome. Ver app/instalable.py
    from . import instalable
    app.register_blueprint(instalable.bp)
    # Versión 1.1.13: ventas rápidas (fotocopias, dulcería...). Ver app/ventas_rapidas.py
    from . import ventas_rapidas
    app.register_blueprint(ventas_rapidas.bp)
    # Versión 1.1.14: pantalla Ventas (buscar, ver el carrito al lado, devolver, corregir el pago)
    from . import ventas
    app.register_blueprint(ventas.bp)

    app.jinja_env.filters["rol_nombre"] = lambda rol: auth.ROLES.get(rol, rol)
    # {{ 12345 | pesos }} → "$12.345" (formato colombiano, ver app/formato.py)
    from .formato import pesos as _pesos
    app.jinja_env.filters["pesos"] = _pesos
    # Versión 1.1.14: las formas de pago y cuentas (con Daviplata) para todas las pantallas:
    #   {% for f in formas_pago.FORMAS_MOVIMIENTO %}<option value="{{ f }}">{{ formas_pago.nombre(f) }}</option>{% endfor %}
    from . import formas_pago as _formas_pago
    app.jinja_env.globals["formas_pago"] = _formas_pago
    # {{ "2026-10-10 07:15:00" | fecha_hora }} → "10/10/2026 07:15"
    app.jinja_env.filters["fecha_hora"] = lambda t: (
        f"{t[8:10]}/{t[5:7]}/{t[0:4]}" + (f" {t[11:16]}" if len(t or "") >= 16 else "")
    ) if t and len(t) >= 10 else (t or "")

    # ---- Archivos que sube la droguería (fotos, certificados, actas...) ----
    # Se guardan en la carpeta de DATOS (config.UPLOADS_DIR) y se sirven en la
    # misma dirección de siempre (/static/uploads/...), así las páginas no cambian.
    # Esta regla es más específica que la de /static/..., por eso gana.
    @app.route("/static/uploads/<path:archivo>")
    def archivos_subidos(archivo):
        return send_from_directory(app.config["UPLOADS_DIR"], archivo)

    # ---- "¿Estás prendido?" ----
    # La usa el lanzador del programa instalado (escritorio.py) para saber si
    # el programa ya está corriendo y no abrir dos veces.
    from .version import VERSION

    @app.route("/salud")
    def salud():
        return f"fervifarma {VERSION}", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.context_processor
    def _version_global():
        return {"version_programa": VERSION}

    # ---- Versión 1.1.11: las pantallas que piden datos por detrás (/api/...) reciben
    # SIEMPRE una respuesta en JSON, también cuando hay un error. Antes recibían una
    # página web de error y el POS mostraba "Unexpected token '<' ... is not valid JSON"
    # (pasó al cobrar con la sesión cerrada). Ahora el POS muestra el mensaje claro.
    from .auth import es_pedido_api, respuesta_api_error

    @app.errorhandler(400)
    def error_400(_e):
        if es_pedido_api():
            return respuesta_api_error(
                "La sesión se renovó o se venció (por ejemplo, se volvió a entrar en otra ventana). "
                "Recarga la página con F5 y vuelve a intentarlo: esto NO se guardó.", 400, sesion=True)
        return render_template("error.html", codigo=400, mensaje="Solicitud no válida o sesión vencida. Vuelve a intentarlo."), 400

    @app.errorhandler(403)
    def error_403(_e):
        if es_pedido_api():
            return respuesta_api_error("Tu usuario no tiene permiso para hacer esto.", 403)
        return render_template("error.html", codigo=403, mensaje="No tienes permiso para ver esta página."), 403

    @app.errorhandler(404)
    def error_404(_e):
        if es_pedido_api():
            return respuesta_api_error("Eso ya no existe (quizá se borró). Recarga la página con F5.", 404)
        return render_template("error.html", codigo=404, mensaje="La página no existe."), 404

    # ---- Base de datos ocupada ("database is locked") ----
    # Pasa si otra tarea larga está escribiendo (por ejemplo una importación grande)
    # y no termina en 15 segundos. En vez del "error 500" se explica qué hacer.
    import sqlite3 as _sqlite3

    @app.errorhandler(_sqlite3.OperationalError)
    def base_ocupada(error):
        from flask import jsonify, request
        if "locked" not in str(error).lower():
            log.exception("Error de base de datos")
            return error_500(error)
        log.warning("Base de datos ocupada en %s %s", request.method, request.path)
        mensaje = ("El programa está ocupado terminando otra tarea (por ejemplo una importación). "
                   "Espera un momento y vuelve a intentarlo: no se guardó nada de esta operación.")
        if "/api/" in request.path:
            return jsonify({"ok": False, "error": mensaje}), 503
        return render_template("error.html", codigo=503, mensaje=mensaje), 503

    @app.errorhandler(500)
    def error_500(_e):
        from flask import request
        # Queda escrito en el archivo de errores (fervifarma.log) con la página donde pasó
        log.error("Error interno en %s %s: %r", request.method, request.path,
                  getattr(_e, "original_exception", _e))
        if es_pedido_api():
            return respuesta_api_error(
                "Ocurrió un error interno y no se pudo terminar. Antes de volver a intentarlo, revisa si quedó "
                "guardado (por ejemplo, en las ventas del turno). El detalle quedó en el archivo de errores.", 500)
        return render_template("error.html", codigo=500, mensaje="Ocurrió un error interno. Avisa al administrador."), 500

    # Los respaldos automáticos los hace el "reloj de respaldos" (backup_utils.py),
    # que arrancan run.py y escritorio.py: uno al abrir y luego cada 24 horas.

    from .configuracion import obtener_config as _obtener_config

    @app.context_processor
    def _config_global():
        try:
            return {"config_negocio": _obtener_config()}
        except Exception:
            return {"config_negocio": {}}

    @app.context_processor
    def _apariencia_global():
        """Tema del usuario y caja abierta: los usa la barra superior de base.html."""
        from flask import g as _g
        usuario = _g.get("user")
        return {"tema_actual": apariencia.tema_de(usuario),
                "caja_barra": apariencia.caja_abierta_actual() if usuario else None}

    return app
