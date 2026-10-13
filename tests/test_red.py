"""
PRUEBAS DE "VARIOS COMPUTADORES" (versión 1.1.0):
  - el candado de red (app/equipo.py): entra este PC, la red del local y
    Tailscale; desde internet no se ve ni la página de entrada
  - equipo.json (config.py) y la dirección del PC principal (escritorio.py)
  - la página Administración → Red y equipos
  - la tirilla DIRECTA (app/tirilla_directa.py): los bytes ESC/POS, la
    impresión desde el POS (simulada: aquí no hay impresora) y la configuración
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import FUTURO, BaseVentas

from app import equipo


class TestCandadoDeRed(BaseVentas):
    def test_direcciones_permitidas(self):
        for ip in ("127.0.0.1", "192.168.1.20", "10.0.0.5", "172.20.1.1", "100.101.102.103",
                   "::1", "fd7a:115c:a1e0::1", "::ffff:192.168.1.20"):
            self.assertTrue(equipo.red_permitida(ip), ip)
        for ip in ("8.8.8.8", "181.50.20.1", "100.128.0.1", "2800:e2::1", "", None, "basura"):
            self.assertFalse(equipo.red_permitida(ip), ip)

    def test_tipo_de_red(self):
        self.assertEqual(equipo.tipo_de_red("100.90.1.2"), "Tailscale")
        self.assertEqual(equipo.tipo_de_red("192.168.0.9"), "Red del local")
        self.assertEqual(equipo.tipo_de_red("127.0.0.1"), "Este computador")

    def test_desde_internet_no_entra(self):
        r = self.cliente().get("/", environ_base={"REMOTE_ADDR": "181.50.20.1"})
        self.assertEqual(r.status_code, 403)
        for ip in ("100.90.1.2", "192.168.1.30"):
            r = self.cliente().get("/salud", environ_base={"REMOTE_ADDR": ip})
            self.assertEqual(r.status_code, 200, ip)

    def test_pagina_red_y_conectados(self):
        # El portátil (por Tailscale) abre una página: queda en la lista de conectados
        self.c.get("/", environ_base={"REMOTE_ADDR": "100.90.1.2"})
        r = self.c.get("/admin/red")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Red y equipos", html)
        self.assertIn("100.90.1.2", html)
        self.assertIn("Tailscale", html)


class TestEquipoJson(BaseVentas):
    def leer(self, contenido):
        import config
        carpeta = Path(tempfile.mkdtemp())
        archivo = carpeta / "equipo.json"
        if contenido is not None:
            archivo.write_text(contenido, encoding="utf-8")
        with mock.patch.object(config, "EQUIPO_FILE", archivo):
            return config.leer_equipo()

    def test_sin_archivo_es_principal_sin_compartir(self):
        self.assertEqual(self.leer(None), {"modo": "principal", "compartir": False, "servidor": ""})
        self.assertEqual(self.leer("{dañado"), {"modo": "principal", "compartir": False, "servidor": ""})

    def test_modos(self):
        self.assertTrue(self.leer('{"modo": "principal", "compartir": true}')["compartir"])
        e = self.leer(json.dumps({"modo": "conectado", "servidor": " mostrador "}))
        self.assertEqual((e["modo"], e["compartir"], e["servidor"]), ("conectado", False, "mostrador"))
        # Con BOM (algunos editores de Windows lo ponen)
        self.assertEqual(self.leer('﻿{"modo": "conectado", "servidor": "x"}')["modo"], "conectado")

    def test_direccion_del_principal(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from escritorio import url_del_principal
        con = {"modo": "conectado"}
        self.assertEqual(url_del_principal({**con, "servidor": "mostrador"}, 8765), "http://mostrador:8765")
        self.assertEqual(url_del_principal({**con, "servidor": "100.90.1.2"}, 8765), "http://100.90.1.2:8765")
        self.assertEqual(url_del_principal({**con, "servidor": "http://pc:9000/"}, 8765), "http://pc:9000")
        self.assertIsNone(url_del_principal({"modo": "principal", "servidor": "x"}, 8765))
        self.assertIsNone(url_del_principal({**con, "servidor": ""}, 8765))


class TestTirillaDirecta(BaseVentas):
    def vender(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        return self.cobrar([{"producto_id": 1, "cantidad": 3}], recibido="5000").get_json()

    def configurar(self, **extra):
        datos = {"razon_social": "Droguería Fervifarma SAS", "nit": "900123", "nombre_comercial": "Fervifarma",
                 "ancho_tirilla": "58", "impresora_tirillas": "POS-58"}
        datos.update(extra)
        self.post(self.c, "/configuracion/", datos)

    def test_partir_renglones(self):
        from app.tirilla_directa import partir
        self.assertEqual(partir("Acetaminofén 500 mg tabletas recubiertas", 16),
                         ["Acetaminofén 500", "mg tabletas", "recubiertas"])
        self.assertEqual(partir("x" * 20, 8), ["x" * 8, "x" * 8, "xxxx"])

    def test_bytes_de_la_venta(self):
        self.configurar()
        venta = self.vender()
        enviados = {}

        def falso_enviar(impresora, datos, titulo):
            enviados.update(impresora=impresora, datos=datos, titulo=titulo)
            return True, ""

        with mock.patch("app.cajon.enviar_crudo", side_effect=falso_enviar):
            r = self.post(self.c, "/pos/api/imprimir-tirilla", {"venta_id": str(venta["venta_id"])})
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(enviados["impresora"], "POS-58")
        datos = enviados["datos"]
        self.assertTrue(datos.startswith(b"\x1b@\x1bt\x02"))          # iniciar + tabla PC850 (con tildes)
        self.assertTrue(datos.endswith(b"\x1dVB\x03"))                 # cortar papel
        texto = datos.decode("cp850")
        self.assertIn("V-0001", texto)
        self.assertIn("$3.000", texto)
        self.assertIn("Atendió", texto)                                # con tilde
        # Ningún renglón pasa de 32 letras (papel de 58 mm), sin contar las órdenes ESC/POS
        import re
        limpio = re.sub(r"\x1b[@]|\x1b[taE].|\x1d!.|\x1dVB.", "", texto, flags=re.S)
        self.assertTrue(all(len(r) <= 32 for r in limpio.split("\n")), limpio)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM bitacora WHERE accion='tirilla_impresa'")["n"], 1)

    def test_sin_tildes_y_ultima(self):
        self.configurar(tirilla_tildes="no")
        self.vender()
        with mock.patch("app.cajon.enviar_crudo", return_value=(True, "")) as enviar:
            r = self.post(self.c, "/pos/api/imprimir-tirilla", {"venta_id": "ultima"})
        self.assertTrue(r.get_json()["ok"])
        datos = enviar.call_args[0][1]
        self.assertNotIn(b"\x1bt\x02", datos)
        self.assertIn(b"Atendio", datos)

    def test_errores(self):
        r = self.post(self.c, "/pos/api/imprimir-tirilla", {"venta_id": "ultima"})
        self.assertFalse(r.get_json()["ok"])                           # todavía no hay ventas
        r = self.post(self.c, "/pos/api/imprimir-tirilla", {"venta_id": "abc"})
        self.assertFalse(r.get_json()["ok"])
        venta = self.vender()
        # Sin Windows (o sin la impresora), la impresión avisa sin romper nada.
        # Se simula "sin Windows" para que la prueba dé igual en Linux y en Windows.
        with mock.patch("app.cajon.disponible", return_value=False):
            r = self.post(self.c, "/pos/api/imprimir-tirilla", {"venta_id": str(venta["venta_id"])})
        self.assertFalse(r.get_json()["ok"])
        self.assertIn("Windows", r.get_json()["error"])

    def test_configuracion_pos_y_comprobante(self):
        self.configurar(tirilla_modo="directa")
        venta = self.vender()
        html = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('id="cfg-tirilla" value="directa"', html)
        self.assertIn('id="exito-imprimir"', html)
        html = self.c.get(f"/pos/venta/{venta['venta_id']}").get_data(as_text=True)
        self.assertIn("Imprimir en el mostrador", html)
        with mock.patch("app.cajon.enviar_crudo", return_value=(True, "")):
            r = self.post(self.c, f"/pos/venta/{venta['venta_id']}/imprimir", {})
        self.assertEqual(r.status_code, 302)
        self.assertIn("impresa=1", r.headers["Location"])
        # Valor raro -> por el navegador (como antes)
        self.configurar(tirilla_modo="cohete")
        html = self.c.get(f"/pos/venta/{venta['venta_id']}").get_data(as_text=True)
        self.assertNotIn("Imprimir en el mostrador", html)

    def test_prueba_desde_configuracion(self):
        self.configurar()
        with mock.patch("app.cajon.enviar_crudo", return_value=(True, "")) as enviar:
            r = self.post(self.c, "/configuracion/probar-tirilla", {"impresora_tirillas": "POS-58"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("PRUEBA".encode(), enviar.call_args[0][1])
