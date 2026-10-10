"""Sistema de gestión de calidad y POS para droguería."""
import logging
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, render_template

import config

from . import db as base_datos
from .backup_utils import hacer_respaldo_si_toca

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
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        UPLOADS_DIR=str(config.UPLOADS_DIR),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _clave_secreta(config.SECRET_KEY_FILE)

    base_datos.init_db(app.config["DB_PATH"])
    base_datos.init_app(app)

    from . import (admin, auth, caja_menor, catalogos, configuracion,
                   contabilidad, conteos, equipos, importador, inventario, main, pos, productos,
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
    app.register_blueprint(pos.bp)
    app.register_blueprint(contabilidad.bp)
    app.register_blueprint(caja_menor.bp)
    app.register_blueprint(conteos.bp)   # toma de inventario (conteo físico)
    app.register_blueprint(equipos.bp)   # equipos y calibraciones

    app.jinja_env.filters["rol_nombre"] = lambda rol: auth.ROLES.get(rol, rol)

    @app.errorhandler(400)
    def error_400(_e):
        return render_template("error.html", codigo=400, mensaje="Solicitud no válida o sesión vencida. Vuelve a intentarlo."), 400

    @app.errorhandler(403)
    def error_403(_e):
        return render_template("error.html", codigo=403, mensaje="No tienes permiso para ver esta página."), 403

    @app.errorhandler(404)
    def error_404(_e):
        return render_template("error.html", codigo=404, mensaje="La página no existe."), 404

    @app.errorhandler(500)
    def error_500(_e):
        return render_template("error.html", codigo=500, mensaje="Ocurrió un error interno. Avisa al administrador."), 500

    if not app.config.get("TESTING"):
        try:
            nuevo = hacer_respaldo_si_toca(
                app.config["DB_PATH"], app.config["BACKUP_DIR"],
                app.config["BACKUP_EXTRA_DIR"], app.config["BACKUP_KEEP"]
            )
            if nuevo:
                log.info("Respaldo automático creado: %s", nuevo)
        except Exception:
            log.exception("No se pudo hacer el respaldo automático al iniciar")

    from .configuracion import obtener_config as _obtener_config

    @app.context_processor
    def _config_global():
        try:
            return {"config_negocio": _obtener_config()}
        except Exception:
            return {"config_negocio": {}}

    return app
