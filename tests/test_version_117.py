"""
PRUEBAS DE LA VERSIÓN 1.1.7
===========================
  - TestRecepcionUnaLinea: las líneas de la recepción en una sola fila.
  - TestBancos: saldo de Nequi y Davivienda armado solo con ventas, gastos, abonos...;
    traslados, plata del dueño y cuadre con la app del banco.
  - TestCuentasPorPagar: factura a crédito o de contado, pagos desde cada lugar,
    anular, facturas viejas «por revisar», recepción rechazada, dashboard y alerta.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import FUTURO, BaseVentas

HOY = date.today().isoformat()


class Base117(BaseVentas):
    def saldo(self, clave):
        """Saldo de una cuenta calculado por app/bancos.py (con una conexión de prueba)."""
        from app import bancos
        con = self.db()
        from app.nombres import registrar_en
        registrar_en(con)
        try:
            c = con.execute("SELECT * FROM cuentas_bancarias WHERE clave = ?", (clave,)).fetchone()
            return round(bancos.saldo(con, c))
        finally:
            con.close()

    def caja_menor(self):
        from app.caja_menor import saldo_actual
        con = self.db()
        try:
            return round(saldo_actual(con))
        finally:
            con.close()

    def recibir(self, factura="F-1", costo="10000", cantidad="4", resultado="aceptado", **pago):
        datos = {"proveedor_id": "1", "factura_numero": factura,
                 "linea_producto_id": ["2"], "linea_lote": [""], "linea_vencimiento": [""],
                 "linea_cantidad_recibida": [cantidad], "linea_costo": [costo], "linea_iva": ["0"],
                 "linea_presentacion": ["0"], "linea_resultado": [resultado]}
        datos.update(pago)
        r = self.post(self.c, "/recepciones/nueva", datos)
        return r, self.uno("SELECT * FROM recepciones WHERE factura_numero = ?", factura)


class TestRecepcionUnaLinea(Base117):
    def test_columnas_propias(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        for col in ("c-cant", "c-udm", "c-costo", "c-iva", "c-importe", "tabla-recepcion-caja"):
            self.assertIn(col, html)
        self.assertNotIn("linea-iva-campo", html)          # el IVA ya no va apilado debajo del costo
        self.assertIn('name="pago_modo"', html)


class TestBancos(Base117):
    def test_ventas_por_nequi_suman_y_anuladas_no(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 3}], forma="nequi")
        self.cobrar([{"producto_id": 1, "cantidad": 2}], forma="davivienda")
        self.assertEqual((self.saldo("nequi"), self.saldo("davivienda")), (3000, 2000))
        venta = self.uno("SELECT id FROM ventas WHERE forma_pago = 'nequi'")
        con = self.db()
        con.execute("UPDATE ventas SET estado = 'anulada' WHERE id = ?", (venta["id"],))
        con.commit()
        con.close()
        self.assertEqual(self.saldo("nequi"), 0)

    def test_gasto_y_abono_sin_contar_doble(self):
        con = self.db()
        con.execute("INSERT INTO gastos (fecha, categoria_id, descripcion, monto, forma_pago, activo, creado_en) "
                    "VALUES (datetime('now','localtime'), (SELECT id FROM catalogos WHERE tipo = 'categoria_gasto' LIMIT 1), "
                    "'Internet', 70000, 'davivienda', 1, datetime('now'))")
        con.execute("INSERT INTO clientes (nombre, creado_en) VALUES ('Doña Rosa', datetime('now'))")
        con.execute("INSERT INTO cartera_abonos (numero, cliente_id, fecha, monto, forma_pago, usuario_nombre, creado_en) "
                    "VALUES ('AB-1', 1, datetime('now','localtime'), 20000, 'nequi', 'x', datetime('now'))")
        # el abono hecho con caja abierta también queda en caja_movimientos (origen 'cartera')
        con.execute("INSERT INTO cajas (numero, abierta_en, efectivo_inicial, estado, detalle_apertura) "
                    "VALUES ('9', datetime('now'), 0, 'cerrada', '{}')")
        con.execute("INSERT INTO caja_movimientos (caja_id, fecha, tipo, forma_pago, monto, motivo, creado_en, origen) "
                    "VALUES (1, datetime('now','localtime'), 'ingreso', 'nequi', 20000, 'Abono AB-1', datetime('now'), 'cartera')")
        con.commit()
        con.close()
        self.assertEqual((self.saldo("davivienda"), self.saldo("nequi")), (-70000, 20000))

    def test_traslado_caja_menor_a_nequi_y_anular(self):
        antes = self.caja_menor()
        self.post(self.c, "/bancos/traslado", {"origen": "caja_menor", "destino": "nequi", "monto": "50000",
                                               "fecha": HOY})
        self.assertEqual((self.caja_menor(), self.saldo("nequi")), (antes - 50000, 50000))
        mov = self.uno("SELECT id FROM bancos_movimientos WHERE tipo = 'traslado_entrada'")
        self.post(self.c, f"/bancos/movimiento/{mov['id']}/anular", {})
        self.assertEqual((self.caja_menor(), self.saldo("nequi")), (antes, 0))

    def test_traslado_entre_bancos(self):
        self.post(self.c, "/bancos/traslado", {"origen": "nequi", "destino": "davivienda", "monto": "30000"})
        self.assertEqual((self.saldo("nequi"), self.saldo("davivienda")), (-30000, 30000))

    def test_plata_del_dueno_no_es_gasto(self):
        self.post(self.c, "/bancos/dueno", {"cuenta": "nequi", "tipo": "aporte_dueno", "monto": "100000"})
        self.post(self.c, "/bancos/dueno", {"cuenta": "nequi", "tipo": "retiro_dueno", "monto": "40000"})
        self.assertEqual(self.saldo("nequi"), 60000)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM gastos")["n"], 0)
        from app import utilidades
        with self.app.test_request_context():
            r = utilidades.calcular(date.today().replace(day=1), date.today())
        self.assertEqual(round(r["retiros_dueno"]), 40000)          # informativo, aparte de los gastos

    def test_cuadrar_cobros_del_banco_y_plata_personal(self):
        self.post(self.c, "/bancos/arranque/x", {})                      # ruta mala: no rompe nada
        self.post(self.c, "/bancos/nequi/arranque", {"saldo_inicial": "200000", "fecha_inicial": HOY})
        self.assertEqual(self.saldo("nequi"), 200000)
        # La app dice 195.000: faltan 5.000 → cobros del banco = gasto "Gastos bancarios"
        self.post(self.c, "/bancos/cuadrar", {"cuenta": "nequi", "saldo_app": "195000", "explicacion": "banco"})
        g = self.uno("SELECT g.monto, g.forma_pago, c.nombre FROM gastos g JOIN catalogos c ON c.id = g.categoria_id")
        self.assertEqual((round(g["monto"]), g["forma_pago"], g["nombre"]), (5000, "nequi", "Gastos bancarios"))
        self.assertEqual(self.saldo("nequi"), 195000)
        # Ahora dice 150.000: 45.000 que sacó el dueño
        self.post(self.c, "/bancos/cuadrar", {"cuenta": "nequi", "saldo_app": "150000", "explicacion": "dueno"})
        self.assertEqual(self.uno("SELECT tipo, monto FROM bancos_movimientos")["tipo"], "retiro_dueno")
        self.assertEqual(self.saldo("nequi"), 150000)

    def test_pantallas(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 3}], forma="nequi")
        for url in ("/bancos/", "/bancos/nequi", "/bancos/nequi?mes=todo", "/bancos/davivienda"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
        self.assertIn("V-0001", self.c.get("/bancos/nequi").get_data(as_text=True))
        self.assertEqual(self.c.get("/bancos/bancolombia").status_code, 404)

    def test_cuenta_arranca_el_dia_de_la_primera_venta(self):
        c = self.uno("SELECT fecha_inicial FROM cuentas_bancarias WHERE clave = 'nequi'")
        self.assertEqual(len(c["fecha_inicial"]), 10)


class TestCuentasPorPagar(Base117):
    def test_credito_queda_pendiente_con_plazo_del_proveedor(self):
        con = self.db()
        con.execute("UPDATE proveedores SET plazo_dias = 15 WHERE id = 1")
        con.commit()
        con.close()
        _, rec = self.recibir()
        self.assertEqual((rec["pago_estado"], round(rec["total_pagar"])), ("pendiente", 40000))
        self.assertEqual(rec["pago_vence"], (date.today() + timedelta(days=15)).isoformat())

    def test_lineas_rechazadas_no_se_pagan(self):
        _, rec = self.recibir(resultado="rechazado", factura="F-R")
        self.assertEqual(rec["pago_estado"], "no_aplica")

    def test_contado_desde_nequi(self):
        _, rec = self.recibir(pago_modo="contado", pago_origen="nequi")
        self.assertEqual(rec["pago_estado"], "pagada")
        self.assertEqual(self.saldo("nequi"), -40000)
        p = self.uno("SELECT * FROM pagos_proveedores")
        self.assertEqual((p["origen"], round(p["monto"])), ("nequi", 40000))

    def test_contado_caja_pos_sin_caja_abierta_no_guarda(self):
        r, rec = self.recibir(pago_modo="contado", pago_origen="caja_pos", factura="F-X")
        self.assertIsNone(rec)
        self.assertIn("No hay caja del POS abierta", r.get_data(as_text=True))

    def test_contado_desde_caja_pos_baja_el_efectivo_esperado(self):
        self.abrir_caja("100000")
        self.recibir(pago_modo="contado", pago_origen="caja_pos")
        from app.pos import _resumen_caja
        with self.app.test_request_context():
            from app.db import get_db
            caja = get_db().execute("SELECT * FROM cajas WHERE estado = 'abierta'").fetchone()
            self.assertEqual(round(_resumen_caja(caja)["efectivo_esperado"]), 60000)

    def test_pagar_desde_caja_menor_y_anular(self):
        _, rec = self.recibir()
        antes = self.caja_menor()
        self.post(self.c, f"/cuentas-por-pagar/pagar/{rec['id']}", {"monto": "40000", "fecha": HOY,
                                                                     "origen": "caja_menor"})
        self.assertEqual(self.uno("SELECT pago_estado FROM recepciones WHERE id = ?", rec["id"])["pago_estado"], "pagada")
        self.assertEqual(self.caja_menor(), antes - 40000)
        pago = self.uno("SELECT id FROM pagos_proveedores")
        self.post(self.c, f"/cuentas-por-pagar/pago/{pago['id']}/anular", {"motivo": "error"})
        self.assertEqual(self.uno("SELECT pago_estado FROM recepciones WHERE id = ?", rec["id"])["pago_estado"], "pendiente")
        self.assertEqual(self.caja_menor(), antes)

    def test_pago_no_es_gasto(self):
        _, rec = self.recibir()
        self.post(self.c, f"/cuentas-por-pagar/pagar/{rec['id']}", {"monto": "40000", "origen": "davivienda"})
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM gastos")["n"], 0)
        self.assertEqual(self.saldo("davivienda"), -40000)

    def test_facturas_viejas_por_revisar(self):
        _, a = self.recibir(factura="V-1")
        _, b = self.recibir(factura="V-2")
        con = self.db()
        con.execute("UPDATE recepciones SET pago_estado = 'por_revisar', pago_vence = NULL")
        con.commit()
        con.close()
        html = self.c.get("/cuentas-por-pagar/?ver=por_revisar").get_data(as_text=True)
        self.assertIn("Ya estaba pagada", html)
        self.assertNotIn('value="caja_menor"', html)          # para las viejas no se ofrece la caja menor
        self.post(self.c, f"/cuentas-por-pagar/revisar/{a['id']}", {"accion": "pagada", "origen": "nequi", "fecha": HOY})
        self.post(self.c, f"/cuentas-por-pagar/revisar/{b['id']}", {"accion": "pendiente", "vence": "2030-01-31"})
        self.assertEqual(self.uno("SELECT pago_estado FROM recepciones WHERE id = ?", a["id"])["pago_estado"], "pagada")
        fila = self.uno("SELECT pago_estado, pago_vence FROM recepciones WHERE id = ?", b["id"])
        self.assertEqual((fila["pago_estado"], fila["pago_vence"]), ("pendiente", "2030-01-31"))
        self.assertEqual(self.saldo("nequi"), -40000)

    def test_recepcion_rechazada_no_se_paga(self):
        _, rec = self.recibir()
        self.post(self.c, f"/recepciones/{rec['id']}/rechazar", {"motivo": "llegó dañado"})
        self.assertEqual(self.uno("SELECT pago_estado FROM recepciones WHERE id = ?", rec["id"])["pago_estado"], "no_aplica")

    def test_plazo_del_proveedor_se_guarda(self):
        self.post(self.c, "/proveedores/1/editar", {"nit": "900123456", "razon_social": "Proveedor Prueba SAS",
                                                     "plazo_dias": "30"})
        self.assertEqual(self.uno("SELECT plazo_dias FROM proveedores WHERE id = 1")["plazo_dias"], 30)

    def test_pantallas_dashboard_y_alerta(self):
        _, rec = self.recibir()
        con = self.db()
        con.execute("UPDATE recepciones SET pago_vence = '2020-01-01' WHERE id = ?", (rec["id"],))
        con.commit()
        con.close()
        for url in ("/cuentas-por-pagar/", "/cuentas-por-pagar/?ver=pagadas", f"/cuentas-por-pagar/pagar/{rec['id']}",
                    f"/recepciones/{rec['id']}"):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        dash = self.c.get("/contabilidad/").get_data(as_text=True)
        self.assertIn("Le debo a proveedores", dash)
        self.assertIn("Facturas de proveedores por pagar ya", dash)
        self.assertIn("Se debe", self.c.get(f"/recepciones/{rec['id']}").get_data(as_text=True))


class TestFormulariosSeguros(Base117):
    """Todo formulario que envía datos (POST) lleva el campo _csrf (protección del programa).

    En las pruebas esa protección está apagada, así que sin esta revisión un formulario
    sin _csrf pasaría las pruebas pero fallaría en la droguería.
    """

    def test_todos_los_post_llevan_csrf(self):
        import re
        raiz = Path(__file__).resolve().parent.parent / "app" / "templates"
        faltan = []
        for archivo in raiz.rglob("*.html"):
            texto = archivo.read_text(encoding="utf-8")
            for m in re.finditer(r'<form[^>]*method="post"[^>]*>', texto, re.I):
                fin = texto.find("</form>", m.end())
                if "_csrf" not in texto[m.end():fin]:
                    faltan.append(f"{archivo.relative_to(raiz)}:{texto[:m.start()].count(chr(10)) + 1}")
        self.assertEqual(faltan, [])
