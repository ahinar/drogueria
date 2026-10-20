"""
PRUEBAS DE LA VERSIÓN 1.1.6
===========================
Cada clase prueba una parte de lo que pidió Fernando para esta versión:
  - TestNombres / TestCatalogosSinRepetidos / TestUnirRepetidos: catálogos y
    unidades sin repetidos ("SAN FER" = "Sanfer"), orden con tildes y unidades
    por tamaño.
(Las demás partes de la 1.1.6 se agregan abajo, cada una en su clase.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import FECHA
from test_fase2_ventas import BaseVentas, FUTURO


class TestNombres(BaseVentas):
    def test_clave_y_orden(self):
        from app.nombres import clave, orden, orden_unidades
        self.assertEqual(clave("SAN FER"), clave("Sanfer."))
        self.assertEqual(clave("Acetaminofén"), clave("acetaminofen"))
        self.assertEqual(clave("Caja x12"), clave("CAJA X 12"))
        self.assertLess(orden("Ácido fólico"), orden("Zinc"))       # la tilde no manda al final
        unidades = [{"nombre": n, "cantidad": c} for n, c in (
            ("Caja x 12", 1), ("Sello x 10", 10), ("Unidad", 1), ("Caja x 10", 10), ("Sello x 4", 4))]
        self.assertEqual([u["nombre"] for u in orden_unidades(unidades)],
                         ["Unidad", "Sello x 4", "Caja x 10", "Sello x 10", "Caja x 12"])

    def test_sqlite_ordena_con_tildes(self):
        from app.db import get_db
        con = self.db()
        for n in ("Zinc", "Ácido fólico", "Amoxicilina"):
            con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES ('principio', ?, 1, ?)",
                        (n, FECHA))
        con.commit()
        con.close()
        with self.app.app_context():
            nombres = [f["nombre"] for f in get_db().execute(
                "SELECT nombre FROM catalogos WHERE tipo = 'principio' AND nombre IN ('Zinc','Ácido fólico','Amoxicilina') "
                "ORDER BY nombre COLLATE ES")]
        self.assertEqual(nombres, ["Ácido fólico", "Amoxicilina", "Zinc"])


class TestCatalogosSinRepetidos(BaseVentas):
    def n(self, tipo, clave_):
        from app.nombres import clave
        con = self.db()
        filas = con.execute("SELECT nombre FROM catalogos WHERE tipo = ?", (tipo,)).fetchall()
        con.close()
        return sum(1 for f in filas if clave(f["nombre"]) == clave_)

    def test_api_y_formulario_no_crean_repetidos(self):
        j1 = self.post(self.c, "/admin/catalogos/laboratorio/api/crear", {"nombre": "SAN FER"}).get_json()
        j2 = self.post(self.c, "/admin/catalogos/laboratorio/api/crear", {"nombre": "san fer."}).get_json()
        self.assertEqual(j1["id"], j2["id"])
        self.assertTrue(j2.get("existente"))
        self.post(self.c, "/admin/catalogos/laboratorio/nuevo", {"nombre": "Sanfer"})
        self.assertEqual(self.n("laboratorio", "sanfer"), 1)

    def test_unidades_sin_repetidas(self):
        self.post(self.c, "/admin/unidades/nueva", {"nombre": "Caja x 12", "cantidad": "12"})
        j = self.post(self.c, "/recepciones/api/crear-unidad", {"nombre": "CAJA X12"}).get_json()
        con = self.db()
        n = con.execute("SELECT COUNT(*) FROM unidades_medida WHERE REPLACE(LOWER(nombre),' ','') = 'cajax12'").fetchone()[0]
        con.close()
        self.assertEqual(n, 1)
        self.assertTrue(j["ok"])


class TestUnirRepetidos(BaseVentas):
    def test_buscar_y_unir(self):
        # Se cuelan dos laboratorios "iguales" (como pasaba antes de la 1.1.6)
        con = self.db()
        a = con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES ('laboratorio','SAN FER',1,?)",
                        (FECHA,)).lastrowid
        b = con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES ('laboratorio','San fer',1,?)",
                        (FECHA,)).lastrowid
        con.execute("UPDATE productos SET laboratorio_id = ? WHERE id = 1", (a,))
        con.execute("UPDATE productos SET laboratorio_id = ? WHERE id = 2", (b,))
        con.commit()
        con.close()
        html = self.c.get("/admin/catalogos/repetidos").get_data(as_text=True)
        self.assertIn("SAN FER", html)
        self.assertIn("San fer", html)
        self.post(self.c, "/admin/catalogos/repetidos/unir", {"tipo": "laboratorio", "queda": str(a),
                                                               "ids": [str(a), str(b)]})
        con = self.db()
        labs = {r[0] for r in con.execute("SELECT laboratorio_id FROM productos WHERE id IN (1, 2)")}
        quedan = con.execute("SELECT COUNT(*) FROM catalogos WHERE id IN (?, ?)", (a, b)).fetchone()[0]
        con.close()
        self.assertEqual(labs, {a})            # los dos productos quedaron en el que se escogió
        self.assertEqual(quedan, 1)
        self.assertIn("No hay repetidos", self.c.get("/admin/catalogos/repetidos").get_data(as_text=True))

    def test_no_une_nombres_distintos(self):
        con = self.db()
        a = con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES ('laboratorio','MK',1,?)",
                        (FECHA,)).lastrowid
        b = con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES ('laboratorio','GENFAR',1,?)",
                        (FECHA,)).lastrowid
        con.commit()
        con.close()
        self.post(self.c, "/admin/catalogos/repetidos/unir", {"tipo": "laboratorio", "queda": str(a),
                                                               "ids": [str(a), str(b)]})
        con = self.db()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM catalogos WHERE id IN (?, ?)", (a, b)).fetchone()[0], 2)
        con.close()


class TestVariosPrincipios(BaseVentas):
    """Productos compuestos: «acetaminofén, codeína»."""

    def crear(self, principios):
        unidad = self.uno("SELECT id FROM unidades_medida WHERE nombre = 'Unidad'")["id"]
        self.post(self.c, "/productos/nuevo", {
            "codigo": "PX1", "nombre": "Acetaminofén + Codeína", "principios": principios,
            "venta_unidad_id": str(unidad), "venta_precio": "1000", "unidad_venta_id": str(unidad),
            "iva_tipo": "excluido"})
        return self.uno("SELECT * FROM productos WHERE codigo = 'PX1'")

    def test_ficha_guarda_varios_y_reusa_los_existentes(self):
        con = self.db()
        con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) VALUES ('principio','Acetaminofén',1,?)",
                    (FECHA,))
        con.commit()
        con.close()
        p = self.crear("acetaminofen, Codeína")
        self.assertIsNotNone(p, "no se creó el producto")
        con = self.db()
        nombres = [r[0] for r in con.execute(
            "SELECT c.nombre FROM producto_principios pp JOIN catalogos c ON c.id = pp.catalogo_id "
            "WHERE pp.producto_id = ? ORDER BY pp.orden", (p["id"],))]
        n_aceta = con.execute("SELECT COUNT(*) FROM catalogos WHERE tipo='principio' AND nombre LIKE 'Acetamin%'").fetchone()[0]
        primero = con.execute("SELECT nombre FROM catalogos WHERE id = ?", (p["principio_id"],)).fetchone()[0]
        con.close()
        self.assertEqual(nombres, ["Acetaminofén", "Codeína"])
        self.assertEqual(n_aceta, 1)                     # no se creó otro "Acetaminofen" sin tilde
        self.assertEqual(primero, "Acetaminofén")        # el primero queda también en principio_id

    def test_busca_por_cualquier_principio(self):
        self.crear("acetaminofén, codeína")
        r = self.c.get("/recepciones/api/buscar-productos?q=codeina").get_json()["resultados"]
        self.assertIn("PX1", [x["codigo"] for x in r])
        j = self.c.get("/pos/api/productos?q=codeína").get_json()
        self.assertIn("PX1", [x["codigo"] for x in j["productos"]])

    def test_completar_datos_de_la_recepcion(self):
        p = self.crear("")
        j = self.post(self.c, f"/recepciones/api/producto/{p['id']}/tecnicos",
                      {"principios": "losartán, hidroclorotiazida", "laboratorio_id": "", "forma_farmaceutica_id": "",
                       "concentracion": "", "registro_sanitario": "", "registro_vence": ""}).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["producto"]["principios"], "losartán, hidroclorotiazida")

    def test_ficha_muestra_el_texto(self):
        p = self.crear("acetaminofén, codeína")
        html = self.c.get(f"/productos/{p['id']}/editar").get_data(as_text=True)
        self.assertIn('value="acetaminofén, codeína"', html)


class TestLaboratorioOpcional(BaseVentas):
    def test_alta_rapida_sin_laboratorio(self):
        unidad = self.uno("SELECT id FROM unidades_medida WHERE nombre = 'Unidad'")["id"]
        j = self.post(self.c, "/recepciones/api/crear-producto", {
            "nombre": "Jabón de tocador", "venta_unidad_id": str(unidad), "precio_venta": "3.500"}).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["laboratorio"], "")
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn("Laboratorio o marca", html)


class TestIvaRecepcion(BaseVentas):
    """IVA por línea: el costo para la utilidad es CON IVA mientras la droguería no declare."""

    def recibir(self, costo, iva="19", incluye=False, factura="F-IVA"):
        datos = {"proveedor_id": "1", "factura_numero": factura,
                 "linea_producto_id": ["2"], "linea_lote": [""], "linea_vencimiento": [""],
                 "linea_cantidad_recibida": ["4"], "linea_costo": [costo], "linea_iva": [iva],
                 "linea_presentacion": ["0"], "linea_resultado": ["aceptado"]}
        if incluye:
            datos["precios_con_iva"] = "1"
        self.post(self.c, "/recepciones/nueva", datos)
        return self.uno("SELECT rl.* FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id "
                        "WHERE r.factura_numero = ?", factura)

    def test_iva_aparte_no_declara(self):
        l = self.recibir("10000")
        self.assertEqual((l["iva_tarifa"], round(l["costo_sin_iva"]), round(l["costo_con_iva"])), (19, 10000, 11900))
        self.assertEqual(round(l["costo_unitario"]), 11900)          # utilidad con el costo CON IVA

    def test_iva_incluido(self):
        l = self.recibir("11900", incluye=True, factura="F-INC")
        self.assertEqual((round(l["costo_sin_iva"]), round(l["costo_con_iva"]), round(l["costo_unitario"])),
                         (10000, 11900, 11900))

    def test_si_declara_usa_costo_sin_iva(self):
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1", "declara_iva": "si"})
        l = self.recibir("10000", factura="F-DEC")
        self.assertEqual(round(l["costo_unitario"]), 10000)

    def test_pantallas(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        for pieza in ('name="precios_con_iva"', 'name="linea_iva"', 'id="total-iva"'):
            self.assertIn(pieza, html)
        self.recibir("10000", factura="F-VER")
        rec = self.uno("SELECT id FROM recepciones WHERE factura_numero = 'F-VER'")
        ver = self.c.get(f"/recepciones/{rec['id']}").get_data(as_text=True)
        self.assertIn("Total de la factura", ver)
        self.assertIn("47.600", ver)                                   # 4 × 10.000 + 19 %


class TestSesionesDeCaja(BaseVentas):
    """Sobrantes y faltantes de caja: quedan solos como otro ingreso o gasto, una sola vez."""

    def cerrar(self, contado):
        return self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": contado}).get_json()

    def venta_y_cierre(self, contado):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja("10000")
        self.cobrar([{"producto_id": 1, "cantidad": 5}], recibido="5000")   # esperado = 10.000 + 5.000
        j = self.cerrar(contado)
        self.assertTrue(j["ok"], j)
        return self.uno("SELECT * FROM cajas ORDER BY id DESC LIMIT 1")

    def test_faltante_queda_como_gasto(self):
        caja = self.venta_y_cierre("14000")
        self.assertEqual(round(caja["diferencia"]), -1000)
        g = self.uno("SELECT g.*, c.nombre cat FROM gastos g JOIN catalogos c ON c.id = g.categoria_id "
                     "WHERE g.id = ?", caja["diferencia_gasto_id"])
        self.assertEqual((round(g["monto"]), g["cat"]), (1000, "Faltante de caja"))
        self.assertIsNone(caja["diferencia_ingreso_id"])

    def test_sobrante_queda_como_otro_ingreso(self):
        caja = self.venta_y_cierre("15500")
        i = self.uno("SELECT o.*, c.nombre cat FROM otros_ingresos o JOIN catalogos c ON c.id = o.categoria_id "
                     "WHERE o.id = ?", caja["diferencia_ingreso_id"])
        self.assertEqual((round(i["monto"]), i["cat"]), (500, "Sobrante de caja"))

    def test_cuadra_no_registra_nada_y_no_repite(self):
        caja = self.venta_y_cierre("15000")
        self.assertEqual(caja["diferencia_revisada"], 1)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM gastos")["n"], 0)
        from app import cajas
        con = self.db()
        self.assertEqual(cajas.registrar_pendientes(con), 0)          # ya estaba revisada
        con.close()

    def test_cajas_cerradas_antes_de_la_version(self):
        """Una caja cerrada antes de la 1.1.6 (sin revisar) se registra una sola vez al arrancar."""
        caja = self.venta_y_cierre("13000")
        con = self.db()
        con.execute("DELETE FROM gastos")
        con.execute("UPDATE cajas SET diferencia_revisada = 0, diferencia_gasto_id = NULL WHERE id = ?", (caja["id"],))
        con.commit()
        from app import cajas
        self.assertEqual(cajas.registrar_pendientes(con), 1)
        self.assertEqual(cajas.registrar_pendientes(con), 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM gastos").fetchone()[0], 1)
        con.close()

    def test_clase_y_pantallas(self):
        from app.cajas import clase_diferencia
        self.assertEqual([clase_diferencia(x) for x in (0, -1000, 500, None)], ["cuadra", "falta", "sobra", None])
        caja = self.venta_y_cierre("14000")
        lista = self.c.get("/contabilidad/cajas").get_data(as_text=True)
        self.assertIn("dif-falta", lista)
        self.assertIn("−$1.000", lista.replace("−$ 1.000", "−$1.000"))
        det = self.c.get(f"/contabilidad/cajas/{caja['id']}")
        self.assertEqual(det.status_code, 200)
        self.assertIn("Faltante de caja", det.get_data(as_text=True))


class TestDashboardContabilidad(BaseVentas):
    def test_dashboard_carga_con_datos(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 2}], recibido="2000")
        r = self.c.get("/contabilidad/")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for pieza in ("dash-ingresos", "dash-utilidad", 'id="g-flujo"', 'id="g-meses"', "Sesiones de caja"):
            self.assertIn(pieza, html)
        self.assertNotIn("dash-iva", html)                            # no declara IVA: sin tarjeta de IVA

    def test_tarjeta_iva_solo_si_declara(self):
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1", "declara_iva": "si"})
        html = self.c.get("/contabilidad/").get_data(as_text=True)
        self.assertIn("dash-iva", html)

    def test_mes_anterior(self):
        r = self.c.get("/contabilidad/?mes=2020-01")
        self.assertEqual(r.status_code, 200)


class TestIconoBarraDeTareas(BaseVentas):
    """Solo se tocan las ventanas de Fervifarma, nunca las del Chrome de uso diario."""

    def test_reconoce_ventanas(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from icono_ventana import es_ventana_del_programa as es
        self.assertTrue(es("Chrome_WidgetWin_1", "Vender · Fervifarma"))
        self.assertTrue(es("Chrome_WidgetWin_1", "Comprobante V-0012"))
        self.assertFalse(es("Chrome_WidgetWin_1", "Vender · Fervifarma - Google Chrome"))
        self.assertFalse(es("Chrome_WidgetWin_1", "Inicio · Fervifarma - Personal: Microsoft​ Edge"))
        self.assertFalse(es("Notepad", "Vender · Fervifarma"))

    def test_favicon_png(self):
        self.assertIn("img/app-192.png", self.c.get("/productos/").get_data(as_text=True))
