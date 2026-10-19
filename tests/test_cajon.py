"""
PRUEBAS DEL CAJÓN MONEDERO (app/cajon.py) Y DE LA TIRILLA.

Aquí no hay impresora ni Windows, así que se prueba:
  - que la orden ESC/POS sea la correcta
  - que en un computador sin Windows avise (sin romper nada)
  - que, si "abrir" funciona (simulado), el POS lo registre en la bitácora
  - la configuración (cuándo abrirlo) y que el POS la reciba
  - que el enlace "Ver comprobante" deje a la tirilla cerrarse al volver
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas


class TestCajon(BaseVentas):
    def test_orden_escpos(self):
        from app.cajon import ORDEN_ABRIR
        # ESC p 0 25 250 (pin 2) + ESC p 1 25 250 (pin 5)
        self.assertEqual(ORDEN_ABRIR, b"\x1bp\x00\x19\xfa\x1bp\x01\x19\xfa")

    def test_sin_windows_avisa(self):
        from app import cajon
        with mock.patch.object(cajon, "disponible", return_value=False):
            ok, error = cajon.abrir("POS-58")
        self.assertFalse(ok)
        self.assertIn("Windows", error)

    def test_api_necesita_caja_abierta_y_queda_en_bitacora(self):
        r = self.post(self.c, "/pos/api/abrir-cajon", {"motivo": "manual"})
        self.assertFalse(r.get_json()["ok"])                    # sin caja abierta
        self.abrir_caja()
        with mock.patch("app.cajon.abrir", return_value=(True, "")) as abrir:
            r = self.post(self.c, "/pos/api/abrir-cajon", {"motivo": "cobro"})
        self.assertTrue(r.get_json()["ok"])
        abrir.assert_called_once()
        bit = self.uno("SELECT detalle FROM bitacora WHERE accion = 'cajon_abierto'")
        self.assertEqual(bit["detalle"], "motivo=cobro")

    def test_configuracion_y_pos(self):
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1", "ancho_tirilla": "58",
                                              "cajon_modo": "efectivo", "impresora_tirillas": "POS-58"})
        from app.configuracion import obtener_config
        with self.app.app_context():
            cfg = obtener_config()
        self.assertEqual((cfg["cajon_modo"], cfg["impresora_tirillas"]), ("efectivo", "POS-58"))
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1", "cajon_modo": "cohete"})
        with self.app.app_context():
            self.assertEqual(obtener_config()["cajon_modo"], "no")          # valor raro -> "no"
        self.abrir_caja()
        html = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('id="cfg-cajon" value="no"', html)
        self.assertIn('data-accion="abrir-cajon"', html)
        # "Ver comprobante" abre la tirilla CON acceso a la ventana del POS (rel="opener"),
        # así "Volver al POS" la cierra en vez de abrir otro POS
        self.assertIn('id="exito-comprobante" href="#" target="_blank" rel="opener"', html)


class TestCorreccion112(BaseVentas):
    """Versión 1.1.2: el cajón no abría porque se cargaba "winspool" (.dll) en vez de winspool.drv."""

    def test_carga_winspool_drv(self):
        # Se revisa el código: en ningún lado debe quedar la forma vieja ctypes.windll.winspool.X
        from app import cajon
        codigo = Path(cajon.__file__).read_text(encoding="utf-8")
        self.assertIn('WinDLL("winspool.drv")', codigo)
        self.assertNotIn("windll.winspool.", codigo)

    def test_si_windows_falla_avisa_sin_romper(self):
        # Si Windows lanza un error raro, se devuelve un mensaje (no un "error 500")
        from app import cajon
        with mock.patch.object(cajon, "disponible", return_value=True), \
             mock.patch.object(cajon, "_enviar_crudo_windows", side_effect=OSError("prueba")):
            ok, error = cajon.abrir("POS-58")
        self.assertFalse(ok)
        self.assertIn("prueba", error)


class TestInstalable(BaseVentas):
    """Versión 1.1.2: el programa se puede instalar como aplicación desde Chrome."""

    def test_manifiesto_y_service_worker_sin_contraseña(self):
        anonimo = self.app.test_client()                     # sin iniciar sesión
        r = anonimo.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/manifest+json")
        datos = r.get_json(force=True)
        self.assertEqual(datos["display"], "standalone")
        tamaños = {i["sizes"] for i in datos["icons"]}
        self.assertTrue({"192x192", "512x512"} <= tamaños)    # Chrome exige estos dos
        for icono in datos["icons"]:
            self.assertEqual(anonimo.get(icono["src"]).status_code, 200)
        r = anonimo.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/javascript")

    def test_paginas_anuncian_el_manifiesto(self):
        anonimo = self.app.test_client()
        self.assertIn('rel="manifest"', anonimo.get("/login").get_data(as_text=True))
        self.assertIn('rel="manifest"', self.c.get("/").get_data(as_text=True))


class TestOrdenesCajon113(BaseVentas):
    """Versión 1.1.3: se puede escoger qué orden mandar para abrir el cajón."""

    def test_ordenes(self):
        from app import cajon
        self.assertEqual(set(cajon.ORDENES), {"estandar", "largo", "tiempo_real"})
        for _nombre, datos in cajon.ORDENES.values():
            self.assertTrue(datos.startswith(b"\x1b@"))           # todas reinician primero
        self.assertIn(b"\x10\x14\x01\x00\x05", cajon.ORDENES["tiempo_real"][1])   # DLE DC4

    def test_se_guarda_y_el_pos_la_usa(self):
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1",
                                              "cajon_orden": "tiempo_real", "impresora_tirillas": "SAT Q150"})
        from app.configuracion import obtener_config
        with self.app.app_context():
            self.assertEqual(obtener_config()["cajon_orden"], "tiempo_real")
        self.abrir_caja()
        with mock.patch("app.cajon.abrir", return_value=(True, "")) as abrir:
            j = self.post(self.c, "/pos/api/abrir-cajon", {"motivo": "manual"}).get_json()
        abrir.assert_called_once_with("SAT Q150", "tiempo_real")
        self.assertEqual(j["impresora"], "SAT Q150")              # el POS dice a cuál impresora llegó

    def test_valor_raro_queda_estandar(self):
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1", "cajon_orden": "cohete"})
        from app.configuracion import obtener_config
        with self.app.app_context():
            self.assertEqual(obtener_config()["cajon_orden"], "estandar")


class TestRecepcionBarras113(BaseVentas):
    def test_modal_tiene_codigo_de_barras(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn('id="np-barras"', html)
        self.assertIn("codigo_barras", html)
        self.assertIn("beforeunload", html)                       # avisa antes de salir sin guardar


class TestBusquedaConLaboratorio113(BaseVentas):
    """Versión 1.1.3: productos que se llaman igual se distinguen por el laboratorio."""

    def setUp(self):
        super().setUp()
        con = self.db()
        labs = {}
        for nombre in ("SAN FER", "GENFAR"):
            labs[nombre] = con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) "
                                       "VALUES ('laboratorio', ?, 1, '2026-10-18')", (nombre,)).lastrowid
        unidad = con.execute("SELECT id FROM unidades_medida LIMIT 1").fetchone()[0]
        for codigo, lab in (("TZ1", "SAN FER"), ("TZ2", "GENFAR")):
            con.execute("INSERT INTO productos (codigo, nombre, concentracion, laboratorio_id, unidad_venta_id, "
                        "precio_venta, activo, creado_en) VALUES (?, 'TRAZODONA CLORHIDRATO', '50 MG', ?, ?, 600, 1, "
                        "'2026-10-18')", (codigo, labs[lab], unidad))
        con.commit()
        con.close()

    def test_recepcion_busca_por_nombre_y_laboratorio(self):
        r = self.c.get("/recepciones/api/buscar-productos?q=trazodona san fer").get_json()["resultados"]
        self.assertEqual([x["codigo"] for x in r], ["TZ1"])
        self.assertEqual(r[0]["laboratorio"], "SAN FER")
        # Solo el nombre: salen los dos, ordenados por laboratorio (GENFAR antes que SAN FER)
        r = self.c.get("/recepciones/api/buscar-productos?q=trazodona 50").get_json()["resultados"]
        self.assertEqual([x["codigo"] for x in r], ["TZ2", "TZ1"])

    def test_pos_busca_por_laboratorio_y_lo_devuelve(self):
        j = self.c.get("/pos/api/productos?q=trazodona genfar").get_json()
        self.assertEqual([p["codigo"] for p in j["productos"]], ["TZ2"])
        self.assertEqual(j["productos"][0]["laboratorio"], "GENFAR")

    def test_lista_de_productos(self):
        html = self.c.get("/productos/?q=trazodona san fer").get_data(as_text=True)
        self.assertIn("TZ1", html)
        self.assertNotIn("TZ2", html)

    def test_las_paginas_tienen_la_etiqueta(self):
        self.assertIn("chipLaboratorio", self.c.get("/").get_data(as_text=True))


class TestTotalPorLinea113(BaseVentas):
    def test_recepcion_muestra_total_de_cada_linea(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn('class="linea-total-txt"', html)     # debajo del costo: cantidad × costo


class TestBuscaQueContenga113(BaseVentas):
    """Fernando buscó «meloxi» y no salió «MEBLAINEX MELOXICAM»: había muchos «MELOXICAM ...»
    que empezaban igual y ocupaban todos los puestos de la lista."""

    def test_sale_aunque_haya_muchos_que_empiezan_igual(self):
        con = self.db()
        unidad = con.execute("SELECT id FROM unidades_medida LIMIT 1").fetchone()[0]
        for i in range(25):
            con.execute("INSERT INTO productos (codigo, nombre, unidad_venta_id, activo, creado_en) "
                        "VALUES (?, ?, ?, 1, '2026-10-18')", (f"M{i:02d}", f"MELOXICAM {i} MG", unidad))
        con.execute("INSERT INTO productos (codigo, nombre, unidad_venta_id, activo, creado_en) "
                    "VALUES ('MBX', 'MEBLAINEX MELOXICAM', ?, 1, '2026-10-18')", (unidad,))
        con.commit()
        con.close()
        r = self.c.get("/recepciones/api/buscar-productos?q=meloxi").get_json()["resultados"]
        self.assertIn("MBX", [x["codigo"] for x in r])
        self.assertEqual(r[0]["nombre"][:9], "MELOXICAM")              # los que empiezan igual, primero


class TestLaboratoriosEnCompletarDatos113(BaseVentas):
    def test_lista_actual_y_boton_crear(self):
        self.post(self.c, "/admin/catalogos/laboratorio/api/crear", {"nombre": "BLASKOV"})
        j = self.c.get("/admin/catalogos/laboratorio/api/lista").get_json()
        self.assertIn("BLASKOV", [x["nombre"] for x in j["items"]])
        self.assertEqual(self.app.test_client().get("/admin/catalogos/laboratorio/api/lista").status_code, 401)
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn('id="dt-nuevo-lab"', html)
        self.assertIn("refrescarLaboratorios", html)


class TestRecepcionObligatorios113(BaseVentas):
    """Versión 1.1.3: cantidad, UdM y costo obligatorios en cada línea con producto."""

    def enviar(self, cantidad, costo, udm):
        return self.post(self.c, "/recepciones/nueva", {
            "proveedor_id": "1", "factura_numero": "F-OBL",
            "linea_producto_id": ["2"], "linea_lote": [""], "linea_vencimiento": [""],
            "linea_cantidad_recibida": [cantidad], "linea_costo": [costo],
            "linea_presentacion": [udm], "linea_resultado": ["aceptado"]}, follow_redirects=True)

    def test_falta_udm(self):
        html = self.enviar("4", "1000", "").get_data(as_text=True)
        self.assertIn("escoge en qué unidad llegó", html)

    def test_falta_cantidad_o_costo(self):
        html = self.enviar("", "", "0").get_data(as_text=True)
        self.assertIn("la cantidad recibida debe ser mayor a cero", html)
        self.assertIn("el costo unitario debe ser mayor a cero", html)

    def test_pantalla_marca_obligatorios(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn("Cantidad · UdM *", html)
        self.assertIn("Costo por UdM *", html)
        self.assertIn("Escribe la cantidad recibida (mayor a 0).", html)
