"""
PRUEBAS DE LA VERSIÓN 1.1.20: avisos al celular por WhatsApp (CallMeBot), por
Telegram o por los dos (app/avisos.py).

NUNCA se conecta a internet: se reemplaza (mock) lo que habla con Telegram y con
CallMeBot y se revisa QUÉ se iba a mandar y por dónde.
"""
import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO
from test_version_1116 import HiloInmediato


class RespuestaFalsa(io.BytesIO):
    """Lo que devolvería urlopen (se puede usar con «with»)."""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BaseAvisos(BaseVentas):
    def setUp(self):
        super().setUp()
        self.config(telegram_token="123:ABC", telegram_chat_id="999", nombre_comercial="Fervifarma",
                    whatsapp_numero="+573001234567", whatsapp_apikey="555111")
        self.telegram = []          # mensajes que «salieron» por Telegram
        self.whatsapp = []          # direcciones que se «abrieron» en CallMeBot
        falso_tg = lambda texto, token, chat: (self.telegram.append(texto) or (True, ""))

        def falso_urlopen(req, timeout=None):
            self.whatsapp.append(req.full_url)
            return RespuestaFalsa(b"<p>Message queued. You will receive it in a few seconds.</p>")
        for p in (mock.patch("app.telegram.enviar_ahora", side_effect=falso_tg),
                  mock.patch("app.avisos.urllib.request.urlopen", side_effect=falso_urlopen),
                  mock.patch("app.avisos.threading.Thread", HiloInmediato)):
            p.start()
            self.addCleanup(p.stop)

    def config(self, **valores):
        con = self.db()
        for k, v in valores.items():
            con.execute("INSERT INTO config (clave, valor) VALUES (?, ?) "
                        "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor", (k, v))
        con.commit()
        con.close()

    def cerrar_caja(self):
        self.lote(1, "A1", FUTURO, 50)
        self.abrir_caja()
        datos = {"carrito": json.dumps([{"producto_id": 1, "cantidad": 2}]), "forma_pago": "efectivo",
                 "monto_recibido": "100000"}
        self.post(self.c, "/pos/api/cobrar", datos)
        return self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "12000"}).get_json()


class TestCanales(BaseAvisos):
    def test_solo_telegram_por_defecto(self):
        """Quien ya tenía Telegram (1.1.16) sigue igual: WhatsApp viene apagado."""
        self.assertTrue(self.cerrar_caja()["ok"])
        self.assertEqual(len(self.telegram), 1)
        self.assertEqual(self.whatsapp, [])

    def test_los_dos(self):
        self.config(aviso_whatsapp="si")
        self.cerrar_caja()
        self.assertEqual(len(self.telegram), 1)
        self.assertEqual(len(self.whatsapp), 1)
        url = self.whatsapp[0]
        self.assertIn("api.callmebot.com/whatsapp.php", url)
        self.assertIn("phone=%2B573001234567", url)
        self.assertIn("apikey=555111", url)
        self.assertIn("%2AFervifarma", url)          # *negrita* de WhatsApp (no <b> de Telegram)
        self.assertNotIn("%3Cb%3E", url)

    def test_solo_whatsapp(self):
        self.config(aviso_whatsapp="si", aviso_telegram="no")
        self.cerrar_caja()
        self.assertEqual(self.telegram, [])
        self.assertEqual(len(self.whatsapp), 1)

    def test_whatsapp_sin_clave_no_se_usa(self):
        self.config(aviso_whatsapp="si", aviso_telegram="no", whatsapp_apikey="")
        self.cerrar_caja()
        self.assertEqual(self.whatsapp, [])

    def test_si_whatsapp_falla_telegram_llega_y_la_caja_cierra(self):
        self.config(aviso_whatsapp="si")
        with mock.patch("app.avisos.urllib.request.urlopen", side_effect=OSError("sin internet")):
            self.assertTrue(self.cerrar_caja()["ok"])
        self.assertEqual(len(self.telegram), 1)

    def test_temperatura_por_whatsapp(self):
        self.config(aviso_whatsapp="si", aviso_telegram="no")
        con = self.db()
        con.execute("UPDATE zonas_temperatura SET temp_min = 15, temp_max = 30, controla_humedad = 0 WHERE nombre = 'Ambiente'")
        con.commit()
        con.close()
        zona = self.uno("SELECT id FROM zonas_temperatura WHERE nombre = 'Ambiente'")["id"]
        self.post(self.c, f"/temperaturas/api/registrar/{zona}", {"temperatura": "33", "accion_correctiva": "Ventilador"})
        self.assertEqual(len(self.whatsapp), 1)
        self.assertIn("Ambiente", self.whatsapp[0])


class TestFormatos(BaseAvisos):
    def test_numero(self):
        from app.avisos import numero_whatsapp
        self.assertEqual(numero_whatsapp("300 123 4567"), "+573001234567")
        self.assertEqual(numero_whatsapp("+57 300-123-4567"), "+573001234567")
        self.assertEqual(numero_whatsapp(""), "")

    def test_texto_de_telegram_a_whatsapp(self):
        from app.avisos import a_whatsapp
        self.assertEqual(a_whatsapp("<b>Caja #3</b> &amp; más"), "*Caja #3* & más")

    def test_clave_mala(self):
        from app.avisos import whatsapp_enviar_ahora
        error = urllib.error.HTTPError("u", 400, "x", {}, io.BytesIO(b"<p>APIKey is invalid</p>"))
        with mock.patch("app.avisos.urllib.request.urlopen", side_effect=error):
            ok, porque = whatsapp_enviar_ahora("hola", "3001234567", "1")
        self.assertFalse(ok)
        self.assertIn("clave", porque)


class TestConfiguracion(BaseAvisos):
    def test_pantalla(self):
        html = self.c.get("/configuracion/").get_data(as_text=True)
        for t in ("¿Por dónde avisar?", 'name="aviso_whatsapp"', "I allow callmebot to send me messages",
                  "Mandar prueba por WhatsApp", "Mandar prueba por Telegram"):
            self.assertIn(t, html)

    def test_guardar_canales(self):
        datos = {"razon_social": "X", "nit": "1", "telegram_token": "123:ABC", "telegram_chat_id": "999",
                 "aviso_whatsapp": "si", "whatsapp_numero": "310 555 1234", "whatsapp_apikey": " 777 ",
                 "telegram_cierre_caja": "si"}
        self.post(self.c, "/configuracion/", datos)
        valor = lambda k: self.uno(f"SELECT valor FROM config WHERE clave = '{k}'")["valor"]
        self.assertEqual(valor("aviso_telegram"), "no")           # no se marcó
        self.assertEqual(valor("aviso_whatsapp"), "si")
        self.assertEqual(valor("whatsapp_numero"), "+573105551234")
        self.assertEqual(valor("whatsapp_apikey"), "777")

    def test_mandar_prueba_whatsapp(self):
        r = self.post(self.c, "/configuracion/whatsapp/probar",
                      {"whatsapp_numero": "3009998877", "whatsapp_apikey": "4242"}, follow_redirects=True)
        self.assertIn("Mensaje de prueba enviado", r.get_data(as_text=True))
        self.assertIn("phone=%2B573009998877", self.whatsapp[0])
        self.assertIn("funcionando", self.whatsapp[0])
        # Si sale bien, deja guardados el número y la clave
        self.assertEqual(self.uno("SELECT valor FROM config WHERE clave = 'whatsapp_apikey'")["valor"], "4242")
