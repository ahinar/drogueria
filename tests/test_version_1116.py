"""
PRUEBAS DE LA VERSIÓN 1.1.16
============================
  - TestTelegram: alertas al celular. NUNCA se conecta a internet: se reemplaza
    (mock) la función que habla con Telegram y se revisa QUÉ se iba a mandar.
      · mini resumen al cerrar la caja (ventas por forma de pago, diferencia, gastos)
      · aviso de temperatura fuera de rango
      · si está apagado o sin configurar, no manda nada
      · si Telegram falla, la caja se cierra igual
      · botones de Configuración: «Buscar mi chat» y «Mandar prueba»
  - TestInspeccion: el paquete .zip para la visita de la Secretaría de Salud.
  - TestFotoCodigo: buscar la foto del producto por código de barras (sin internet:
    se reemplaza la descarga por respuestas de mentiras).

Recordatorio (BaseVentas): producto 1 = $1.000 sin IVA; la caja se abre con $10.000.
"""
import io
import json
import sys
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO


class HiloInmediato:
    """Reemplaza threading.Thread: corre la tarea de una vez (así la prueba no tiene que esperar)."""

    def __init__(self, target=None, **_):
        self.target = target

    def start(self):
        self.target()


class BaseTelegram(BaseVentas):
    def setUp(self):
        super().setUp()
        self.config(telegram_token="123:ABC", telegram_chat_id="999", nombre_comercial="Fervifarma")
        self.enviados = []                 # aquí quedan los mensajes que «se mandaron»
        falso = lambda texto, token, chat: (self.enviados.append(texto) or (True, ""))
        for p in (mock.patch("app.telegram.enviar_ahora", side_effect=falso),
                  mock.patch("app.telegram.threading.Thread", HiloInmediato)):
            p.start()
            self.addCleanup(p.stop)

    def config(self, **valores):
        con = self.db()
        for k, v in valores.items():
            con.execute("INSERT INTO config (clave, valor) VALUES (?, ?) "
                        "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor", (k, v))
        con.commit()
        con.close()

    def vender(self, forma="efectivo", cantidad=1):
        datos = {"carrito": json.dumps([{"producto_id": 1, "cantidad": cantidad}]), "forma_pago": forma,
                 "monto_recibido": "100000" if forma == "efectivo" else ""}
        self.assertTrue(self.post(self.c, "/pos/api/cobrar", datos).get_json()["ok"])


class TestTelegramCierre(BaseTelegram):
    def setUp(self):
        super().setUp()
        self.lote(1, "A1", FUTURO, 50)
        self.abrir_caja()

    def test_mini_resumen_al_cerrar(self):
        self.vender("efectivo", 3)            # $3.000 en efectivo
        self.vender("daviplata", 2)           # $2.000 por Daviplata
        # Esperado en el cajón: 10.000 + 3.000 = 13.000. Se cuentan 12.500 → faltan $500
        j = self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "12500"}).get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(len(self.enviados), 1)
        m = self.enviados[0]
        self.assertIn("cerrada", m)
        self.assertIn("Fervifarma", m)
        self.assertIn("$5.000", m)            # total vendido
        self.assertIn("(2 ventas)", m)
        self.assertIn("Daviplata: $2.000", m)
        self.assertIn("faltaron $500", m)
        self.assertNotIn("Gastos del turno", m)   # el «Faltante de caja» automático no es un gasto del turno

    def test_caja_que_cuadra(self):
        self.vender("efectivo", 1)
        self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "11000"})
        self.assertIn("cuadró", self.enviados[0])

    def test_apagado_no_manda(self):
        self.config(telegram_cierre_caja="no")
        self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "10000"})
        self.assertEqual(self.enviados, [])

    def test_sin_configurar_no_manda(self):
        self.config(telegram_token="")
        self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "10000"})
        self.assertEqual(self.enviados, [])

    def test_si_telegram_falla_la_caja_se_cierra_igual(self):
        with mock.patch("app.telegram.mensaje_cierre_caja", side_effect=RuntimeError("sin internet")):
            j = self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "10000"}).get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(self.uno("SELECT estado FROM cajas ORDER BY id DESC LIMIT 1")["estado"], "cerrada")


