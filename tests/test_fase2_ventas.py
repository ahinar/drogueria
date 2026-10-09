"""
PRUEBAS DE LA FASE 2.1: el carrito del POS (buscar, cobrar, FEFO, anular).

Cada test arma un mini-inventario de prueba y "vende" como lo haría el
navegador: mandando un carrito en formato JSON a /pos/api/cobrar.
Después revisa la base de datos para confirmar que todo quedó bien.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1, FECHA

FUTURO = (date.today() + timedelta(days=400)).isoformat()
FUTURO_CERCA = (date.today() + timedelta(days=60)).isoformat()
PASADO = (date.today() - timedelta(days=5)).isoformat()


class BaseVentas(BaseFase1):
    """Hereda el proveedor y los 2 productos (id 1 y 2) y les pone precio."""

    def setUp(self):
        super().setUp()
        con = self.db()
        # Producto 1: Acetaminofén, $1.000, excluido de IVA. Producto 2: Jeringa, $11.900, IVA 19 %.
        con.execute("UPDATE productos SET precio_venta = 1000, iva_tipo = 'excluido', iva_tarifa = 0 WHERE id = 1")
        con.execute("UPDATE productos SET precio_venta = 11900, iva_tipo = 'gravado', iva_tarifa = 19 WHERE id = 2")
        con.commit()
        con.close()

    def lote(self, producto_id, lote, vence, cantidad, estado="disponible"):
        con = self.db()
        con.execute(
            "INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
            "costo_unitario, estado, creado_en) VALUES (?,?,?,?,?,100,?,?)",
            (producto_id, lote, vence, cantidad, cantidad, estado, FECHA))
        con.commit()
        con.close()

    def abrir_caja(self, monto="10000"):
        # confirmar_sobregiro: la caja menor de pruebas está en $0 (ver BaseFase1.abrir)
        return self.post(self.c, "/pos/abrir-caja",
                         {"efectivo_inicial": monto, "confirmar_sobregiro": "1"})

    def cobrar(self, carrito, forma="efectivo", recibido="", cliente=None, cliente_obj=None):
        datos = {"carrito": json.dumps(carrito), "forma_pago": forma, "monto_recibido": recibido}
        return self.post(self.c, "/pos/api/cobrar", datos)

    def stock(self, producto_id):
        return self.uno("SELECT COALESCE(SUM(cantidad_disponible),0) n FROM lotes WHERE producto_id=?",
                        producto_id)["n"]


class TestCobrar(BaseVentas):
    def test_venta_simple_en_efectivo(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        r = self.cobrar([{"producto_id": 1, "cantidad": 3}], recibido="5000")
        j = r.get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual((j["total"], j["cambio"], j["consecutivo"]), (3000, 2000, "V-0001"))
        self.assertEqual(self.stock(1), 97)
        mov = self.uno("SELECT * FROM movimientos_inventario WHERE tipo = 'venta'")
        self.assertEqual(mov["cantidad"], -3)  # sale mercancía = negativo

    def test_consecutivos_aumentan(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 1}])
        j = self.cobrar([{"producto_id": 1, "cantidad": 1}]).get_json()
        self.assertEqual(j["consecutivo"], "V-0002")

    def test_fefo_vende_primero_el_lote_que_vence_antes(self):
        self.lote(1, "LARGO", FUTURO, 10)         # vence lejos
        self.lote(1, "CORTO", FUTURO_CERCA, 10)   # vence primero
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 14}])
        corto = self.uno("SELECT cantidad_disponible n FROM lotes WHERE lote='CORTO'")["n"]
        largo = self.uno("SELECT cantidad_disponible n FROM lotes WHERE lote='LARGO'")["n"]
        self.assertEqual((corto, largo), (0, 6))   # 10 del corto + 4 del largo
        linea = self.uno("SELECT lotes_json FROM venta_lineas")
        self.assertEqual(len(json.loads(linea["lotes_json"])), 2)

    def test_no_vende_lotes_vencidos_bloqueados_ni_en_cuarentena(self):
        self.lote(1, "VENCIDO", PASADO, 50)
        self.lote(1, "BLOQ", FUTURO, 50, estado="bloqueado")
        self.lote(1, "CUAR", FUTURO, 50, estado="cuarentena")
        self.lote(1, "BUENO", FUTURO, 5)
        self.abrir_caja()
        r = self.cobrar([{"producto_id": 1, "cantidad": 6}])   # solo 5 son vendibles
        self.assertFalse(r.get_json()["ok"])
        self.assertTrue(self.cobrar([{"producto_id": 1, "cantidad": 5}]).get_json()["ok"])

    def test_stock_insuficiente_no_guarda_nada(self):
        """Carrito de 2 líneas: la 2.ª falla -> la 1.ª tampoco debe quedar registrada."""
        self.lote(1, "L1", FUTURO, 100)
        self.lote(2, "L2", FUTURO, 2)
        self.abrir_caja()
        r = self.cobrar([{"producto_id": 1, "cantidad": 10}, {"producto_id": 2, "cantidad": 5}])
        self.assertFalse(r.get_json()["ok"])
        self.assertEqual(self.stock(1), 100)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM ventas")["n"], 0)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM movimientos_inventario")["n"], 0)

    def test_sin_caja_abierta(self):
        self.lote(1, "L1", FUTURO, 10)
        self.assertEqual(self.cobrar([{"producto_id": 1, "cantidad": 1}]).status_code, 400)

    def test_datos_invalidos(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        for carrito in ([], [{"producto_id": 1, "cantidad": 0}], [{"producto_id": 1, "cantidad": -2}],
                        [{"producto_id": 1, "cantidad": 1, "descuento_pct": 101}],
                        [{"producto_id": 999, "cantidad": 1}], [{"producto_id": "x", "cantidad": 1}]):
            self.assertFalse(self.cobrar(carrito).get_json()["ok"], carrito)
        self.assertFalse(self.cobrar([{"producto_id": 1, "cantidad": 1}], forma="bitcoin").get_json()["ok"])
        self.assertEqual(self.stock(1), 10)

    def test_efectivo_insuficiente_se_rechaza_sin_cambios(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        r = self.cobrar([{"producto_id": 1, "cantidad": 5}], recibido="4000")
        self.assertFalse(r.get_json()["ok"])
        self.assertEqual(self.stock(1), 10)

    def test_el_precio_lo_pone_el_servidor_no_el_navegador(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 2, "precio": 1, "precio_unitario": 1}]).get_json()
        self.assertEqual(j["total"], 2000)   # 2 x $1.000 reales, ignora el "precio" falso

    def test_iva_incluido_en_el_precio(self):
        self.lote(2, "L2", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": 2, "cantidad": 1}])
        v = self.uno("SELECT * FROM ventas")
        self.assertEqual((v["subtotal"], v["iva"], v["total"]), (10000, 1900, 11900))

    def test_descuento_porcentaje(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 10, "descuento_pct": 10}]).get_json()
        self.assertEqual(j["total"], 9000)
        self.assertEqual(self.uno("SELECT descuento d FROM ventas")["d"], 1000)

    def test_control_especial_se_bloquea(self):
        con = self.db()
        con.execute("UPDATE productos SET control_especial = 1 WHERE id = 1")
        con.commit(); con.close()
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        self.assertFalse(self.cobrar([{"producto_id": 1, "cantidad": 1}]).get_json()["ok"])

    def test_pago_nequi_no_da_cambio(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 2}], forma="nequi").get_json()
        self.assertEqual(j["cambio"], 0)

    def test_cierre_de_caja_suma_ventas_en_efectivo(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja("10000")
        self.cobrar([{"producto_id": 1, "cantidad": 3}])                 # efectivo 3.000
        self.cobrar([{"producto_id": 1, "cantidad": 2}], forma="nequi")  # NO es efectivo
        r = self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "13000"})
        self.assertEqual(r.get_json()["diferencia"], 0)   # esperado = 10.000 + 3.000

    def test_auditoria_registra_la_venta(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 1}])
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'venta_creada'"))


class TestCambioDePrecio(BaseVentas):
    """Opción B: cualquier cajero puede cambiar el precio, con motivo, y queda en bitácora."""

    def test_cambio_con_motivo_se_cobra_y_se_registra(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 2, "precio_nuevo": 800,
                          "motivo_precio": "Cliente frecuente"}]).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["total"], 1600)   # 2 x $800, no 2 x $1.000
        linea = self.uno("SELECT precio_unitario, precio_original, motivo_precio FROM venta_lineas")
        self.assertEqual((linea["precio_unitario"], linea["precio_original"]), (800, 1000))
        self.assertEqual(linea["motivo_precio"], "Cliente frecuente")
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'venta_precio_modificado'"))

    def test_sin_motivo_se_rechaza_y_no_guarda_nada(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 1, "precio_nuevo": 800}]).get_json()
        self.assertFalse(j["ok"])
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM ventas")["n"], 0)
        self.assertEqual(self.stock(1), 10)

    def test_no_se_puede_superar_el_precio_maximo(self):
        con = self.db()
        con.execute("UPDATE productos SET precio_maximo = 1200 WHERE id = 1")
        con.commit()
        con.close()
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 1, "precio_nuevo": 1500,
                          "motivo_precio": "prueba"}]).get_json()
        self.assertFalse(j["ok"])
        ok = self.cobrar([{"producto_id": 1, "cantidad": 1, "precio_nuevo": 1200,
                           "motivo_precio": "prueba"}]).get_json()
        self.assertTrue(ok["ok"], ok)   # justo en el tope sí se permite

    def test_precio_nuevo_igual_al_original_no_cuenta_como_cambio(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 1, "precio_nuevo": 1000}]).get_json()
        self.assertTrue(j["ok"], j)   # no pide motivo porque el precio no cambió
        self.assertIsNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'venta_precio_modificado'"))
        self.assertIsNone(self.uno("SELECT motivo_precio FROM venta_lineas")["motivo_precio"])

    def test_precio_nuevo_invalido(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        for malo in ("abc", 0, -5):
            j = self.cobrar([{"producto_id": 1, "cantidad": 1, "precio_nuevo": malo,
                              "motivo_precio": "prueba"}]).get_json()
            self.assertFalse(j["ok"], malo)


class TestInfoProducto(BaseVentas):
    """Botón "i" del POS: datos del producto y sus lotes vendibles."""

    def test_info_trae_datos_y_solo_lotes_vendibles(self):
        self.lote(1, "BUENO", FUTURO, 7)
        self.lote(1, "VENCIDO", PASADO, 50)
        self.lote(1, "BLOQ", FUTURO, 50, estado="bloqueado")
        r = self.c.get("/pos/api/producto/1")
        self.assertEqual(r.status_code, 200)
        p = r.get_json()["producto"]
        self.assertEqual((p["id"], p["precio"], p["stock"]), (1, 1000, 7))
        self.assertEqual([l["lote"] for l in p["lotes"]], ["BUENO"])

    def test_info_de_producto_inexistente(self):
        self.assertEqual(self.c.get("/pos/api/producto/9999").status_code, 404)

    def test_costo_promedio_y_margen(self):
        """5 unid. a $400 + 5 a $600 = costo promedio $500; precio $1.000 -> margen $500 (50 %)."""
        con = self.db()
        for lote, costo in (("A", 400), ("B", 600)):
            con.execute("INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, "
                        "cantidad_disponible, costo_unitario, estado, creado_en) "
                        "VALUES (1, ?, ?, 5, 5, ?, 'disponible', ?)", (lote, FUTURO, costo, FECHA))
        con.commit()
        con.close()
        p = self.c.get("/pos/api/producto/1").get_json()["producto"]
        self.assertEqual((p["costo"], p["margen"], p["margen_pct"]), (500, 500, 50))

    def test_margen_se_calcula_sin_iva(self):
        """Jeringa $11.900 con IVA 19 % -> $10.000 sin IVA; costo $100 -> margen $9.900."""
        self.lote(2, "J1", FUTURO, 3)
        p = self.c.get("/pos/api/producto/2").get_json()["producto"]
        self.assertEqual((p["precio_sin_iva"], p["iva_valor"], p["margen"]), (10000, 1900, 9900))

    def test_ultimas_4_compras_aprobadas(self):
        for n in range(5):   # 5 compras aprobadas: solo deben salir las 4 más recientes
            self.crear_recepcion([{"producto_id": 1, "lote": f"C{n}", "vencimiento": FUTURO,
                                   "cantidad_recibida": 10, "costo": 300 + n}], factura=f"F-{n}")
            self.post(self.c, f"/recepciones/{n + 1}/aprobar")
        self.crear_recepcion([{"producto_id": 1, "lote": "SIN", "vencimiento": FUTURO,
                               "cantidad_recibida": 10, "costo": 999}], factura="F-X")  # sin aprobar
        compras = self.c.get("/pos/api/producto/1").get_json()["producto"]["compras"]
        self.assertEqual(len(compras), 4)
        self.assertNotIn(999, [c["costo"] for c in compras])
        self.assertEqual(compras[0]["proveedor"], "Proveedor Prueba SAS")

    def test_cuenta_lotes_que_no_se_pueden_vender(self):
        self.lote(1, "V", PASADO, 3)
        self.lote(1, "Q", FUTURO, 3, estado="cuarentena")
        self.lote(1, "B", FUTURO, 3, estado="bloqueado")
        otros = self.c.get("/pos/api/producto/1").get_json()["producto"]["otros_lotes"]
        self.assertEqual(otros, {"cuarentena": 1, "bloqueados": 1, "vencidos": 1})


class TestEditarDesdePOS(BaseVentas):
    """Ventana "Editar" que se abre encima de la "i"."""

    def editar(self, cliente=None, **campos):
        datos = {"nombre": "Acetaminofén 500 mg", "precio_venta": "1000", "iva_tipo": "excluido"}
        datos.update(campos)
        return self.post(cliente or self.c, "/pos/api/producto/1/editar", datos)

    def test_guarda_cambios_y_deja_bitacora(self):
        r = self.editar(nombre="Acetaminofén 500 mg x 10", precio_venta="9.800",
                        precio_maximo="11200", codigo_barras="7707019379464",
                        requiere_formula="1")
        self.assertTrue(r.get_json()["ok"], r.get_json())
        p = self.uno("SELECT * FROM productos WHERE id = 1")
        self.assertEqual((p["nombre"], p["precio_venta"], p["precio_maximo"], p["requiere_formula"]),
                         ("Acetaminofén 500 mg x 10", 9800, 11200, 1))
        bit = self.uno("SELECT detalle FROM bitacora WHERE accion = 'producto_editado'")
        self.assertIn("precio_venta: 1000", bit["detalle"])

    def test_iva_gravado_exige_tarifa_y_excluido_la_pone_en_cero(self):
        self.assertFalse(self.editar(iva_tipo="gravado").get_json()["ok"])
        self.assertTrue(self.editar(iva_tipo="gravado", iva_tarifa="19").get_json()["ok"])
        self.assertEqual(self.uno("SELECT iva_tarifa t FROM productos WHERE id=1")["t"], 19)
        self.editar(iva_tipo="excluido", iva_tarifa="19")
        self.assertEqual(self.uno("SELECT iva_tarifa t FROM productos WHERE id=1")["t"], 0)

    def test_validaciones(self):
        self.assertFalse(self.editar(nombre="").get_json()["ok"])
        self.assertFalse(self.editar(precio_venta="0").get_json()["ok"])
        self.assertFalse(self.editar(precio_venta="abc").get_json()["ok"])
        self.assertFalse(self.editar(precio_venta="1500", precio_maximo="1200").get_json()["ok"])
        self.assertFalse(self.editar(control_especial="1").get_json()["ok"])  # sin INVIMA
        self.assertEqual(self.uno("SELECT precio_venta p FROM productos WHERE id=1")["p"], 1000)

    def test_codigo_de_barras_repetido(self):
        con = self.db()
        con.execute("UPDATE productos SET codigo_barras = '123' WHERE id = 2")
        con.commit()
        con.close()
        self.assertFalse(self.editar(codigo_barras="123").get_json()["ok"])

    def test_auxiliar_no_puede_editar(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c2 = self.cliente()
        self.entrar(c2, "aux")
        self.assertEqual(self.editar(cliente=c2, precio_venta="5").status_code, 403)
        self.assertEqual(self.uno("SELECT precio_venta p FROM productos WHERE id=1")["p"], 1000)


class TestAnular(BaseVentas):
    def vender(self):
        self.lote(1, "CORTO", FUTURO_CERCA, 5)
        self.lote(1, "LARGO", FUTURO, 5)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 7}])

    def test_anular_devuelve_stock_a_los_mismos_lotes(self):
        self.vender()
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "Error del cajero"})
        self.assertEqual(self.uno("SELECT estado FROM ventas")["estado"], "anulada")
        self.assertEqual(self.uno("SELECT cantidad_disponible n FROM lotes WHERE lote='CORTO'")["n"], 5)
        self.assertEqual(self.uno("SELECT cantidad_disponible n FROM lotes WHERE lote='LARGO'")["n"], 5)

    def test_anular_dos_veces_no_duplica_stock(self):
        self.vender()
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "x"})
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "x"})
        self.assertEqual(self.stock(1), 10)

    def test_anular_exige_motivo(self):
        self.vender()
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "  "})
        self.assertEqual(self.uno("SELECT estado FROM ventas")["estado"], "completada")

    def test_venta_anulada_no_cuenta_en_el_cierre(self):
        self.vender()
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "x"})
        r = self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "10000"})
        self.assertEqual(r.get_json()["diferencia"], 0)

    def test_no_se_anula_en_caja_cerrada(self):
        self.vender()
        self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "17000"})
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "x"})
        self.assertEqual(self.uno("SELECT estado FROM ventas")["estado"], "completada")

    def test_auxiliar_no_puede_anular(self):
        self.vender()
        self.crear_usuario(self.c, "aux", "auxiliar")
        c2 = self.cliente()
        self.entrar(c2, "aux")
        self.assertEqual(self.post(c2, "/pos/venta/1/anular", {"motivo": "x"}).status_code, 403)


class TestBuscarYComprobante(BaseVentas):
    def buscar(self, q="", cat=""):
        return self.c.get("/pos/api/productos", query_string={"q": q, "cat": cat}).get_json()

    def test_busqueda_por_nombre_y_stock_ignora_vencidos(self):
        self.lote(1, "VIEJO", PASADO, 100)
        self.lote(1, "BUENO", FUTURO, 7)
        j = self.buscar("aceta")
        self.assertEqual([p["nombre"] for p in j["productos"]], ["Acetaminofén 500 mg"])
        self.assertEqual(j["productos"][0]["stock"], 7)

    def test_codigo_de_barras_exacto(self):
        con = self.db()
        con.execute("UPDATE productos SET codigo_barras = '7701234567890' WHERE id = 2")
        con.commit(); con.close()
        j = self.buscar("7701234567890")
        self.assertTrue(j["exacto"])
        self.assertEqual(j["productos"][0]["id"], 2)

    def test_producto_inactivo_no_aparece(self):
        con = self.db()
        con.execute("UPDATE productos SET activo = 0 WHERE id = 2")
        con.commit(); con.close()
        self.assertEqual(len(self.buscar("")["productos"]), 1)

    def test_comprobante_y_lista_de_ventas(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 2}])
        r = self.c.get("/pos/venta/1")
        self.assertEqual(r.status_code, 200)
        self.assertIn("V-0001", r.get_data(as_text=True))
        self.assertEqual(self.c.get("/pos/venta/ultima", follow_redirects=True).status_code, 200)
        self.assertIn("V-0001", self.c.get("/pos/ventas").get_data(as_text=True))
        self.assertEqual(self.c.get("/pos/venta/999").status_code, 404)


class TestPantallaPOS(BaseVentas):
    def test_pantalla_del_pos_carga_con_caja_abierta(self):
        """Verifica que la página del POS se arma completa (carrito, modal de pago y scripts)."""
        self.abrir_caja()
        r = self.c.get("/pos/")
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        for pieza in ("pos_carrito.js", 'id="modal-pago"', 'id="url-api-cobrar"', 'id="url-inventario"'):
            self.assertIn(pieza, html)


class TestInicio(BaseVentas):
    def test_boton_vender_lleva_al_pos_real(self):
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn('href="/pos/"', html)
        self.assertNotIn("en construcción", html.lower())

    def test_pos_sin_barra_final_redirige_al_pos(self):
        r = self.c.get("/pos")
        self.assertIn(r.status_code, (301, 302, 307, 308))
        self.assertTrue(r.headers["Location"].endswith("/pos/"))

    def test_ventas_del_dia_en_el_inicio(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 3}])    # $3.000
        self.cobrar([{"producto_id": 1, "cantidad": 2}])    # $2.000 (se anulará)
        self.post(self.c, "/pos/venta/2/anular", {"motivo": "prueba"})
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("$3,000", html.replace("$3.000", "$3,000"))   # solo cuenta la venta válida
        self.assertIn("1 venta hoy", html)
