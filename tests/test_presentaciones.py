"""
PRUEBAS DE LA VENTA POR PRESENTACIÓN (unidad / sobre / caja).

Montaje de cada prueba:
    Producto 1 = Acetaminofén. Unidad principal "Unidad" a $1.000.
    Presentaciones: "Sobre x 10" (trae 10) a $9.000 y "Caja x 100" (trae 100) a $80.000.
El inventario siempre está en unidades: vender 1 sobre descuenta 10.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import FECHA
from test_fase2_ventas import BaseVentas, FUTURO, FUTURO_CERCA


class BasePresentaciones(BaseVentas):
    def setUp(self):
        super().setUp()
        con = self.db()
        unidad = con.execute("SELECT id FROM unidades_medida WHERE nombre = 'Unidad'").fetchone()[0]
        self.sobre = con.execute(
            "INSERT INTO unidades_medida (nombre, cantidad, activo, creado_en) VALUES ('Sobre x 10', 10, 1, ?)",
            (FECHA,)).lastrowid
        self.caja = con.execute(
            "INSERT INTO unidades_medida (nombre, cantidad, activo, creado_en) VALUES ('Caja x 100', 100, 1, ?)",
            (FECHA,)).lastrowid
        con.execute("UPDATE productos SET unidad_venta_id = ?, precio_maximo = 1200 WHERE id = 1", (unidad,))
        self.unidad = unidad
        self.p_sobre = con.execute(
            "INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
            "precio_maximo, codigo_barras, creado_en) VALUES (1, ?, 10, 9000, 9500, '7700000000999', ?)",
            (self.sobre, FECHA)).lastrowid
        self.p_caja = con.execute(
            "INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, creado_en) "
            "VALUES (1, ?, 100, 80000, ?)", (self.caja, FECHA)).lastrowid
        con.commit()
        con.close()


class TestVenderPorPresentacion(BasePresentaciones):
    def test_vender_sobres_descuenta_unidades_y_cobra_precio_del_sobre(self):
        self.lote(1, "L1", FUTURO, 150)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "presentacion_id": self.p_sobre, "cantidad": 2}],
                        recibido="20000").get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["total"], 18000)        # 2 sobres x $9.000
        self.assertEqual(self.stock(1), 130)       # 150 - 2 x 10
        linea = self.uno("SELECT * FROM venta_lineas")
        self.assertEqual((linea["presentacion"], linea["factor"], linea["cantidad"], linea["precio_unitario"]),
                         ("Sobre x 10", 10, 2, 9000))
        self.assertEqual(linea["presentacion_id"], self.p_sobre)
        mov = self.uno("SELECT cantidad FROM movimientos_inventario WHERE tipo = 'venta'")
        self.assertEqual(mov["cantidad"], -20)

    def test_sin_presentacion_vende_la_unidad_principal(self):
        """Los carritos viejos (sin presentacion_id) siguen funcionando igual que antes."""
        self.lote(1, "L1", FUTURO, 50)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 3}]).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["total"], 3000)
        self.assertEqual(self.stock(1), 47)
        linea = self.uno("SELECT presentacion, factor, presentacion_id FROM venta_lineas")
        self.assertEqual((linea["presentacion"], linea["factor"], linea["presentacion_id"]), ("Unidad", 1, None))

    def test_caja_y_sueltas_del_mismo_producto_comparten_el_stock(self):
        """1 caja (100) + 15 sueltas = 115, pero solo hay 110 -> no se vende nada."""
        self.lote(1, "L1", FUTURO, 110)
        self.abrir_caja()
        r = self.cobrar([{"producto_id": 1, "presentacion_id": self.p_caja, "cantidad": 1},
                         {"producto_id": 1, "presentacion_id": 0, "cantidad": 15}])
        self.assertFalse(r.get_json()["ok"])
        self.assertEqual(self.stock(1), 110)
        # 1 caja + 10 sueltas sí alcanza
        j = self.cobrar([{"producto_id": 1, "presentacion_id": self.p_caja, "cantidad": 1},
                         {"producto_id": 1, "presentacion_id": 0, "cantidad": 10}]).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(self.stock(1), 0)
        self.assertEqual(j["total"], 90000)

    def test_mensaje_de_stock_habla_en_unidades(self):
        self.lote(1, "L1", FUTURO, 25)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "presentacion_id": self.p_sobre, "cantidad": 3}]).get_json()
        self.assertFalse(j["ok"])
        self.assertIn("30 unidades", j["error"])
        self.assertIn("25", j["error"])

    def test_fefo_con_presentacion(self):
        self.lote(1, "LARGO", FUTURO, 50)
        self.lote(1, "CORTO", FUTURO_CERCA, 15)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "presentacion_id": self.p_sobre, "cantidad": 2}])
        corto = self.uno("SELECT cantidad_disponible n FROM lotes WHERE lote='CORTO'")["n"]
        largo = self.uno("SELECT cantidad_disponible n FROM lotes WHERE lote='LARGO'")["n"]
        self.assertEqual((corto, largo), (0, 45))   # 15 del corto + 5 del largo

    def test_presentacion_de_otro_producto_se_rechaza(self):
        self.lote(2, "L2", FUTURO, 500)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 2, "presentacion_id": self.p_sobre, "cantidad": 1}]).get_json()
        self.assertFalse(j["ok"])
        self.assertEqual(self.stock(2), 500)

    def test_precio_maximo_es_el_de_la_presentacion(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        # El sobre tiene tope $9.500: $9.600 no se permite
        j = self.cobrar([{"producto_id": 1, "presentacion_id": self.p_sobre, "cantidad": 1,
                          "precio_nuevo": 9600, "motivo_precio": "prueba"}]).get_json()
        self.assertFalse(j["ok"])
        self.assertIn("máximo", j["error"])
        # $9.400 sí (aunque supera el tope de la UNIDAD, que es $1.200)
        j = self.cobrar([{"producto_id": 1, "presentacion_id": self.p_sobre, "cantidad": 1,
                          "precio_nuevo": 9400, "motivo_precio": "cliente frecuente"}]).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["total"], 9400)

    def test_anular_devuelve_las_unidades(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "presentacion_id": self.p_sobre, "cantidad": 3}])
        self.assertEqual(self.stock(1), 70)
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "Error"})
        self.assertEqual(self.stock(1), 100)

    def test_comprobante_muestra_la_presentacion(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "presentacion_id": self.p_caja, "cantidad": 1}])
        self.assertIn("Caja x 100", self.c.get("/pos/venta/1").get_data(as_text=True))


class TestBuscarConPresentaciones(BasePresentaciones):
    def buscar(self, q=""):
        return self.c.get("/pos/api/productos", query_string={"q": q}).get_json()

    def test_la_busqueda_trae_las_presentaciones_en_orden(self):
        self.lote(1, "L1", FUTURO, 10)
        p = [x for x in self.buscar("aceta")["productos"] if x["id"] == 1][0]
        self.assertEqual([(x["nombre"], x["factor"], x["precio"]) for x in p["presentaciones"]],
                         [("Unidad", 1, 1000), ("Sobre x 10", 10, 9000), ("Caja x 100", 100, 80000)])
        self.assertEqual(p["presentaciones"][0]["id"], 0)

    def test_escanear_el_codigo_del_sobre_elige_el_sobre(self):
        j = self.buscar("7700000000999")
        self.assertEqual(len(j["productos"]), 1)
        self.assertTrue(j["exacto"])
        self.assertEqual(j["presentacion_id"], self.p_sobre)

    def test_producto_sin_presentaciones_trae_solo_la_principal(self):
        p = [x for x in self.buscar("")["productos"] if x["id"] == 2][0]
        self.assertEqual(len(p["presentaciones"]), 1)
        self.assertEqual(p["presentaciones"][0]["nombre"], "Unidad")   # sin unidad elegida

    def test_la_ventana_i_trae_margen_por_presentacion(self):
        self.lote(1, "L1", FUTURO, 10)   # costo $100 por unidad
        info = self.c.get("/pos/api/producto/1").get_json()["producto"]
        caja = [x for x in info["presentaciones"] if x["nombre"] == "Caja x 100"][0]
        self.assertEqual(caja["margen"], 80000 - 100 * 100)


class TestFormularioProducto(BasePresentaciones):
    """Guardar presentaciones desde Productos > Editar."""

    def datos(self, **extra):
        base = {"codigo": "P1", "nombre": "Acetaminofén 500 mg", "iva_tipo": "excluido",
                "precio_venta": "1000", "unidad_venta_id": str(self.unidad), "maneja_vencimiento": "1"}
        base.update(extra)
        return base

    def guardar(self, filas):
        """filas = [(unidad_id, factor, precio, maximo, barras), ...]"""
        datos = self.datos()
        lista = list(datos.items())
        for f in filas:
            lista += [("pres_unidad_id", str(f[0])), ("pres_factor", str(f[1])), ("pres_precio", str(f[2])),
                      ("pres_maximo", str(f[3])), ("pres_barras", str(f[4]))]
        from werkzeug.datastructures import MultiDict
        md = MultiDict(lista)
        md["_csrf"] = __import__("test_fase0").TOKEN
        return self.c.post("/productos/1/editar", data=md, follow_redirects=True)

    def presentaciones(self):
        con = self.db()
        filas = con.execute("SELECT unidad_id, factor, precio_venta, codigo_barras FROM producto_presentaciones "
                            "WHERE producto_id = 1 ORDER BY factor").fetchall()
        con.close()
        return [tuple(f) for f in filas]

    def test_guarda_reemplaza_y_deja_bitacora(self):
        self.guardar([(self.sobre, 10, 8500, "", "111"), ("", "", "", "", "")])   # fila vacía se ignora
        self.assertEqual(self.presentaciones(), [(self.sobre, 10, 8500, "111")])
        bit = self.uno("SELECT detalle FROM bitacora WHERE accion = 'producto_editado' ORDER BY id DESC")
        self.assertIn("Sobre x 10", bit["detalle"])
        # Volver a guardar sin filas = se quitan todas
        self.guardar([])
        self.assertEqual(self.presentaciones(), [])

    def test_el_formulario_muestra_las_presentaciones(self):
        html = self.c.get("/productos/1/editar").get_data(as_text=True)
        self.assertIn('name="pres_factor"', html)
        self.assertIn('value="80000"', html)

    def test_validaciones(self):
        casos = [
            [(self.sobre, 1, 9000, "", "")],                    # factor debe ser > 1
            [(self.sobre, 10, 0, "", "")],                      # precio > 0
            [(self.sobre, 10, 9000, 8000, "")],                 # precio supera su máximo
            [(self.unidad, 10, 9000, "", "")],                  # misma unidad principal
            [(self.sobre, 10, 9000, "", ""), (self.sobre, 10, 9000, "", "")],  # repetida
            [("", 10, 9000, "", "")],                           # sin unidad
        ]
        antes = self.presentaciones()
        for filas in casos:
            self.guardar(filas)
            self.assertEqual(self.presentaciones(), antes, filas)

    def test_codigo_de_barras_de_otro_producto(self):
        con = self.db()
        con.execute("UPDATE productos SET codigo_barras = '555' WHERE id = 2")
        con.commit(); con.close()
        antes = self.presentaciones()
        self.guardar([(self.sobre, 10, 9000, "", "555")])
        self.assertEqual(self.presentaciones(), antes)


class TestConteoConCodigoDeCaja(BasePresentaciones):
    def test_escanear_la_caja_en_el_conteo_encuentra_el_producto(self):
        self.lote(1, "L1", FUTURO, 10)
        self.post(self.c, "/inventario/conteos/nuevo", {})
        j = self.c.get("/inventario/conteos/1/api/buscar", query_string={"q": "7700000000999"}).get_json()
        self.assertEqual([p["id"] for p in j["productos"]], [1])