class TestTelegramTemperatura(BaseTelegram):
    def setUp(self):
        super().setUp()
        con = self.db()
        con.execute("UPDATE zonas_temperatura SET temp_min = 15, temp_max = 30, controla_humedad = 0 "
                    "WHERE nombre = 'Ambiente'")
        con.commit()
        con.close()
        self.zona = self.uno("SELECT id FROM zonas_temperatura WHERE nombre = 'Ambiente'")["id"]

    def registrar(self, **datos):
        return self.post(self.c, f"/temperaturas/api/registrar/{self.zona}", datos).get_json()

    def test_fuera_de_rango_avisa(self):
        j = self.registrar(temperatura="32,5", accion_correctiva="Se prendió el ventilador")
        self.assertTrue(j["ok"], j)
        self.assertEqual(len(self.enviados), 1)
        self.assertIn("Ambiente", self.enviados[0])
        self.assertIn("32,5 °C", self.enviados[0])
        self.assertIn("ventilador", self.enviados[0])

    def test_en_rango_no_avisa(self):
        self.assertTrue(self.registrar(temperatura="22")["ok"])
        self.assertEqual(self.enviados, [])


class TestTelegramConfiguracion(BaseTelegram):
    def test_pantalla_tiene_la_seccion(self):
        html = self.c.get("/configuracion/").get_data(as_text=True)
        self.assertIn("Alertas al celular", html)
        self.assertIn("BotFather", html)
        self.assertIn('value="123:ABC"', html)

    def test_buscar_chat_lo_guarda(self):
        respuesta = {"ok": True, "result": [{"message": {"chat": {"id": 555, "first_name": "Fernando"}}}]}
        with mock.patch("app.telegram._llamar", return_value=respuesta):
            r = self.post(self.c, "/configuracion/telegram/buscar-chat", {"telegram_token": " 777:XYZ "},
                          follow_redirects=True)
        self.assertIn("Fernando", r.get_data(as_text=True))
        self.assertEqual(self.uno("SELECT valor FROM config WHERE clave = 'telegram_chat_id'")["valor"], "555")
        self.assertEqual(self.uno("SELECT valor FROM config WHERE clave = 'telegram_token'")["valor"], "777:XYZ")

    def test_buscar_chat_sin_mensajes(self):
        with mock.patch("app.telegram._llamar", return_value={"ok": True, "result": []}):
            r = self.post(self.c, "/configuracion/telegram/buscar-chat", {"telegram_token": "777:XYZ"},
                          follow_redirects=True)
        self.assertIn("escríbale cualquier cosa", r.get_data(as_text=True))

    def test_mandar_prueba(self):
        r = self.post(self.c, "/configuracion/telegram/probar", {"telegram_token": "123:ABC",
                                                                 "telegram_chat_id": "999"}, follow_redirects=True)
        self.assertIn("Mensaje de prueba enviado", r.get_data(as_text=True))
        self.assertIn("funcionando", self.enviados[0])

    def test_guardar_casillas(self):
        datos = {"razon_social": "X", "nit": "1", "telegram_token": "123:ABC", "telegram_chat_id": "999",
                 "telegram_temperatura": "si"}         # cierre de caja SIN marcar
        self.post(self.c, "/configuracion/", datos)
        self.assertEqual(self.uno("SELECT valor FROM config WHERE clave = 'telegram_cierre_caja'")["valor"], "no")
        self.assertEqual(self.uno("SELECT valor FROM config WHERE clave = 'telegram_temperatura'")["valor"], "si")

    def test_escapa_html(self):
        from app import telegram
        self.assertEqual(telegram.escapar("<b>&"), "&lt;b&gt;&amp;")


# =====================================================================
# MODO INSPECCIÓN: el paquete .zip con todo lo que pide la Secretaría
# =====================================================================


