import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app import auth  # noqa: E402
from app.backup_utils import hacer_respaldo, hacer_respaldo_si_toca, listar_respaldos  # noqa: E402

TOKEN = "token-de-prueba"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "prueba.db")
        self.backups = os.path.join(self.tmp, "respaldos")
        self.app = create_app(
            {"TESTING": True, "SECRET_KEY": "x", "DB_PATH": self.db_path, "BACKUP_DIR": self.backups, "BACKUP_KEEP": 3}
        )
        auth.reiniciar_limites()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cliente(self):
        c = self.app.test_client()
        with c.session_transaction() as s:
            s["_csrf"] = TOKEN
        return c

    def post(self, c, url, datos=None, **kw):
        datos = dict(datos or {})
        datos["_csrf"] = TOKEN
        return c.post(url, data=datos, **kw)

    def crear_admin(self, c):
        return self.post(c, "/configurar", {"nombre": "Fernando", "usuario": "admin", "clave": "clave1234", "confirmar": "clave1234"})

    def entrar(self, c, usuario="admin", clave="clave1234"):
        r = self.post(c, "/login", {"usuario": usuario, "clave": clave})
        with c.session_transaction() as s:
            s["_csrf"] = TOKEN
        return r

    def admin_logueado(self):
        c = self.cliente()
        self.crear_admin(c)
        self.entrar(c)
        return c

    def crear_usuario(self, c, usuario, rol, clave="clave1234"):
        return self.post(c, "/admin/usuarios/nuevo", {"nombre": usuario.title(), "usuario": usuario, "rol": rol, "clave": clave, "confirmar": clave})


