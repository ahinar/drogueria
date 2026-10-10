"""
PRUEBAS DE LA TOMA DE INVENTARIO (conteo físico).

Cada test crea un conteo, "cuenta" lotes como lo haría la pantalla y revisa
que al aplicar los lotes, el kardex y la bitácora queden bien.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO, PASADO


from datetime import date as _d, timedelta as _td
FUTURO_C = (_d.today() + _td(days=400)).isoformat()


class BaseConteo(BaseVentas):
    def crear_conteo(self, cliente=None, **datos):
        return self.post(cliente or self.c, "/inventario/conteos/nuevo", datos)

    def contar(self, cantidad, conteo=1, cliente=None, **datos):
        datos["cantidad"] = str(cantidad)
        return self.post(cliente or self.c, f"/inventario/conteos/{conteo}/api/contar", datos)

    def aplicar(self, conteo=1, cliente=None):
        return self.post(cliente or self.c, f"/inventario/conteos/{conteo}/aplicar")

    def cantidad_lote(self, lote):
        fila = self.uno("SELECT cantidad_disponible n FROM lotes WHERE lote = ?", lote)
        return fila["n"] if fila else None

    def auxiliar(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c2 = self.cliente()
        self.entrar(c2, "aux")
        return c2


class TestCrearConteo(BaseConteo):
    def test_crea_conteo_con_consecutivo(self):
        self.crear_conteo(descripcion="Conteo de prueba")
        c = self.uno("SELECT * FROM conteos")
        self.assertEqual((c["numero"], c["estado"]), ("CNT-0001", "abierto"))

    def test_solo_un_conteo_abierto(self):
        self.crear_conteo()
        self.crear_conteo()
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM conteos")["n"], 1)

    def test_auxiliar_no_crea_ni_aplica_pero_si_cuenta(self):
        self.lote(1, "L1", FUTURO, 10)
        c2 = self.auxiliar()
        self.assertEqual(self.crear_conteo(cliente=c2).status_code, 403)
        self.crear_conteo()
        self.assertTrue(self.contar(8, cliente=c2, lote_id="1").get_json()["ok"])
        self.assertEqual(self.aplicar(cliente=c2).status_code, 403)
        self.assertEqual(self.cantidad_lote("L1"), 10)


class TestContarYAplicar(BaseConteo):
    def test_faltante_y_sobrante(self):
        self.lote(1, "FALTA", FUTURO, 10)
        self.lote(1, "SOBRA", FUTURO, 5)
        self.crear_conteo()
        j = self.contar(7, lote_id="1").get_json()
        self.assertEqual(j["linea"]["diferencia"], -3)
        self.contar(6, lote_id="2")
        self.aplicar()
        self.assertEqual((self.cantidad_lote("FALTA"), self.cantidad_lote("SOBRA")), (7, 6))
        movs = self.db().execute(
            "SELECT cantidad FROM movimientos_inventario WHERE tipo='ajuste' ORDER BY lote_id").fetchall()
        self.assertEqual([m["cantidad"] for m in movs], [-3, 1])
        self.assertEqual(self.uno("SELECT estado FROM conteos")["estado"], "aplicado")
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion='conteo_aplicado'"))

    def test_vender_durante_el_conteo_no_se_pierde(self):
        """Sistema 10, cuento 9 (falta 1), luego vendo 2 -> al aplicar debe quedar 7, no 9."""
        self.lote(1, "L1", FUTURO, 10)
        self.crear_conteo()
        self.contar(9, lote_id="1")
        self.abrir_caja()
        self.assertTrue(self.cobrar([{"producto_id": 1, "cantidad": 2}]).get_json()["ok"])
        self.assertEqual(self.cantidad_lote("L1"), 8)
        self.aplicar()
        self.assertEqual(self.cantidad_lote("L1"), 7)

    def test_venta_antes_de_contar_ya_queda_incluida(self):
        """Vendo 2 ANTES de contar ese lote: el sistema ya dice 8; cuento 8 -> sin diferencia."""
        self.lote(1, "L1", FUTURO, 10)
        self.crear_conteo()
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 2}])
        j = self.contar(8, lote_id="1").get_json()
        self.assertEqual(j["linea"]["diferencia"], 0)
        self.aplicar()
        self.assertEqual(self.cantidad_lote("L1"), 8)

    def test_recontar_reemplaza_lo_anterior(self):
        self.lote(1, "L1", FUTURO, 10)
        self.crear_conteo()
        self.contar(3, lote_id="1")
        self.contar(10, lote_id="1")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM conteo_lineas")["n"], 1)
        self.aplicar()
        self.assertEqual(self.cantidad_lote("L1"), 10)

    def test_contar_cero_agota_el_lote(self):
        self.lote(1, "L1", FUTURO, 4)
        self.crear_conteo()
        self.contar(0, lote_id="1")
        self.aplicar()
        lote = self.uno("SELECT cantidad_disponible n, estado FROM lotes WHERE lote='L1'")
        self.assertEqual((lote["n"], lote["estado"]), (0, "agotado"))

    def test_lotes_no_contados_no_se_tocan(self):
        self.lote(1, "CONTADO", FUTURO, 10)
        self.lote(1, "OLVIDADO", FUTURO, 10)
        self.crear_conteo()
        self.contar(9, lote_id="1")
        self.aplicar()
        self.assertEqual((self.cantidad_lote("CONTADO"), self.cantidad_lote("OLVIDADO")), (9, 10))

    def test_cantidad_invalida(self):
        self.lote(1, "L1", FUTURO, 10)
        self.crear_conteo()
        for mala in ("-1", "abc", ""):
            self.assertFalse(self.contar(mala, lote_id="1").get_json()["ok"], mala)

    def test_quitar_una_linea(self):
        self.lote(1, "L1", FUTURO, 10)
        self.crear_conteo()
        linea = self.contar(2, lote_id="1").get_json()["linea"]
        self.post(self.c, "/inventario/conteos/1/api/quitar", {"linea_id": str(linea["id"])})
        self.aplicar()
        self.assertEqual(self.cantidad_lote("L1"), 10)


class TestLotesEncontrados(BaseConteo):
    """Así entra el inventario inicial: productos importados sin lotes."""

    def test_lote_nuevo_se_crea_al_aplicar(self):
        self.crear_conteo()
        j = self.contar(15, producto_id="1", lote="abc123", vencimiento="2028-05-01", costo="350").get_json()
        self.assertTrue(j["ok"], j)
        self.assertIsNone(self.cantidad_lote("ABC123"))   # aún no existe
        self.aplicar()
        lote = self.uno("SELECT * FROM lotes WHERE lote='ABC123'")
        self.assertEqual((lote["cantidad_disponible"], lote["costo_unitario"], lote["estado"]),
                         (15, 350, "disponible"))
        # ... y queda vendible en el POS
        self.abrir_caja()
        self.assertTrue(self.cobrar([{"producto_id": 1, "cantidad": 1}]).get_json()["ok"])

    def test_producto_con_lotes_exige_lote_y_vencimiento(self):
        self.crear_conteo()
        self.assertFalse(self.contar(5, producto_id="1", costo="100").get_json()["ok"])
        # La jeringa (id 2) no maneja vencimiento: puede ir sin lote
        self.assertTrue(self.contar(5, producto_id="2", costo="100").get_json()["ok"])

    def test_exige_costo(self):
        self.crear_conteo()
        j = self.contar(5, producto_id="1", lote="X", vencimiento="2028-01-01").get_json()
        self.assertFalse(j["ok"])   # sin costo y sin compras previas

    def test_lote_que_ya_existe_se_cuenta_sobre_el_existente(self):
        self.lote(1, "L1", FUTURO, 10)
        self.crear_conteo()
        j = self.contar(12, producto_id="1", lote="l1", vencimiento=FUTURO, costo="100").get_json()
        self.assertEqual(j["lote_id"], 1)
        self.aplicar()
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM lotes")["n"], 1)
        self.assertEqual(self.cantidad_lote("L1"), 12)

    def test_mismo_lote_nuevo_dos_veces_se_actualiza(self):
        self.crear_conteo()
        self.contar(5, producto_id="1", lote="N1", vencimiento="2028-01-01", costo="100")
        self.contar(7, producto_id="1", lote="N1", vencimiento="2028-01-01", costo="100")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM conteo_lineas")["n"], 1)
        self.aplicar()
        self.assertEqual(self.cantidad_lote("N1"), 7)


class TestBuscarRevisarYActa(BaseConteo):
    def test_buscar_y_filtros(self):
        self.lote(1, "L1", FUTURO, 10)
        self.lote(2, "J1", FUTURO, 3)
        self.crear_conteo()
        self.contar(9, lote_id="1")
        def nombres(filtro):
            j = self.c.get(f"/inventario/conteos/1/api/buscar?filtro={filtro}").get_json()
            return [p["id"] for p in j["productos"]]
        self.assertEqual(sorted(nombres("todos")), [1, 2])
        self.assertEqual(nombres("contados"), [1])
        self.assertEqual(nombres("pendientes"), [2])
        self.assertEqual(nombres("diferencias"), [1])
        r = self.c.get("/inventario/conteos/1/api/buscar?q=jeringa").get_json()
        self.assertEqual([p["id"] for p in r["productos"]], [2])
        self.assertEqual(r["resumen"]["pendientes"], 1)

    def test_conteo_por_categoria_solo_muestra_esa_categoria(self):
        con = self.db()
        cat = con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) "
                          "VALUES ('categoria', 'Prueba', 1, '2026-01-01')").lastrowid
        con.execute("INSERT INTO productos_categorias (producto_id, catalogo_id) VALUES (2, ?)", (cat,))
        con.commit()
        con.close()
        self.lote(1, "A1", FUTURO_C, 5)
        self.lote(2, "B1", FUTURO_C, 5)
        self.crear_conteo(categoria_id=str(cat))
        j = self.c.get("/inventario/conteos/1/api/buscar").get_json()
        self.assertEqual([p["id"] for p in j["productos"]], [2])

    def test_en_cero_solo_aparece_al_buscar(self):
        """Sin buscar, la lista muestra lo que hay; buscando, aparece aunque esté en 0."""
        self.lote(1, "A1", FUTURO_C, 5)
        self.crear_conteo()
        j = self.c.get("/inventario/conteos/1/api/buscar").get_json()
        self.assertEqual([p["id"] for p in j["productos"]], [1])
        nombre = self.uno("SELECT nombre FROM productos WHERE id = 2")["nombre"]
        j = self.c.get("/inventario/conteos/1/api/buscar?q=" + nombre.split()[0]).get_json()
        self.assertIn(2, [p["id"] for p in j["productos"]])

    def test_lote_agotado_se_reutiliza(self):
        self.lote(1, "VIEJO", FUTURO_C, 0)
        self.crear_conteo()
        r = self.post(self.c, "/inventario/conteos/1/api/contar", {
            "producto_id": "1", "lote": "viejo", "vencimiento": FUTURO_C, "cantidad": "3", "costo": "100"}).get_json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["lote_id"], self.uno("SELECT id FROM lotes WHERE lote = 'VIEJO'")["id"])

    def test_paginas(self):
        self.crear_conteo()
        r = self.c.get("/inventario/conteos/").status_code
        self.assertEqual(r, 200)
        self.assertEqual(self.c.get("/inventario/conteos/1").status_code, 200)
        self.assertEqual(self.c.get("/inventario/conteos/1/revisar").status_code, 200)
        acta = self.c.get("/inventario/conteos/1/acta")
        self.assertTrue(acta.data.startswith(b"%PDF"))

    def test_anular_no_cambia_nada(self):
        self.lote(1, "L1", FUTURO, 10)
        self.crear_conteo()
        self.contar(1, lote_id="1")
        self.post(self.c, "/inventario/conteos/1/anular", {"motivo": "Me equivoqué"})
        self.assertEqual(self.uno("SELECT estado FROM conteos")["estado"], "anulado")
        self.assertEqual(self.cantidad_lote("L1"), 10)
        self.assertFalse(self.contar(5, lote_id="1").get_json()["ok"])   # ya está cerrado
        self.aplicar()
        self.assertEqual(self.cantidad_lote("L1"), 10)

    def test_no_se_aplica_dos_veces(self):
        self.lote(1, "L1", FUTURO, 10)
        self.crear_conteo()
        self.contar(8, lote_id="1")
        self.aplicar()
        self.aplicar()
        self.assertEqual(self.cantidad_lote("L1"), 8)

    def test_lote_vencido_tambien_se_puede_contar(self):
        self.lote(1, "VIEJO", PASADO, 6)
        self.crear_conteo()
        self.contar(4, lote_id="1")
        self.aplicar()
        self.assertEqual(self.cantidad_lote("VIEJO"), 4)