class TestInspeccion(BaseVentas):
    def test_pagina(self):
        html = self.c.get("/inspeccion/").get_data(as_text=True)
        self.assertIn("Modo inspección", html)
        self.assertIn("Descargar paquete", html)
        self.assertIn("lo pendiente", html)
        self.assertIn("/inspeccion/", self.c.get("/").get_data(as_text=True))   # está en el menú

    def zip_de(self, **datos):
        r = self.post(self.c, "/inspeccion/descargar", datos)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/zip")
        return zipfile.ZipFile(io.BytesIO(r.data))

    def test_paquete_completo(self):
        partes = ["temperaturas", "limpieza", "residuos", "vencimientos", "documentos", "capacitaciones", "certificados"]
        z = self.zip_de(mes="2026-10", partes=partes)
        nombres = z.namelist()
        self.assertIn("LEAME.txt", nombres)
        self.assertNotIn("No se pudieron incluir", z.read("LEAME.txt").decode())
        for esperado in ("Limpieza_2026-10.pdf", "Residuos_2026-10.pdf", "Listado_maestro_documentos.pdf",
                         "Plan_capacitaciones_2026.pdf", "Temperaturas_"):
            self.assertTrue(any(esperado in n for n in nombres), (esperado, nombres))
        for n in nombres:
            if n.endswith(".pdf"):
                self.assertTrue(z.read(n).startswith(b"%PDF"), n)

    def test_solo_una_parte(self):
        z = self.zip_de(mes="2026-09", partes=["limpieza"])
        self.assertEqual(sorted(z.namelist()), ["01_Limpieza_2026-09.pdf", "LEAME.txt"])

    def test_adjunta_certificado_de_fumigacion(self):
        import shutil
        import tempfile
        from app.utils_imagenes import ruta_de
        # Los archivos subidos van a una carpeta temporal (no a static/uploads del proyecto)
        carpeta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, carpeta, ignore_errors=True)
        self.app.config["UPLOADS_DIR"] = carpeta
        with self.app.app_context():
            fisico = ruta_de("uploads/saneamiento/cert_prueba.pdf")
        fisico.parent.mkdir(parents=True, exist_ok=True)
        fisico.write_bytes(b"%PDF-1.4 prueba")
        con = self.db()
        con.execute("INSERT INTO control_plagas (fecha, tipo, empresa, proxima, archivo, usuario_nombre, creado_en) "
                    "VALUES ('2026-10-01', 'integral', 'Fumigax', '2027-04-01', 'uploads/saneamiento/cert_prueba.pdf', "
                    "'x', '2026-10-01')")
        con.commit()
        con.close()
        z = self.zip_de(mes="2026-10", partes=["certificados"])
        self.assertIn("Certificados/Fumigacion_2026-10-01.pdf", z.namelist())

    def test_sin_marcar_nada(self):
        r = self.post(self.c, "/inspeccion/descargar", {"mes": "2026-10"}, follow_redirects=True)
        self.assertIn("Marca al menos una cosa", r.get_data(as_text=True))


# =====================================================================
# FOTO POR CÓDIGO DE BARRAS (sin internet: se reemplaza la descarga)
# =====================================================================


def _png_chiquito():
    """Una foto de verdad (1x1 píxel) para las pruebas."""
    from PIL import Image
    salida = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(salida, "PNG")
    return salida.getvalue()


class TestFotoCodigo(BaseVentas):
    def bajar_falso(self, respuestas):
        """respuestas: {parte de la dirección: bytes o Exception}."""
        def falso(url, maximo=None):
            for parte, valor in respuestas.items():
                if parte in url:
                    if isinstance(valor, Exception):
                        raise valor
                    return valor
            raise urllib.error.HTTPError(url, 404, "no", {}, None)
        return mock.patch("app.foto_codigo._bajar", side_effect=falso)

    def test_codigo_malo(self):
        from app.foto_codigo import buscar_foto
        self.assertFalse(buscar_foto("abc")["ok"])
        self.assertFalse(buscar_foto("123")["ok"])

    def test_encuentra_en_beauty_facts(self):
        ficha = json.dumps({"status": 1, "product": {"product_name": "Crema X",
                                                     "image_front_url": "https://img/crema.png"}}).encode()
        with self.bajar_falso({"openbeautyfacts": ficha, "img/crema": _png_chiquito()}):
            r = self.c.get("/productos/api/foto-codigo?codigo=7701234567890")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "image/png")
        self.assertEqual(r.headers["X-Fuente"], "Open%20Beauty%20Facts")
        self.assertIn("Crema", r.headers["X-Nombre"])

    def test_no_encontrado(self):
        with self.bajar_falso({}):                   # todas responden 404
            r = self.c.get("/productos/api/foto-codigo?codigo=7701234567890")
        self.assertEqual(r.status_code, 404)
        self.assertIn("medicamentos", r.get_json()["error"])

    def test_sin_internet(self):
        with self.bajar_falso({"open": OSError("sin red")}):
            r = self.c.get("/productos/api/foto-codigo?codigo=7701234567890")
        self.assertIn("internet", r.get_json()["error"])

    def test_boton_en_la_ficha(self):
        html = self.pagina_con_js(self.c, "/productos/1/editar")
        self.assertIn("btn-foto-codigo", html)
        self.assertIn("DataTransfer", html)
        # el «fetch envuelto» de pagina_inicio.js deja pasar las fotos (antes las volvía un error)
        self.assertIn("tipo.indexOf('image/') === 0", html)
