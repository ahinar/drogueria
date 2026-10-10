"""
PRUEBAS DE VENTA LIBRE Y OTROS INGRESOS

- Venta libre: cobrar en el POS algo que NO está en el inventario
  (inyectología, toma de presión...). No toca el stock.
- Otros ingresos: plata que entra y NO es venta (recargas, arriendo...).
  Desde el POS (si es efectivo entra a la caja) o desde Contabilidad.
- Ambos se ven en Utilidades y en el reporte R1 Ventas.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO

HOY = date.today().isoformat()
MES = HOY[:7]


def libre(descripcion="Inyectología", precio=5000, cantidad=1, iva=0, costo=None):
    """Una línea de venta libre como la manda el navegador."""
    return {"libre": 1, "descripcion": descripcion, "precio": precio, "cantidad": cantidad,
            "descuento_pct": 0, "iva_tarifa": iva, "costo": costo}


class BaseLibre(BaseVentas):
    def categoria_ingreso(self, nombre="Arriendo de espacios"):
        return self.uno("SELECT id FROM catalogos WHERE tipo = 'categoria_ingreso' AND nombre = ?",
                        nombre)["id"]

    def otro_ingreso_pos(self, monto=20000, forma="efectivo", descripcion="Comisión recargas"):
        return self.post(self.c, "/pos/api/otro-ingreso", {
            "categoria_id": self.categoria_ingreso("Comisiones (recargas, pagos de servicios)"),
            "descripcion": descripcion, "monto": monto, "forma_pago": forma})


# ======================================================================
# VENTA LIBRE
# ======================================================================

class TestVentaLibre(BaseLibre):
    def test_cobrar_venta_libre_sin_inventario(self):
        self.abrir_caja()
        r = self.cobrar([libre(precio=5000, cantidad=2)], recibido="10000")
        j = r.get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["total"], 10000)
        ln = self.uno("SELECT * FROM venta_lineas")
        self.assertEqual(ln["es_libre"], 1)
        self.assertIsNone(ln["producto_id"])            # no es un producto del inventario
        self.assertEqual(ln["producto_nombre"], "Inyectología")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM movimientos_inventario")["n"], 0)
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'venta_libre'"))

    def test_venta_mixta_producto_y_libre(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        j = self.cobrar([{"producto_id": 1, "cantidad": 2}, libre(precio=3000)]).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["total"], 2000 + 3000)
        self.assertEqual(self.stock(1), 8)                # solo baja el producto

    def test_iva_19_incluido(self):
        self.abrir_caja()
        self.cobrar([libre(precio=11900, iva=19)])
        ln = self.uno("SELECT subtotal, iva_valor, total, iva_tipo FROM venta_lineas")
        self.assertEqual((ln["subtotal"], ln["iva_valor"], ln["total"]), (10000, 1900, 11900))
        self.assertEqual(ln["iva_tipo"], "gravado")

    def test_validaciones(self):
        self.abrir_caja()
        for mala, texto in [(libre(descripcion="ab"), "qué se está vendiendo"),
                            (libre(precio=0), "mayor a cero"),
                            (libre(iva=7), "0, 5 o 19"),
                            (libre(costo=-1), "negativo")]:
            j = self.cobrar([mala]).get_json()
            self.assertFalse(j["ok"])
            self.assertIn(texto, j["error"])
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM ventas")["n"], 0)   # nada a medias

    def test_comprobante_muestra_la_venta_libre(self):
        self.abrir_caja()
        self.cobrar([libre(descripcion="Toma de presión", precio=2000)])
        self.assertIn("Toma de presión", self.c.get("/pos/venta/1").get_data(as_text=True))

    def test_anular_venta_con_libre(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 1}, libre()])
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "Error"})
        self.assertEqual(self.uno("SELECT estado FROM ventas")["estado"], "anulada")
        self.assertEqual(self.stock(1), 10)

    def test_la_venta_libre_no_se_devuelve(self):
        self.abrir_caja()
        self.cobrar([libre()])
        html = self.c.get("/devoluciones/cliente?venta=V-0001").get_data(as_text=True)
        self.assertIn("venta libre", html)
        self.assertNotIn('name="cant_1"', html)            # no hay casilla para devolverla

    def test_pos_tiene_boton_venta_libre(self):
        self.abrir_caja()
        html = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('id="btn-venta-libre"', html)
        self.assertIn('data-accion="otro-ingreso"', html)
        self.assertIn('id="categorias-ingreso"', html)


# ======================================================================
# OTROS INGRESOS
# ======================================================================

class TestOtrosIngresosPOS(BaseLibre):
    def test_en_efectivo_entra_a_la_caja(self):
        self.abrir_caja("10000")
        j = self.otro_ingreso_pos(20000).get_json()
        self.assertTrue(j["ok"], j)
        mov = self.uno("SELECT * FROM caja_movimientos")
        self.assertEqual((mov["tipo"], mov["monto"]), ("ingreso", 20000))
        r = self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "30000"})
        self.assertEqual(r.get_json()["diferencia"], 0)    # 10.000 de base + 20.000

    def test_por_nequi_no_toca_el_efectivo(self):
        self.abrir_caja()
        self.otro_ingreso_pos(15000, forma="nequi")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM caja_movimientos")["n"], 0)
        self.assertEqual(self.uno("SELECT origen FROM otros_ingresos")["origen"], "pos")

    def test_validaciones(self):
        self.abrir_caja()
        self.assertFalse(self.otro_ingreso_pos(0).get_json()["ok"])
        self.assertFalse(self.otro_ingreso_pos(descripcion="x").get_json()["ok"])
        r = self.post(self.c, "/pos/api/otro-ingreso", {"categoria_id": "999", "descripcion": "Algo",
                                                         "monto": 100, "forma_pago": "efectivo"})
        self.assertFalse(r.get_json()["ok"])

    def test_sin_caja_abierta_no_se_puede(self):
        self.assertEqual(self.otro_ingreso_pos().status_code, 400)


class TestOtrosIngresosContabilidad(BaseLibre):
    def nuevo(self, **cambios):
        datos = {"fecha": HOY, "categoria_id": self.categoria_ingreso(), "descripcion": "Arriendo de la vitrina",
                 "monto": "150000", "forma_pago": "transferencia"}
        datos.update(cambios)
        return self.post(self.c, "/contabilidad/ingresos/nuevo", datos)

    def test_hay_categorias_sembradas(self):
        self.assertGreaterEqual(self.uno("SELECT COUNT(*) n FROM catalogos WHERE tipo = 'categoria_ingreso'")["n"], 5)
        # y no dañaron la siembra de los demás catálogos
        self.assertIsNotNone(self.uno("SELECT 1 FROM catalogos WHERE tipo = 'uso' LIMIT 1"))

    def test_crear_listar_editar_y_anular(self):
        self.nuevo()
        ing = self.uno("SELECT * FROM otros_ingresos")
        self.assertEqual((ing["monto"], ing["origen"]), (150000, "ninguna"))
        html = self.c.get("/contabilidad/ingresos/").get_data(as_text=True)
        self.assertIn("Arriendo de la vitrina", html)
        self.assertIn("$150.000", html)
        self.post(self.c, f"/contabilidad/ingresos/{ing['id']}/editar",
                  {"fecha": HOY, "categoria_id": ing["categoria_id"], "descripcion": "Arriendo vitrina",
                   "monto": "160000", "forma_pago": "transferencia"})
        self.assertEqual(self.uno("SELECT monto FROM otros_ingresos")["monto"], 160000)
        self.post(self.c, f"/contabilidad/ingresos/{ing['id']}/anular")
        self.assertEqual(self.uno("SELECT activo FROM otros_ingresos")["activo"], 0)

    def test_validaciones(self):
        self.nuevo(monto="0")
        self.nuevo(descripcion="")
        self.nuevo(fecha="2999-01-01")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM otros_ingresos")["n"], 0)

    def test_el_del_pos_no_deja_cambiar_el_monto(self):
        self.abrir_caja()
        self.otro_ingreso_pos(20000)
        ing = self.uno("SELECT * FROM otros_ingresos")
        self.post(self.c, f"/contabilidad/ingresos/{ing['id']}/editar",
                  {"fecha": "2020-01-01", "categoria_id": ing["categoria_id"], "descripcion": "Recargas semana 2",
                   "monto": "999999", "forma_pago": "nequi"})
        nuevo = self.uno("SELECT * FROM otros_ingresos")
        self.assertEqual(nuevo["descripcion"], "Recargas semana 2")   # el texto sí cambia
        self.assertEqual((nuevo["monto"], nuevo["forma_pago"], nuevo["fecha"]),
                         (20000, "efectivo", ing["fecha"]))            # lo de la caja no

    def test_auxiliar_no_entra(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c = self.cliente()
        self.entrar(c, "aux")
        self.assertEqual(c.get("/contabilidad/ingresos/").status_code, 403)

    def test_contabilidad_muestra_el_total_del_mes(self):
        self.nuevo()
        html = self.c.get("/contabilidad/").get_data(as_text=True)
        self.assertIn("Otros ingresos de", html)
        self.assertIn("$150.000", html)


# ======================================================================
# REPORTES
# ======================================================================

class TestReportes(BaseLibre):
    def preparar(self):
        self.lote(1, "L1", FUTURO, 10)                       # costo 100 c/u
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 2}])     # $2.000, costo $200
        self.cobrar([libre(precio=5000, costo=800)])         # $5.000, costo $800
        self.otro_ingreso_pos(20000)

    def test_utilidades_suma_otros_ingresos_y_costo_libre(self):
        from app import utilidades
        self.preparar()
        with self.app.app_context():
            r = utilidades.calcular(date.today(), date.today())
        self.assertEqual(r["ventas"], 7000)
        self.assertEqual(r["ventas_libres"], 5000)
        self.assertEqual(r["costo"], 200 + 800)
        self.assertEqual(r["total_otros_ingresos"], 20000)
        self.assertEqual(r["utilidad_neta"], 7000 - 1000 + 20000)
        self.assertEqual(r["lineas_sin_costo"], 0)
        html = self.c.get(f"/reportes/utilidades?mes={MES}").get_data(as_text=True)
        self.assertIn("+ Otros ingresos: Comisiones", html)

    def test_r1_filtro_por_tipo(self):
        self.preparar()
        todo = self.c.get(f"/reportes/ventas?mes={MES}").get_data(as_text=True)
        self.assertIn("$7.000", todo)
        self.assertIn("Otros ingresos (no son ventas)", todo)
        self.assertIn("en venta libre", todo)               # composición productos / libre
        solo_libre = self.c.get(f"/reportes/ventas?mes={MES}&tipo=libre").get_data(as_text=True)
        self.assertIn("Solo venta libre", solo_libre)
        self.assertIn("$5.000", solo_libre)
        self.assertNotIn("$7.000", solo_libre)
        solo_prod = self.c.get(f"/reportes/ventas?mes={MES}&tipo=productos").get_data(as_text=True)
        self.assertIn("$2.000", solo_prod)

    def test_top_productos_no_incluye_venta_libre(self):
        self.preparar()
        html = self.c.get(f"/reportes/top?mes={MES}").get_data(as_text=True)
        self.assertNotIn("Inyectología", html)

    def test_sugerido_sigue_funcionando(self):
        self.preparar()
        self.assertEqual(self.c.get("/reportes/sugerido").status_code, 200)

    def test_inicio_no_falla(self):
        self.preparar()
        self.assertEqual(self.c.get("/").status_code, 200)