class TestArranque(Base):
    def test_sin_usuarios_redirige_a_configurar(self):
        c = self.cliente()
        r = c.get("/", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Configuración inicial", r.get_data(as_text=True))
        self.assertEqual(c.get("/login").status_code, 302)
        self.assertEqual(c.get("/configurar").status_code, 200)

    def test_configurar_solo_una_vez(self):
        c = self.cliente()
        self.assertEqual(self.crear_admin(c).status_code, 302)
        self.assertEqual(c.get("/configurar").status_code, 302)  # ya no se puede usar
        r = self.post(c, "/configurar", {"nombre": "X", "usuario": "otro", "clave": "clave1234", "confirmar": "clave1234"})
        self.assertEqual(r.status_code, 302)
        con = sqlite3.connect(self.db_path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 1)

    def test_clave_corta_o_distinta_se_rechaza(self):
        c = self.cliente()
        r = self.post(c, "/configurar", {"nombre": "F", "usuario": "admin", "clave": "corta", "confirmar": "corta"}, follow_redirects=True)
        self.assertIn("al menos 8", r.get_data(as_text=True))
        r = self.post(c, "/configurar", {"nombre": "F", "usuario": "admin", "clave": "clave1234", "confirmar": "otra12345"}, follow_redirects=True)
        self.assertIn("no coinciden", r.get_data(as_text=True))

    def test_migraciones_son_idempotentes(self):
        from app.db import init_db
        self.assertEqual(init_db(self.db_path), 1)
        self.assertEqual(init_db(self.db_path), 1)


class TestSesion(Base):
    def test_login_correcto_e_incorrecto(self):
        c = self.cliente()
        self.crear_admin(c)
        r = self.post(c, "/login", {"usuario": "admin", "clave": "mala"}, follow_redirects=True)
        self.assertIn("incorrectos", r.get_data(as_text=True))
        r = self.entrar(c)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/").status_code, 200)

    def test_usuario_no_distingue_mayusculas(self):
        c = self.cliente()
        self.crear_admin(c)
        r = self.entrar(c, usuario="ADMIN")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/").status_code, 200)

    def test_pagina_protegida_sin_login(self):
        c = self.cliente()
        self.crear_admin(c)
        r = c.get("/admin/usuarios")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_logout(self):
        c = self.admin_logueado()
        self.post(c, "/logout")
        self.assertEqual(c.get("/admin/usuarios").status_code, 302)

    def test_bloqueo_por_intentos_fallidos(self):
        c = self.cliente()
        self.crear_admin(c)
        for _ in range(5):
            self.post(c, "/login", {"usuario": "admin", "clave": "mala"})
        r = self.post(c, "/login", {"usuario": "admin", "clave": "clave1234"}, follow_redirects=True)
        self.assertIn("Demasiados intentos", r.get_data(as_text=True))
        self.assertEqual(c.get("/").status_code, 302)  # ni con la clave correcta

    def test_redireccion_next_solo_rutas_locales(self):
        c = self.cliente()
        self.crear_admin(c)
        r = c.post("/login?next=https://malo.example.com", data={"usuario": "admin", "clave": "clave1234", "_csrf": TOKEN})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("malo.example.com", r.headers["Location"])
        self.assertFalse(auth.es_ruta_segura("//malo.example.com"))
        self.assertTrue(auth.es_ruta_segura("/admin/bitacora"))

    def test_csrf_obligatorio(self):
        c = self.app.test_client()
        r = c.post("/configurar", data={"nombre": "F", "usuario": "admin", "clave": "clave1234", "confirmar": "clave1234"})
        self.assertEqual(r.status_code, 400)

    def test_usuario_desactivado_pierde_acceso_inmediato(self):
        admin = self.admin_logueado()
        self.crear_usuario(admin, "ana", "auxiliar")
        ana = self.cliente()
        self.entrar(ana, "ana")
        self.assertEqual(ana.get("/").status_code, 200)
        con = sqlite3.connect(self.db_path)
        uid = con.execute("SELECT id FROM usuarios WHERE usuario='ana'").fetchone()[0]
        self.post(admin, f"/admin/usuarios/{uid}/estado")
        self.assertEqual(ana.get("/").status_code, 302)
        r = self.entrar(self.cliente(), "ana")
        self.assertEqual(r.status_code, 200)  # vuelve al formulario con error


class TestRoles(Base):
    def test_permisos_por_rol(self):
        admin = self.admin_logueado()
        self.crear_usuario(admin, "ana", "auxiliar")
        self.crear_usuario(admin, "dtecnico", "director_tecnico")
        aux, dt = self.cliente(), self.cliente()
        self.entrar(aux, "ana")
        self.entrar(dt, "dtecnico")
        self.assertEqual(aux.get("/admin/usuarios").status_code, 403)
        self.assertEqual(aux.get("/admin/bitacora").status_code, 403)
        self.assertEqual(aux.get("/admin/respaldos").status_code, 403)
        self.assertEqual(dt.get("/admin/usuarios").status_code, 403)
        self.assertEqual(dt.get("/admin/respaldos").status_code, 403)
        self.assertEqual(dt.get("/admin/bitacora").status_code, 200)
        self.assertEqual(admin.get("/admin/usuarios").status_code, 200)
        self.assertEqual(admin.get("/admin/respaldos").status_code, 200)

    def test_usuario_repetido_y_rol_invalido(self):
        admin = self.admin_logueado()
        self.crear_usuario(admin, "ana", "auxiliar")
        r = self.crear_usuario(admin, "ANA", "auxiliar")
        self.assertIn("Ya existe", r.get_data(as_text=True))
        r = self.crear_usuario(admin, "luis", "superjefe")
        self.assertIn("rol válido", r.get_data(as_text=True))

    def test_no_se_puede_dejar_sin_administradores(self):
        admin = self.admin_logueado()
        con = sqlite3.connect(self.db_path)
        uid = con.execute("SELECT id FROM usuarios WHERE usuario='admin'").fetchone()[0]
        r = self.post(admin, f"/admin/usuarios/{uid}/estado", follow_redirects=True)
        self.assertIn("propio usuario", r.get_data(as_text=True))
        # segundo administrador puede desactivar al primero, pero no al último
        self.crear_usuario(admin, "jefe2", "administrador")
        jefe2 = self.cliente()
        self.entrar(jefe2, "jefe2")
        r = self.post(jefe2, f"/admin/usuarios/{uid}/estado", follow_redirects=True)
        self.assertIn("desactivado", r.get_data(as_text=True))
        uid2 = con.execute("SELECT id FROM usuarios WHERE usuario='jefe2'").fetchone()[0]
        r = self.post(jefe2, f"/admin/usuarios/{uid2}/estado", follow_redirects=True)
        self.assertIn("propio usuario", r.get_data(as_text=True))

    def test_cambiar_clave_propia_y_restablecer_ajena(self):
        admin = self.admin_logueado()
        self.crear_usuario(admin, "ana", "auxiliar")
        ana = self.cliente()
        self.entrar(ana, "ana")
        r = self.post(ana, "/cuenta", {"actual": "equivocada", "nueva": "nueva12345", "confirmar": "nueva12345"}, follow_redirects=True)
        self.assertIn("no es correcta", r.get_data(as_text=True))
        self.post(ana, "/cuenta", {"actual": "clave1234", "nueva": "nueva12345", "confirmar": "nueva12345"})
        self.post(ana, "/logout")
        r = self.entrar(self.cliente(), "ana", "nueva12345")
        self.assertEqual(r.status_code, 302)
        con = sqlite3.connect(self.db_path)
        uid = con.execute("SELECT id FROM usuarios WHERE usuario='ana'").fetchone()[0]
        self.post(admin, f"/admin/usuarios/{uid}/clave", {"nueva": "otraclave99", "confirmar": "otraclave99"})
        r = self.entrar(self.cliente(), "ana", "otraclave99")
        self.assertEqual(r.status_code, 302)


class TestBitacora(Base):
    def test_se_registran_eventos(self):
        admin = self.admin_logueado()
        self.crear_usuario(admin, "ana", "auxiliar")
        self.post(self.cliente(), "/login", {"usuario": "admin", "clave": "mala"})
        con = sqlite3.connect(self.db_path)
        acciones = [f[0] for f in con.execute("SELECT accion FROM bitacora ORDER BY id")]
        for esperada in ("administrador_inicial_creado", "inicio_sesion", "usuario_creado", "inicio_sesion_fallido"):
            self.assertIn(esperada, acciones)
        r = admin.get("/admin/bitacora?q=ana")
        self.assertIn("usuario_creado", r.get_data(as_text=True))

    def test_bitacora_no_se_puede_editar_ni_borrar(self):
        self.admin_logueado()
        con = sqlite3.connect(self.db_path)
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("UPDATE bitacora SET accion = 'otra'")
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("DELETE FROM bitacora")
        self.assertGreater(con.execute("SELECT COUNT(*) FROM bitacora").fetchone()[0], 0)


class TestRespaldos(Base):
    def test_respaldo_verificado_y_limpieza(self):
        self.admin_logueado()
        import time
        for _ in range(5):
            destino, avisos = hacer_respaldo(self.db_path, self.backups, conservar=3)
            time.sleep(1.1)  # el nombre lleva segundos
        self.assertEqual(len(listar_respaldos(self.backups)), 3)
        con = sqlite3.connect(str(destino))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 1)
        self.assertEqual(avisos, [])

    def test_copia_adicional(self):
        self.admin_logueado()
        extra = os.path.join(self.tmp, "usb")
        destino, avisos = hacer_respaldo(self.db_path, self.backups, extra=extra)
        self.assertTrue(os.path.exists(os.path.join(extra, destino.name)))

    def test_respaldo_si_toca(self):
        self.admin_logueado()
        self.assertIsNotNone(hacer_respaldo_si_toca(self.db_path, self.backups))
        self.assertIsNone(hacer_respaldo_si_toca(self.db_path, self.backups))  # ya hay uno reciente

    def test_respaldo_manual_desde_la_pagina(self):
        admin = self.admin_logueado()
        r = self.post(admin, "/admin/respaldos", follow_redirects=True)
        self.assertIn("Respaldo creado", r.get_data(as_text=True))
        self.assertEqual(len(listar_respaldos(self.backups)), 1)


if __name__ == "__main__":
    unittest.main()
