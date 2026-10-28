"""
PRUEBAS DE LA VERSIÓN 1.1.13
============================
  - TestValorInventario: cuánto vale la mercancía (al costo y a precio de venta),
    por categoría, y lo que no se puede vender aparte.
  - TestVentasRapidas: fotocopias, dulcería, inyectología... guardadas una vez y
    vendidas desde el POS sin tocar el inventario; reporte por concepto.

Recordatorio de los datos de prueba (BaseVentas):
  producto 1 = Acetaminofén, $1.000 la unidad, sin IVA
  producto 2 = Jeringa, $11.900 con IVA 19 % (sin IVA = $10.000)
  self.lote(...) crea lotes con costo $100 cada unidad.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO


class TestValorInventario(BaseVentas):
    def setUp(self):
        super().setUp()
        self.lote(1, "A1", FUTURO, 10)                       # vendible: 10 × $100
        self.lote(2, "J1", FUTURO, 5)                        # vendible: 5 × $100
        self.lote(1, "VIEJO", "2020-01-31", 2)               # vencido: 2 × $100
        self.lote(2, "CUAR", FUTURO, 3, estado="cuarentena")  # cuarentena: 3 × $100

    def calcular(self):
        from app.informes import valor_inventario
        with self.app.app_context():
            return valor_inventario()

    def test_totales(self):
        d = self.calcular()
        self.assertEqual(d["costo"], 1500)                     # 1.000 + 500
        self.assertEqual(d["venta"], 69500)                    # 10 × 1.000 + 5 × 11.900
        self.assertAlmostEqual(d["venta_sin_iva"], 60000)      # la jeringa sin IVA vale 10.000
        self.assertAlmostEqual(d["ganancia"], 58500)
        grupos = {g["grupo"]: g["costo"] for g in d["no_vendible"]}
        self.assertEqual(grupos, {"Vencidos": 200, "En cuarentena": 300})
        self.assertEqual(d["costo_no_vendible"], 500)          # NO suma en el total de arriba

    def test_categoria_contada_una_sola_vez(self):
        con = self.db()
        a = con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) "
                        "VALUES ('categoria', 'Alfa prueba', 1, '2026-01-01')").lastrowid
        b = con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) "
                        "VALUES ('categoria', 'Zeta prueba', 1, '2026-01-01')").lastrowid
        con.execute("INSERT INTO productos_categorias (producto_id, catalogo_id) VALUES (1, ?), (1, ?)", (a, b))
        con.commit()
        con.close()
        cats = {c["categoria"]: c["costo"] for c in self.calcular()["categorias"]}
        self.assertEqual(cats, {"Alfa prueba": 1000, "Sin categoría": 500})   # Zeta no repite el acetaminofén

    def test_lote_sin_costo_se_avisa(self):
        con = self.db()
        con.execute("UPDATE lotes SET costo_unitario = 0 WHERE lote = 'J1'")
        con.commit()
        con.close()
        d = self.calcular()
        self.assertEqual([p["id"] for p in d["sin_costo"]], [2])
        self.assertEqual(d["costo"], 1000)

    def test_pantallas(self):
        html = self.c.get("/reportes/inventario").get_data(as_text=True)
        self.assertIn("Valor del inventario", html)
        self.assertIn("$1.500", html)
        self.assertIn("$69.500", html)
        self.assertIn("En cuarentena", html)
        inicio = self.c.get("/inventario/").get_data(as_text=True)
        self.assertIn('id="kpi-valor-inventario"', inicio)
        self.assertIn("Valor del inventario", self.c.get("/reportes/").get_data(as_text=True))


class TestVentasRapidas(BaseVentas):
    def crear(self, **datos):
        base = {"nombre": "Fotocopia", "precio": "200", "iva_tarifa": "0", "costo": "50"}
        base.update(datos)
        return self.post(self.c, "/ventas-rapidas/guardar", base, follow_redirects=True)

    def test_migracion(self):
        self.assertGreaterEqual(self.uno("SELECT MAX(version) v FROM schema_version")["v"], 42)

    def test_crear_editar_y_no_repetir(self):
        self.crear()
        self.crear(nombre="Dulcería", precio="", costo="")       # sin precio fijo
        v = self.uno("SELECT * FROM ventas_rapidas WHERE nombre = 'Dulcería'")
        self.assertIsNone(v["precio"])
        self.assertIsNone(v["costo"])
        r = self.crear(nombre="  fotocopía ")                    # mismo nombre (tilde y mayúsculas)
        self.assertIn("Ya existe", r.get_data(as_text=True))
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM ventas_rapidas")["n"], 2)
        fid = self.uno("SELECT id FROM ventas_rapidas WHERE nombre = 'Fotocopia'")["id"]
        self.crear(id=str(fid), nombre="Fotocopia B/N", precio="300")
        self.assertEqual(self.uno("SELECT precio FROM ventas_rapidas WHERE id = ?", fid)["precio"], 300)
        html = self.c.get("/ventas-rapidas/").get_data(as_text=True)
        self.assertIn("Fotocopia B/N", html)
        self.assertIn("Se pregunta", html)                       # la dulcería no tiene precio

    def test_validaciones(self):
        from app.ventas_rapidas import leer_y_validar
        self.assertIsNotNone(leer_y_validar({"nombre": "ab"})[1])
        self.assertIsNotNone(leer_y_validar({"nombre": "Fotocopia", "precio": "0"})[1])
        self.assertIsNotNone(leer_y_validar({"nombre": "Fotocopia", "iva_tarifa": "10"})[1])
        valores, error = leer_y_validar({"nombre": "Inyectología", "precio": "5.000", "costo": "1.200,5"})
        self.assertIsNone(error)
        self.assertEqual((valores["precio"], valores["costo"]), (5000, 1200.5))

    def test_quitar_del_pos(self):
        self.crear()
        fid = self.uno("SELECT id FROM ventas_rapidas")["id"]
        self.post(self.c, f"/ventas-rapidas/{fid}/activar", {})
        from app.ventas_rapidas import lista_activas
        with self.app.app_context():
            self.assertEqual(lista_activas(), [])
        # Si en el POS la escriben otra vez con «Guardar», vuelve a salir (no se duplica)
        j = self.post(self.c, "/ventas-rapidas/api/crear", {"nombre": "FOTOCOPIA", "precio": ""}).get_json()
        self.assertTrue(j["ok"] and j["ya_existia"])
        with self.app.app_context():
            self.assertEqual(len(lista_activas()), 1)

    def test_crear_desde_el_pos_y_salen_en_la_pagina(self):
        self.abrir_caja()
        j = self.post(self.c, "/ventas-rapidas/api/crear",
                      {"nombre": "Inyectología", "precio": "5000", "iva_tarifa": "0", "costo": ""}).get_json()
        self.assertTrue(j["ok"])
        self.assertFalse(j["ya_existia"])
        self.assertEqual(j["venta_rapida"]["precio"], 5000)
        error = self.post(self.c, "/ventas-rapidas/api/crear", {"nombre": "x"})
        self.assertEqual(error.status_code, 400)
        pos = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('id="ventas-rapidas"', pos)
        self.assertIn("Inyectolog", pos)          # en el JSON la "í" va escrita como \u00ed
        self.assertIn('id="url-api-venta-rapida"', pos)

    def test_vender_no_toca_inventario_y_sale_en_el_reporte(self):
        self.crear()
        fid = self.uno("SELECT id FROM ventas_rapidas")["id"]
        self.lote(1, "A1", FUTURO, 10)
        self.abrir_caja()
        carrito = [
            {"libre": 1, "descripcion": "Fotocopia", "precio": 200, "cantidad": 10, "iva_tarifa": 0,
             "costo": 50, "venta_rapida_id": fid},
            {"libre": 1, "descripcion": "dulce de coco", "precio": 500, "cantidad": 2, "iva_tarifa": 0},
            {"libre": 1, "descripcion": "Dulce de Coco", "precio": 700, "cantidad": 1, "iva_tarifa": 0},
            {"libre": 1, "descripcion": "Algo raro", "precio": 100, "cantidad": 1, "iva_tarifa": 0,
             "venta_rapida_id": 9999},                       # no existe: se guarda sin venta rápida
        ]
        j = self.cobrar(carrito, recibido="10000").get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(self.stock(1), 10)                  # el inventario no se tocó
        ids = [f["venta_rapida_id"] for f in self.db().execute(
            "SELECT venta_rapida_id FROM venta_lineas ORDER BY id").fetchall()]
        self.assertEqual(ids, [fid, None, None, None])

        from app.informes import ventas_libres
        with self.app.app_context():
            from app.db import get_db
            libres = {f["nombre"]: f for f in ventas_libres(get_db(), "2000-01-01", "2100-01-01")}
        self.assertEqual(libres["Fotocopia"]["con_iva"], 2000)
        self.assertEqual(libres["Fotocopia"]["ganancia"], 1500)          # 2.000 − 10 × 50
        self.assertEqual(libres["dulce de coco"]["cantidad"], 3)         # junta "Dulce de Coco"
        self.assertIsNone(libres["dulce de coco"]["ganancia"])           # sin costo: no se inventa
        html = self.c.get("/reportes/ventas").get_data(as_text=True)
        self.assertIn('id="rep-ventas-libres"', html)
        self.assertIn("Venta rápida", html)

    def test_veces_vendida_en_la_lista(self):
        self.crear()
        fid = self.uno("SELECT id FROM ventas_rapidas")["id"]
        self.abrir_caja()
        self.cobrar([{"libre": 1, "descripcion": "Fotocopia", "precio": 200, "cantidad": 1, "iva_tarifa": 0,
                      "venta_rapida_id": fid}], recibido="200")
        html = self.c.get("/ventas-rapidas/").get_data(as_text=True)
        self.assertRegex(html, r'class="num">1</td>')


if __name__ == "__main__":
    import unittest
    unittest.main()
