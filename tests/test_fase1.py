"""
PRUEBAS DE LA FASE 1 (Recepción técnica -> Lotes -> Kardex) Y DE LA CAJA DEL POS.

¿Para qué sirven los tests?
  Son "robots" que usan el programa como lo usaría una persona (abren páginas,
  llenan formularios, aprietan botones) y verifican que el resultado sea el
  correcto. Si algún día cambias algo y rompes una función, el test falla y te
  avisa ANTES de que el error llegue a tu droguería.

¿Cómo se corren?   python -m pytest tests -q
Cada test usa una base de datos temporal; NO toca tu base de datos real.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase0 import Base  # reutilizamos las ayudas (crear admin, login, etc.)

FECHA = "2026-10-07 10:00:00"


class BaseFase1(Base):
    """Prepara un proveedor y dos productos de ejemplo para todos los tests."""

    def setUp(self):
        super().setUp()
        self.c = self.admin_logueado()
        con = self.db()
        con.execute(
            "INSERT INTO proveedores (nit, razon_social, creado_en) VALUES ('900123456', 'Proveedor Prueba SAS', ?)",
            (FECHA,))
        for codigo, nombre, venc in (("P00001", "Acetaminofén 500 mg", 1), ("P00002", "Jeringa 5 ml", 0)):
            con.execute(
                "INSERT INTO productos (codigo, nombre, maneja_vencimiento, creado_en) VALUES (?,?,?,?)",
                (codigo, nombre, venc, FECHA))
        con.commit()
        con.close()

    def db(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def uno(self, sql, *args):
        con = self.db()
        try:
            return con.execute(sql, args).fetchone()
        finally:
            con.close()

    def crear_recepcion(self, lineas, factura="F-100"):
        """Llena el formulario de recepción. `lineas` es una lista de diccionarios."""
        datos = {"proveedor_id": "1", "factura_numero": factura}
        for campo in ("producto_id", "lote", "vencimiento", "cantidad_recibida", "costo", "resultado"):
            datos["linea_" + campo] = [str(l.get(campo, "")) for l in lineas]
        return self.post(self.c, "/recepciones/nueva", datos, follow_redirects=False)


class TestRecepcion(BaseFase1):
    def test_recepcion_valida_queda_en_cuarentena_sin_stock(self):
        r = self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                                   "cantidad_recibida": 100, "costo": 300}])
        self.assertEqual(r.status_code, 302)
        rec = self.uno("SELECT * FROM recepciones")
        self.assertEqual(rec["estado"], "cuarentena")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM lotes")["n"], 0)  # aún no hay lotes

    def test_aprobar_crea_lote_disponible_y_kardex(self):
        self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 100, "costo": 300}])
        self.post(self.c, "/recepciones/1/aprobar")
        lote = self.uno("SELECT * FROM lotes")
        self.assertEqual(lote["estado"], "disponible")
        self.assertEqual(lote["cantidad_disponible"], 100)
        mov = self.uno("SELECT * FROM movimientos_inventario")
        self.assertEqual((mov["tipo"], mov["cantidad"]), ("recepcion", 100))
        self.assertEqual(self.uno("SELECT estado FROM recepciones")["estado"], "aprobada")

    def test_aprobar_dos_veces_no_duplica_stock(self):
        self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 100, "costo": 300}])
        self.post(self.c, "/recepciones/1/aprobar")
        self.post(self.c, "/recepciones/1/aprobar")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM lotes")["n"], 1)

    def test_linea_rechazada_no_suma_stock(self):
        self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 50, "costo": 300, "resultado": "rechazado"}])
        self.post(self.c, "/recepciones/1/aprobar")
        self.assertEqual(self.uno("SELECT COALESCE(SUM(cantidad_disponible),0) n FROM lotes")["n"], 0)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM movimientos_inventario")["n"], 0)

    def test_linea_en_cuarentena_no_debe_quedar_disponible(self):
        """Regla del proyecto: 'solo lo aceptado genera lotes disponibles'."""
        self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 50, "costo": 300, "resultado": "cuarentena"}])
        self.post(self.c, "/recepciones/1/aprobar")
        lote = self.uno("SELECT * FROM lotes")
        self.assertNotEqual(lote["estado"], "disponible")

    def test_liberar_cuarentena_la_hace_disponible_y_anota_kardex(self):
        self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 50, "costo": 300, "resultado": "cuarentena"}])
        self.post(self.c, "/recepciones/1/aprobar")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM movimientos_inventario")["n"], 0)
        self.post(self.c, "/inventario/lotes/1/liberar")
        self.assertEqual(self.uno("SELECT estado FROM lotes")["estado"], "disponible")
        self.assertEqual(self.uno("SELECT cantidad FROM movimientos_inventario")["cantidad"], 50)
        # liberar otra vez no debe duplicar el kardex
        self.post(self.c, "/inventario/lotes/1/liberar")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM movimientos_inventario")["n"], 1)

    def test_exige_factura_o_remision(self):
        datos = {"proveedor_id": "1", "linea_producto_id": ["1"], "linea_lote": ["L1"],
                 "linea_vencimiento": ["2028-05-01"], "linea_cantidad_recibida": ["10"], "linea_costo": ["300"]}
        self.post(self.c, "/recepciones/nueva", datos)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM recepciones")["n"], 0)

    def test_exige_al_menos_una_linea(self):
        self.post(self.c, "/recepciones/nueva", {"proveedor_id": "1", "factura_numero": "F-1"})
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM recepciones")["n"], 0)

    def test_rechaza_cantidad_cero_o_costo_cero(self):
        """Regla del proyecto: cantidad > 0 y costo > 0."""
        self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 0, "costo": 300}])
        self.crear_recepcion([{"producto_id": 1, "lote": "L2", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 10, "costo": 0}], factura="F-2")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM recepciones")["n"], 0)

    def test_producto_con_vencimiento_exige_lote_y_fecha(self):
        """Regla del proyecto: si maneja vencimiento, lote y vencimiento son obligatorios."""
        self.crear_recepcion([{"producto_id": 1, "lote": "", "vencimiento": "",
                               "cantidad_recibida": 10, "costo": 300}])
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM recepciones")["n"], 0)

    def test_acta_pdf_se_genera(self):
        self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 100, "costo": 300}])
        r = self.c.get("/recepciones/1/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"%PDF"))

    def test_auxiliar_no_puede_aprobar(self):
        self.crear_recepcion([{"producto_id": 1, "lote": "L1", "vencimiento": "2028-05-01",
                               "cantidad_recibida": 100, "costo": 300}])
        self.crear_usuario(self.c, "aux", "auxiliar")
        c2 = self.cliente()
        self.entrar(c2, "aux")
        r = self.post(c2, "/recepciones/1/aprobar")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.uno("SELECT estado FROM recepciones")["estado"], "cuarentena")


class TestCaja(BaseFase1):
    def abrir(self, monto="50000"):
        return self.post(self.c, "/pos/abrir-caja", {"efectivo_inicial": monto})

    def mov(self, tipo, monto, forma="efectivo"):
        return self.post(self.c, "/pos/api/movimiento", {"tipo": tipo, "monto": monto, "forma_pago": forma, "motivo": "prueba"})

    def test_abrir_caja_y_solo_una_a_la_vez(self):
        self.abrir()
        self.abrir()
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM cajas")["n"], 1)
        self.assertEqual(self.uno("SELECT efectivo_inicial e FROM cajas")["e"], 50000)

    def test_movimientos_validan_datos(self):
        self.abrir()
        self.assertEqual(self.mov("ingreso", "10000").status_code, 200)
        self.assertEqual(self.mov("ingreso", "0").status_code, 400)
        self.assertEqual(self.mov("ingreso", "-5").status_code, 400)
        self.assertEqual(self.mov("robo", "100").status_code, 400)
        self.assertEqual(self.mov("ingreso", "100", "bitcoin").status_code, 400)

    def test_movimiento_sin_caja_abierta_se_rechaza(self):
        self.assertEqual(self.mov("ingreso", "1000").status_code, 400)

    def test_cierre_calcula_efectivo_esperado_y_diferencia(self):
        self.abrir("50000")
        self.mov("ingreso", "20000")
        self.mov("salida", "5000")
        self.mov("ingreso", "99999", "nequi")  # Nequi NO debe contar como efectivo
        # esperado en efectivo = 50.000 + 20.000 - 5.000 = 65.000
        r = self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "64000"})
        self.assertEqual(r.get_json()["diferencia"], -1000)
        caja = self.uno("SELECT * FROM cajas")
        self.assertEqual(caja["estado"], "cerrada")

    def test_cierre_con_denominaciones(self):
        self.abrir("0")
        r = self.post(self.c, "/pos/api/cerrar-caja", {"denominaciones": '{"50000": 2, "1000": 3}'})
        self.assertEqual(r.get_json()["diferencia"], 103000)  # contó 103.000, esperado 0

    def test_despues_de_cerrar_se_puede_abrir_otra(self):
        self.abrir()
        self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "50000"})
        self.abrir()
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM cajas")["n"], 2)


class TestBitacora(BaseFase1):
    def test_bitacora_no_se_puede_borrar_ni_editar(self):
        self.abrir = None
        con = self.db()
        con.execute("INSERT INTO bitacora (fecha, accion) VALUES (?, 'prueba')", (FECHA,))
        con.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("DELETE FROM bitacora")
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("UPDATE bitacora SET accion = 'x'")
        con.close()
