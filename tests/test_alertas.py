"""
PRUEBAS DEL PANEL DE ALERTAS DEL INICIO ("Para atender hoy").

Cada prueba crea una situación (un lote vencido, un precio por encima del
máximo, etc.) y revisa que el Inicio muestre la alerta correcta.
Las alertas se reconocen en el HTML por su data-clave="...".
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import FECHA
from test_fase2_ventas import BaseVentas, FUTURO

HOY = date.today()
dias = lambda n: (HOY + timedelta(days=n)).isoformat()


class BaseAlertas(BaseVentas):
    def inicio(self, cliente=None):
        return (cliente or self.c).get("/").get_data(as_text=True)

    def claves(self, cliente=None):
        """Lista de claves de alerta que aparecen en el Inicio, en orden."""
        import re
        return re.findall(r'data-clave="([a-z_]+)"', self.inicio(cliente))

    def sql(self, consulta, *args):
        con = self.db()
        con.execute(consulta, args)
        con.commit()
        con.close()

    def auxiliar(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c = self.cliente()
        self.post(c, "/login", {"usuario": "aux", "clave": "clave1234"})
        return c


class TestPanelAlertas(BaseAlertas):
    def test_sin_problemas_dice_todo_en_orden(self):
        html = self.inicio()
        self.assertIn("Todo en orden", html)
        self.assertEqual(self.claves(), [])

    def test_lote_vencido_con_unidades(self):
        self.lote(1, "VIEJO", dias(-3), 7)
        self.assertIn("lotes_vencidos", self.claves())
        self.assertIn("venció hace 3 días", self.inicio())

    def test_lote_vencido_sin_unidades_no_alerta(self):
        self.lote(1, "VIEJO", dias(-3), 0)
        self.assertNotIn("lotes_vencidos", self.claves())

    def test_lote_por_vencer(self):
        self.lote(1, "PRONTO", dias(10), 5)
        self.lote(1, "LEJOS", FUTURO, 5)
        html = self.inicio()
        self.assertIn("lotes_por_vencer", self.claves())
        self.assertIn("PRONTO", html)
        self.assertNotIn("lote LEJOS", html)

    def test_precio_por_encima_del_maximo(self):
        self.sql("UPDATE productos SET precio_maximo = 900 WHERE id = 1")   # vende a 1.000
        self.assertIn("precio_maximo", self.claves())
        self.assertIn("máximo $900", self.inicio())

    def test_precio_de_presentacion_por_encima_del_maximo(self):
        con = self.db()
        uid = con.execute("INSERT INTO unidades_medida (nombre, cantidad, activo, creado_en) "
                          "VALUES ('Caja x 10', 10, 1, ?)", (FECHA,)).lastrowid
        con.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                    "precio_maximo, creado_en) VALUES (1, ?, 10, 9000, 8500, ?)", (uid, FECHA))
        con.commit(); con.close()
        self.assertIn("precio_maximo", self.claves())
        self.assertIn("(Caja x 10)", self.inicio())

    def test_invima_vencido_y_por_vencer(self):
        self.sql("UPDATE productos SET registro_sanitario='INVIMA 2020M-1', registro_vence=? WHERE id=1", dias(-1))
        self.sql("UPDATE productos SET registro_sanitario='INVIMA 2021M-2', registro_vence=? WHERE id=2", dias(40))
        claves = self.claves()
        self.assertIn("invima_vencido", claves)
        self.assertIn("invima_por_vencer", claves)

    def test_invima_lejano_no_alerta(self):
        self.sql("UPDATE productos SET registro_vence=? WHERE id=1", dias(400))
        self.assertNotIn("invima_por_vencer", self.claves())

    def test_proveedor_concepto_vencido(self):
        self.sql("UPDATE proveedores SET concepto_vence = ? WHERE id = 1", dias(-10))
        self.assertIn("proveedor_vencido", self.claves())

    def test_agotado_y_bajo_minimo(self):
        self.sql("UPDATE productos SET stock_minimo = 10 WHERE id IN (1, 2)")
        self.lote(2, "L2", FUTURO, 4)          # producto 2: 4 de mínimo 10; producto 1: 0
        claves = self.claves()
        self.assertIn("agotados", claves)
        self.assertIn("stock_minimo", claves)
        self.assertIn("hay 4 · mínimo 10", self.inicio())

    def test_sin_stock_minimo_no_alerta_agotado(self):
        """Productos sin stock mínimo no llenan el panel aunque estén en cero."""
        self.assertNotIn("agotados", self.claves())

    def test_stock_vencido_no_cuenta_como_stock(self):
        self.sql("UPDATE productos SET stock_minimo = 5 WHERE id = 1")
        self.lote(1, "VIEJO", dias(-1), 100)
        self.assertIn("agotados", self.claves())

    def test_productos_sin_precio(self):
        self.sql("UPDATE productos SET precio_venta = 0 WHERE id = 2")
        self.assertIn("sin_precio", self.claves())

    def test_caja_abierta_de_ayer(self):
        self.abrir_caja()
        self.sql("UPDATE cajas SET abierta_en = ?", dias(-1) + " 08:00:00")
        self.assertIn("caja_vieja", self.claves())

    def test_rojas_primero(self):
        self.lote(1, "PRONTO", dias(5), 5)               # amarilla
        self.sql("UPDATE productos SET precio_maximo = 900 WHERE id = 1")   # roja
        claves = self.claves()
        self.assertLess(claves.index("precio_maximo"), claves.index("lotes_por_vencer"))

    def test_muestra_maximo_5_y_cuantos_faltan(self):
        for i in range(8):
            self.lote(1, f"V{i}", dias(-1 - i), 1)
        html = self.inicio()
        self.assertIn("… y 3 más.", html)


class TestAlertasPorRol(BaseAlertas):
    def test_auxiliar_no_ve_proveedores_ni_enlace_a_editar(self):
        self.sql("UPDATE proveedores SET concepto_vence = ? WHERE id = 1", dias(-10))
        self.sql("UPDATE productos SET precio_maximo = 900 WHERE id = 1")
        c = self.auxiliar()
        claves = self.claves(c)
        self.assertNotIn("proveedor_vencido", claves)
        self.assertIn("precio_maximo", claves)
        html = self.inicio(c)
        self.assertNotIn("/productos/1/editar", html)   # el auxiliar no puede editar
        self.assertIn("/inventario/kardex/1", html)      # va al kardex en su lugar

    def test_jefe_va_a_editar_el_producto(self):
        self.sql("UPDATE productos SET precio_maximo = 900 WHERE id = 1")
        self.assertIn("/productos/1/editar", self.inicio())


class TestResumenInicio(BaseAlertas):
    def test_jefe_ve_resumen_y_auxiliar_no(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 3}])
        html = self.inicio()
        self.assertIn("Ventas del mes", html)
        self.assertIn("Utilidad neta del mes", html)
        self.assertIn("$3.000", html)
        self.assertNotIn("Ventas del mes", self.inicio(self.auxiliar()))
