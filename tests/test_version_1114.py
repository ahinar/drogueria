"""
PRUEBAS DE LA VERSIÓN 1.1.14
============================
  - TestDaviplata: forma de pago y cuenta propia en Bancos (migración 43).
  - TestMovimientoDePlata: el botón único del POS; a dónde va la plata (dueño,
    caja menor, una cuenta) y los retiros del dueño en Utilidades.
  - TestPantallaVentas: buscar ventas, el panel de la derecha, devolver desde ahí.
  - TestCorregirPago: «pagó por Daviplata y se registró como efectivo», con la
    caja abierta y con la caja ya cerrada (el faltante se vuelve a calcular).
  - TestOrdenInterfaz: menú por tareas, pantallas repetidas que redirigen y el aviso
    de la copia de seguridad fuera del computador.

Recordatorio (BaseVentas): producto 1 = $1.000 sin IVA; la caja se abre con $10.000.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO


class BaseUno(BaseVentas):
    def setUp(self):
        super().setUp()
        self.lote(1, "A1", FUTURO, 50)
        self.abrir_caja()

    def vender(self, forma="efectivo", cantidad=1, **extra):
        datos = {"carrito": json.dumps([{"producto_id": 1, "cantidad": cantidad}]), "forma_pago": forma,
                 "monto_recibido": "100000" if forma == "efectivo" else ""}
        datos.update(extra)
        j = self.post(self.c, "/pos/api/cobrar", datos).get_json()
        self.assertTrue(j["ok"], j)
        return j

    def venta(self, numero=1):
        return self.uno("SELECT * FROM ventas WHERE id = ?", numero)

    def resumen(self):
        return self.c.get("/pos/api/resumen-caja").get_json()["resumen"]


class TestDaviplata(BaseUno):
    def test_migracion_y_cuenta(self):
        self.assertGreaterEqual(self.uno("SELECT MAX(version) v FROM schema_version")["v"], 43)
        self.assertEqual(self.uno("SELECT nombre FROM cuentas_bancarias WHERE clave = 'daviplata'")["nombre"], "Daviplata")
        columnas = [f[1] for f in self.db().execute("PRAGMA table_info(caja_movimientos)")]
        self.assertIn("lugar", columnas)

    def test_vender_por_daviplata_y_mixto(self):
        self.vender("daviplata", 2)
        self.vender("mixto", 3, pagos=json.dumps({"daviplata": 1000, "nequi": 500}))
        r = self.resumen()
        daviplata = next(c for c in r["cuentas"] if c["clave"] == "daviplata")
        self.assertEqual(daviplata["ventas"], 3000)            # 2.000 + 1.000 del mixto
        self.assertEqual(r["efectivo"]["ventas"], 1500)        # lo que faltó en el mixto
        html = self.c.get("/bancos/").get_data(as_text=True)
        self.assertIn("Daviplata", html)
        pos = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('data-forma="daviplata"', pos)            # botón para cobrar
        self.assertIn('id="cuentas-pago"', pos)

    def test_gasto_por_daviplata(self):
        cat = self.uno("SELECT id FROM catalogos WHERE tipo = 'categoria_gasto' LIMIT 1")["id"]
        j = self.post(self.c, "/pos/api/gasto", {"descripcion": "Domicilio", "monto": "3000", "categoria_id": str(cat),
                                                 "forma_pago": "daviplata", "origen": "ninguna"}).get_json()
        self.assertTrue(j["ok"], j)


class TestMovimientoDePlata(BaseUno):
    def mover(self, tipo, lugar, monto="2000", forma="efectivo"):
        return self.post(self.c, "/pos/api/movimiento", {"tipo": tipo, "forma_pago": forma,
                                                         "monto": monto, "lugar": lugar})

    def test_me_la_llevo_yo_es_retiro_no_gasto(self):
        self.assertTrue(self.mover("salida", "dueno").get_json()["ok"])
        self.assertEqual(self.resumen()["efectivo"]["esperado"], 8000)    # 10.000 − 2.000
        from app import utilidades
        from datetime import date
        with self.app.app_context():
            r = utilidades.calcular(date.today().replace(day=1), date.today())
        self.assertEqual(r["retiros_dueno"], 2000)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM gastos")["n"], 0)

    def test_pasar_a_caja_menor_y_a_una_cuenta(self):
        self.assertTrue(self.mover("salida", "caja_menor", "1500").get_json()["ok"])
        cm = self.uno("SELECT tipo, monto FROM caja_menor_movimientos ORDER BY id DESC LIMIT 1")
        self.assertEqual((cm["tipo"], cm["monto"]), ("aporte", 1500))
        self.assertTrue(self.mover("salida", "daviplata", "2500").get_json()["ok"])
        b = self.uno("SELECT m.tipo, m.monto FROM bancos_movimientos m JOIN cuentas_bancarias c ON c.id = m.cuenta_id "
                     "WHERE c.clave = 'daviplata'")
        self.assertEqual((b["tipo"], b["monto"]), ("traslado_entrada", 2500))
        # Entra efectivo que se trae de Nequi → sale de Nequi
        self.assertTrue(self.mover("ingreso", "nequi", "700").get_json()["ok"])
        b = self.uno("SELECT m.tipo FROM bancos_movimientos m JOIN cuentas_bancarias c ON c.id = m.cuenta_id "
                     "WHERE c.clave = 'nequi'")
        self.assertEqual(b["tipo"], "traslado_salida")

    def test_errores(self):
        self.assertEqual(self.mover("salida", "luna").status_code, 400)
        self.assertEqual(self.mover("salida", "dueno", forma="nequi").status_code, 400)

    def test_menu_con_un_solo_boton(self):
        html = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('data-accion="movimiento-plata"', html)
        for viejo in ('data-accion="ingreso-efectivo"', 'data-accion="salida-efectivo"', 'data-accion="registrar-gasto"'):
            self.assertNotIn(viejo, html)
        self.assertIn('id="mov-lugar"', html)


class TestPantallaVentas(BaseUno):
    def test_lista_buscar_y_panel(self):
        self.vender("efectivo", 2)
        self.vender("nequi", 1)
        html = self.c.get("/ventas/").get_data(as_text=True)
        self.assertIn("V-0001", html)
        self.assertIn("V-0002", html)
        solo_nequi = self.c.get("/ventas/?forma=nequi").get_data(as_text=True)
        self.assertNotIn(">V-0001<", solo_nequi)
        self.assertIn("V-0001", self.c.get("/ventas/?q=acetamin").get_data(as_text=True))   # por producto
        self.assertIn("V-0002", self.c.get("/ventas/?q=2").get_data(as_text=True))          # por número
        panel = self.c.get("/ventas/1/panel").get_data(as_text=True)
        self.assertIn("Corregir el pago", panel)
        self.assertIn("Devoluciones", panel)
        self.assertIn('name="volver" value="ventas"', panel)                                 # devolver aquí mismo
        con_panel = self.c.get("/ventas/?venta=1").get_data(as_text=True)
        self.assertIn('data-venta="1"', con_panel)
        self.assertEqual(self.c.get("/ventas/999/panel").status_code, 404)

    def test_devolucion_desde_el_panel_vuelve_a_ventas(self):
        self.vender("efectivo", 2)
        linea = self.uno("SELECT id FROM venta_lineas")["id"]
        r = self.post(self.c, "/devoluciones/cliente", {"venta": "V-0001", "volver": "ventas", f"cant_{linea}": "1",
                                                        f"destino_{linea}": "reingreso", "forma_reembolso": "efectivo",
                                                        "motivo": "No lo necesitó"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/ventas/?venta=1", r.headers["Location"])
        self.assertIn("DC-0001", self.c.get("/ventas/1/panel").get_data(as_text=True))

    def test_direccion_vieja(self):
        self.vender()
        r = self.c.get("/pos/ventas")
        self.assertIn("/ventas/?caja=", r.headers["Location"])


class TestCorregirPago(BaseUno):
    def corregir(self, venta_id=1, **datos):
        base = {"forma_pago": "daviplata", "motivo": "Pagó por Daviplata, se marcó efectivo"}
        base.update(datos)
        return self.post(self.c, f"/ventas/{venta_id}/corregir-pago", base, follow_redirects=True)

    def test_con_la_caja_abierta(self):
        self.vender("efectivo", 5)                      # $5.000 en efectivo
        self.assertEqual(self.resumen()["efectivo"]["esperado"], 15000)
        html = self.corregir().get_data(as_text=True)
        self.assertIn("corregido", html)
        v = self.venta()
        self.assertEqual((v["forma_pago"], v["pago_corregido"]), ("daviplata", 1))
        self.assertIsNone(v["monto_recibido"])
        r = self.resumen()
        self.assertEqual(r["efectivo"]["esperado"], 10000)
        self.assertEqual(next(c for c in r["cuentas"] if c["clave"] == "daviplata")["ventas"], 5000)
        h = self.uno("SELECT antes, despues FROM venta_correcciones_pago")
        self.assertEqual((h["antes"], h["despues"]), ("Efectivo", "Daviplata"))

    def test_con_la_caja_cerrada_se_arregla_el_faltante(self):
        self.vender("efectivo", 5)
        # Al cerrar solo había $10.000: «faltaron» $5.000 (en realidad llegaron por Daviplata)
        self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "10000"})
        caja = self.uno("SELECT * FROM cajas WHERE id = 1")
        self.assertEqual(caja["diferencia"], -5000)
        gasto = self.uno("SELECT activo, monto FROM gastos WHERE id = ?", caja["diferencia_gasto_id"])
        self.assertEqual((gasto["activo"], gasto["monto"]), (1, 5000))
        self.corregir()
        caja = self.uno("SELECT * FROM cajas WHERE id = 1")
        self.assertEqual(caja["diferencia"], 0)                      # ahora cuadra
        self.assertIsNone(caja["diferencia_gasto_id"])
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM gastos WHERE activo = 1")["n"], 0)   # el faltante se anuló

    def test_mixto_y_errores(self):
        self.vender("efectivo", 5)
        self.corregir(forma_pago="mixto", monto_daviplata="3000")
        partes = {p["forma_pago"]: p["monto"] for p in self.db().execute("SELECT * FROM venta_pagos")}
        self.assertEqual(partes, {"daviplata": 3000, "efectivo": 2000})
        html = self.corregir(forma_pago="mixto", monto_daviplata="3000").get_data(as_text=True)
        self.assertIn("es la misma", html)
        self.assertIn("motivo", self.corregir(forma_pago="nequi", motivo="x").get_data(as_text=True))
        self.assertIn("Escoge cómo pagó", self.corregir(forma_pago="credito").get_data(as_text=True))
        self.assertIn("al menos dos", self.corregir(forma_pago="mixto", monto_nequi="5000").get_data(as_text=True))

    def test_no_se_corrige_un_fiado_ni_una_anulada(self):
        from app.ventas import puede_corregir
        with self.app.test_request_context():
            from flask import g
            g.user = {"rol": "administrador", "id": 1, "nombre": "x"}
            self.assertFalse(puede_corregir({"estado": "anulada", "forma_pago": "efectivo", "caja_estado": "abierta"})[0])
            self.assertFalse(puede_corregir({"estado": "completada", "forma_pago": "credito", "caja_estado": "abierta"})[0])
            g.user = {"rol": "auxiliar", "id": 2, "nombre": "y"}
            self.assertFalse(puede_corregir({"estado": "completada", "forma_pago": "efectivo", "caja_estado": "cerrada"})[0])
            self.assertTrue(puede_corregir({"estado": "completada", "forma_pago": "efectivo", "caja_estado": "abierta"})[0])


class TestOrdenInterfaz(BaseUno):
    def test_menu_por_tareas(self):
        html = self.c.get("/").get_data(as_text=True)
        for grupo in ('data-group="ventas"', 'data-group="compras"', 'data-group="inventario"',
                      'data-group="dinero"', 'data-group="calidad"'):
            self.assertIn(grupo, html)
        self.assertIn("Computadores y red", html)
        self.assertIn("Equipos de medición", html)

    def test_pantallas_repetidas_redirigen(self):
        self.assertIn("/reportes/vencimientos", self.c.get("/inventario/vencimientos").headers["Location"])
        r = self.c.get("/temperaturas/historial?fuera=1")
        self.assertIn("/reportes/temperaturas", r.headers["Location"])
        self.assertIn("fuera=1", r.headers["Location"])

    def test_aviso_copia_fuera_del_computador(self):
        self.assertIn("Copia de seguridad solo en este computador", self.c.get("/").get_data(as_text=True))

    def test_pos_categorias_en_una_fila(self):
        html = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('id="pos-cat-mas"', html)
        self.assertIn('id="pos-cat-menu"', html)
