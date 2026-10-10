"""
PRUEBAS DE UNIDADES: unidad de inventario fija, venta por defecto en el POS,
asistente para cambiar la unidad (corregir o convertir), recepciones por
caja/sobre e importador con presentaciones.

El caso real que originó todo (Fernando, 2026-10-10): acetaminofén con 308
TABLETAS; cambió "Se vende por" a Sobre x 10 y el programa leyó 308 SOBRES;
vendió 2 sobres y el inventario quedó en 306 en vez de 288.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO, FECHA


class BaseUnidades(BaseVentas):
    """Producto 1 (Acetaminofén): unidad de inventario Tableta a $200,
    Sobre x 10 a $1.800 y Caja x 100 a $15.000."""

    def setUp(self):
        super().setUp()
        con = self.db()
        ids = {}
        for nombre, cantidad in (("Tableta", 1), ("Sobre x 10", 10), ("Caja x 100", 100)):
            ids[nombre] = con.execute(
                "INSERT INTO unidades_medida (nombre, cantidad, activo, creado_en) VALUES (?,?,1,?) "
                "ON CONFLICT(nombre) DO UPDATE SET cantidad = excluded.cantidad RETURNING id",
                (nombre, cantidad, FECHA)).fetchone()[0]
        self.u = ids
        con.execute("UPDATE productos SET unidad_venta_id = ?, precio_venta = 200 WHERE id = 1", (ids["Tableta"],))
        for nombre, factor, precio in (("Sobre x 10", 10, 1800), ("Caja x 100", 100, 15000)):
            con.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, creado_en) "
                        "VALUES (1,?,?,?,?)", (ids[nombre], factor, precio, FECHA))
        con.commit()
        con.close()

    def ficha(self, **cambios):
        """Envía la ficha del producto 1 con sus presentaciones actuales."""
        datos = {"codigo": "P00001", "nombre": "Acetaminofén 500 mg", "precio_venta": "200",
                 "precio_compra": "0", "iva_tipo": "excluido", "unidad_venta_id": str(self.u["Tableta"]),
                 "pres_unidad_id": [str(self.u["Sobre x 10"]), str(self.u["Caja x 100"])],
                 "pres_factor": ["10", "100"], "pres_precio": ["1800", "15000"],
                 "pres_maximo": ["", ""], "pres_barras": ["", ""]}
        datos.update(cambios)
        return self.post(self.c, "/productos/1/editar", datos)


class TestFicha(BaseUnidades):
    def test_sin_movimientos_la_unidad_se_puede_cambiar(self):
        self.ficha(unidad_venta_id=str(self.u["Sobre x 10"]),
                   pres_unidad_id=[str(self.u["Caja x 100"])], pres_factor=["10"], pres_precio=["15000"],
                   pres_maximo=[""], pres_barras=[""])
        self.assertEqual(self.uno("SELECT unidad_venta_id FROM productos WHERE id = 1")[0], self.u["Sobre x 10"])

    def test_con_existencias_la_unidad_queda_bloqueada(self):
        self.lote(1, "L1", FUTURO, 308)
        html = self.c.get("/productos/1/editar").get_data(as_text=True)
        self.assertIn("Bloqueada porque ya tiene existencias", html)
        self.assertIn("/productos/1/cambiar-unidad", html)
        # Aunque alguien mande el cambio a la fuerza, el servidor no lo acepta
        self.ficha(unidad_venta_id=str(self.u["Sobre x 10"]), pres_unidad_id=[str(self.u["Caja x 100"])],
                   pres_factor=["10"], pres_precio=["15000"], pres_maximo=[""], pres_barras=[""])
        self.assertEqual(self.uno("SELECT unidad_venta_id FROM productos WHERE id = 1")[0], self.u["Tableta"])

    def test_vender_por_defecto_como_sobre(self):
        self.ficha(venta_defecto_unidad_id=str(self.u["Sobre x 10"]))
        self.assertEqual(self.uno("SELECT venta_defecto_unidad_id FROM productos WHERE id = 1")[0],
                         self.u["Sobre x 10"])
        # Una unidad que no es del producto no se acepta
        otra = self.uno("SELECT id FROM unidades_medida WHERE nombre = 'Unidad'")[0]
        self.ficha(venta_defecto_unidad_id=str(otra))
        self.assertEqual(self.uno("SELECT venta_defecto_unidad_id FROM productos WHERE id = 1")[0],
                         self.u["Sobre x 10"])


class TestPOS(BaseUnidades):
    def test_el_caso_de_fernando_ya_no_pasa(self):
        """308 tabletas, vende 2 sobres -> quedan 288 (no 306)."""
        self.lote(1, "L1", FUTURO, 308)
        self.ficha(venta_defecto_unidad_id=str(self.u["Sobre x 10"]))
        p = self.c.get("/pos/api/productos?q=Acetamin").get_json()["productos"][0]
        sobre = next(x for x in p["presentaciones"] if x["nombre"] == "Sobre x 10")
        self.assertEqual(p["presentacion_defecto"], sobre["id"])        # el POS agrega el sobre al tocar
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "presentacion_id": sobre["id"], "cantidad": 2}])
        self.assertEqual(self.stock(1), 288)

    def test_sin_defecto_es_la_unidad_de_inventario(self):
        p = self.c.get("/pos/api/productos?q=Acetamin").get_json()["productos"][0]
        self.assertEqual(p["presentacion_defecto"], 0)


class TestAsistente(BaseUnidades):
    def preparar_error_de_fernando(self):
        """Reproduce el daño: la unidad dice 'Sobre x 10' pero los 308 eran tabletas."""
        self.lote(1, "L1", FUTURO, 308)
        con = self.db()
        con.execute("DELETE FROM producto_presentaciones WHERE unidad_id = ?", (self.u["Sobre x 10"],))
        con.execute("UPDATE productos SET unidad_venta_id = ? WHERE id = 1", (self.u["Sobre x 10"],))
        con.commit()
        con.close()

    def test_corregir_solo_el_nombre(self):
        self.preparar_error_de_fernando()
        self.post(self.c, "/productos/1/cambiar-unidad", {"unidad_id": self.u["Tableta"], "modo": "corregir"})
        self.assertEqual(self.uno("SELECT unidad_venta_id FROM productos WHERE id = 1")[0], self.u["Tableta"])
        self.assertEqual(self.stock(1), 308)                               # no se tocó ningún número
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'producto_unidad_cambiada'"))

    def test_convertir_de_caja_a_tableta(self):
        """3 cajas de 100 a $25.000 -> 300 tabletas a $250; la caja queda como presentación."""
        con = self.db()
        con.execute("DELETE FROM producto_presentaciones WHERE producto_id = 1")
        con.execute("UPDATE productos SET unidad_venta_id = ?, precio_venta = 30000, stock_minimo = 2 WHERE id = 1",
                    (self.u["Caja x 100"],))
        con.execute("INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
                    "costo_unitario, estado, creado_en) VALUES (1, 'L1', ?, 3, 3, 25000, 'disponible', ?)",
                    (FUTURO, FECHA))
        con.commit()
        con.close()
        self.post(self.c, "/productos/1/cambiar-unidad", {"unidad_id": self.u["Tableta"], "modo": "convertir",
                                                          "factor": "100", "precio": "350"})
        lote = self.uno("SELECT * FROM lotes")
        self.assertEqual((lote["cantidad_disponible"], lote["costo_unitario"]), (300, 250))
        prod = self.uno("SELECT * FROM productos WHERE id = 1")
        self.assertEqual((prod["unidad_venta_id"], prod["precio_venta"], prod["stock_minimo"]),
                         (self.u["Tableta"], 350, 200))
        caja = self.uno("SELECT * FROM producto_presentaciones WHERE producto_id = 1")
        self.assertEqual((caja["unidad_id"], caja["factor"], caja["precio_venta"]), (self.u["Caja x 100"], 100, 30000))
        self.assertEqual(prod["venta_defecto_unidad_id"], self.u["Caja x 100"])   # el POS sigue vendiendo cajas

    def test_no_deja_convertir_a_una_unidad_mas_grande(self):
        self.lote(1, "L1", FUTURO, 10)
        self.post(self.c, "/productos/1/cambiar-unidad", {"unidad_id": self.u["Caja x 100"] + 99, "modo": "convertir",
                                                          "factor": "0.5"})
        self.assertEqual(self.uno("SELECT unidad_venta_id FROM productos WHERE id = 1")[0], self.u["Tableta"])


class TestRecepcionPorCaja(BaseUnidades):
    def test_tres_cajas_son_300_tabletas(self):
        caja = self.uno("SELECT id FROM producto_presentaciones WHERE unidad_id = ?", self.u["Caja x 100"])[0]
        datos = {"proveedor_id": "1", "factura_numero": "F-1", "linea_producto_id": ["1"], "linea_lote": ["L9"],
                 "linea_vencimiento": [FUTURO], "linea_cantidad_recibida": ["3"], "linea_costo": ["25000"],
                 "linea_resultado": ["aceptado"], "linea_presentacion": [str(caja)]}
        self.post(self.c, "/recepciones/nueva", datos)
        linea = self.uno("SELECT * FROM recepcion_lineas")
        self.assertEqual((linea["cantidad_recibida"], linea["costo_unitario"], linea["presentacion"], linea["factor"]),
                         (300, 250, "Caja x 100", 100))
        self.post(self.c, "/recepciones/1/aprobar")
        self.assertEqual(self.stock(1), 300)
        html = self.c.get("/recepciones/1").get_data(as_text=True)
        self.assertIn("3 Caja x 100", html)
        self.assertIn("$25.000", html)

    def test_codigo_de_barras_de_la_caja(self):
        con = self.db()
        con.execute("UPDATE producto_presentaciones SET codigo_barras = '7700000000999' WHERE unidad_id = ?",
                    (self.u["Caja x 100"],))
        con.commit()
        con.close()
        j = self.c.get("/recepciones/api/buscar-barras?codigo=7700000000999").get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["producto"]["id"], 1)
        self.assertNotEqual(j["presentacion_id"], 0)


class TestImportador(BaseUnidades):
    def importar(self, filas):
        from app.importador import ENCABEZADOS
        import csv
        buffer = io.StringIO()
        w = csv.writer(buffer)
        w.writerow(ENCABEZADOS)
        for f in filas:
            w.writerow(f)
        self.post(self.c, "/productos/importar/previsualizar",
                  {"archivo": (io.BytesIO(buffer.getvalue().encode("utf-8")), "productos.csv")},
                  content_type="multipart/form-data")
        return self.post(self.c, "/productos/importar/confirmar")

    def fila(self, **valores):
        from app.importador import COLUMNAS
        return [valores.get(campo, "") for campo, _e, _ej in COLUMNAS]

    def test_con_presentaciones_y_venta_por_defecto(self):
        self.importar([self.fila(codigo="P10", nombre="Loratadina 10 mg", unidad_inventario="Tableta",
                                 precio_venta="300", pres2="Sobre x 10", pres2_trae="10", pres2_precio="2.500",
                                 pres3="Blíster x 12", pres3_trae="12", pres3_precio="3.200",
                                 vender_como="Sobre x 10")])
        p = self.uno("SELECT * FROM productos WHERE codigo = 'P10'")
        self.assertEqual(p["unidad_venta_id"], self.u["Tableta"])
        self.assertEqual(p["venta_defecto_unidad_id"], self.u["Sobre x 10"])
        pres = {r["nombre"]: (r["factor"], r["precio_venta"]) for r in self.db().execute(
            "SELECT u.nombre, pp.factor, pp.precio_venta FROM producto_presentaciones pp "
            "JOIN unidades_medida u ON u.id = pp.unidad_id WHERE pp.producto_id = ?", (p["id"],))}
        self.assertEqual(pres, {"Sobre x 10": (10, 2500), "Blíster x 12": (12, 3200)})   # 2.500 = dos mil quinientos
        self.assertEqual(self.uno("SELECT cantidad FROM unidades_medida WHERE nombre = 'Blíster x 12'")[0], 12)

    def test_presentacion_sin_precio_no_se_importa(self):
        self.importar([self.fila(codigo="P11", nombre="Mal", precio_venta="100", pres2="Caja x 100", pres2_trae="100")])
        self.assertIsNone(self.uno("SELECT 1 FROM productos WHERE codigo = 'P11'"))

    def test_numeros_con_punto_de_miles(self):
        from app.importador import _num
        self.assertEqual([_num("1.800"), _num("15.000"), _num("2,5"), _num("$ 1.200"), _num("0.5")],
                         [1800, 15000, 2.5, 1200, 0.5])

    def test_plantilla_trae_las_columnas_nuevas(self):
        r = self.c.get("/productos/importar/plantilla?formato=csv")
        texto = r.get_data().decode("utf-8-sig")
        self.assertIn("Unidad de inventario", texto)
        self.assertIn("Presentación 2 trae", texto)


# ======================================================================
# Pedido de Fernando (2026-10-10, 12:41): trabajar "por sobre" como en su POS,
# pero sin decimales. Ver las existencias en sobres, decidir si se vende
# suelto, y recibir cajas de cualquier tamaño.
# ======================================================================

class TestExistenciasComoSeVende(BaseUnidades):
    def test_texto(self):
        from app.presentaciones import texto_existencias
        op = [{"id": 0, "nombre": "Tableta", "factor": 1}, {"id": 7, "nombre": "Sobre x 10", "factor": 10}]
        self.assertEqual(texto_existencias(295, op, 7), "29 Sobre x 10 + 5 Tableta")
        self.assertEqual(texto_existencias(300, op, 7), "30 Sobre x 10")
        self.assertEqual(texto_existencias(295, op, 0), "295 Tableta")

    def test_lista_de_productos_y_kardex(self):
        self.lote(1, "L1", FUTURO, 295)
        self.ficha(venta_defecto_unidad_id=str(self.u["Sobre x 10"]))
        lista = self.c.get("/productos/?vista=lista").get_data(as_text=True)
        self.assertIn("29 Sobre x 10 + 5 Tableta", lista)
        self.assertIn("$1.800", lista)                       # precio de lo que se vende normalmente
        kardex = self.c.get("/inventario/kardex/1").get_data(as_text=True)
        self.assertIn("29 Sobre x 10 + 5 Tableta", kardex)


class TestNoSeVendeSuelto(BaseUnidades):
    def test_solo_por_sobre(self):
        self.lote(1, "L1", FUTURO, 300)
        self.ficha(vende_suelto_en_form="1", precio_venta="0")     # casilla "Se vende suelto" sin marcar
        prod = self.uno("SELECT * FROM productos WHERE id = 1")
        self.assertEqual(prod["vende_suelto"], 0)
        self.assertEqual(prod["venta_defecto_unidad_id"], self.u["Sobre x 10"])   # se escoge solo
        self.assertEqual(prod["precio_venta"], 180)                # $1.800 ÷ 10, calculado
        p = self.c.get("/pos/api/productos?q=Acetamin").get_json()["productos"][0]
        self.assertFalse(p["presentaciones"][0]["vendible"])        # la tableta no se ofrece
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "presentacion_id": 0, "cantidad": 5}])
        self.assertFalse(j.get_json()["ok"])
        self.assertIn("no se vende suelto", j.get_json()["error"])
        sobre = p["presentacion_defecto"]
        self.assertTrue(self.cobrar([{"producto_id": 1, "presentacion_id": sobre, "cantidad": 1}]).get_json()["ok"])
        self.assertEqual(self.stock(1), 290)

    def test_sin_presentaciones_no_se_puede(self):
        self.ficha(vende_suelto_en_form="1", pres_unidad_id=[], pres_factor=[], pres_precio=[],
                   pres_maximo=[], pres_barras=[])
        self.assertEqual(self.uno("SELECT vende_suelto FROM productos WHERE id = 1")[0], 1)   # no se guardó

    def test_por_defecto_se_vende_suelto(self):
        self.ficha()                                                # formularios viejos: sin la marca
        self.assertEqual(self.uno("SELECT vende_suelto FROM productos WHERE id = 1")[0], 1)


class TestRecepcionOtraCaja(BaseUnidades):
    def test_caja_x_300_que_no_esta_en_la_ficha(self):
        datos = {"proveedor_id": "1", "factura_numero": "F-2", "linea_producto_id": ["1"], "linea_lote": ["L9"],
                 "linea_vencimiento": [FUTURO], "linea_cantidad_recibida": ["1"], "linea_costo": ["36000"],
                 "linea_resultado": ["aceptado"], "linea_presentacion": ["otra"], "linea_factor_otro": ["300"]}
        self.post(self.c, "/recepciones/nueva", datos)
        linea = self.uno("SELECT * FROM recepcion_lineas")
        self.assertEqual((linea["cantidad_recibida"], linea["costo_unitario"], linea["presentacion"]),
                         (300, 120, "Caja x 300"))

    def test_otra_caja_sin_cantidad_no_se_guarda(self):
        datos = {"proveedor_id": "1", "factura_numero": "F-3", "linea_producto_id": ["1"], "linea_lote": ["L9"],
                 "linea_vencimiento": [FUTURO], "linea_cantidad_recibida": ["1"], "linea_costo": ["36000"],
                 "linea_resultado": ["aceptado"], "linea_presentacion": ["otra"], "linea_factor_otro": [""]}
        self.post(self.c, "/recepciones/nueva", datos)
        self.assertIsNone(self.uno("SELECT 1 FROM recepcion_lineas"))


class TestImportadorSuelto(TestImportador):
    def test_no_se_vende_suelto(self):
        self.importar([self.fila(codigo="P20", nombre="Ibuprofeno 400", unidad_inventario="Tableta",
                                 pres2="Sobre x 10", pres2_trae="10", pres2_precio="1.600", vende_suelto="NO")])
        p = self.uno("SELECT * FROM productos WHERE codigo = 'P20'")
        self.assertEqual((p["vende_suelto"], p["venta_defecto_unidad_id"], p["precio_venta"]),
                         (0, self.u["Sobre x 10"], 160))
