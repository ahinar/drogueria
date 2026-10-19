"""
PRUEBAS DE SANEAMIENTO (Fase 4.2, app/saneamiento.py):
limpieza (períodos, marcar, quitar, permisos, planilla, aviso), control de
plagas, residuos (registro, entrega, baja de vencidos) y PDFs.
"""
import io
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1

HOY = date.today()


class BaseSaneamiento(BaseFase1):
    def tearDown(self):
        con = self.db()
        for tabla in ("control_plagas", "residuos_entregas"):
            for f in con.execute(f"SELECT archivo FROM {tabla} WHERE archivo IS NOT NULL"):
                (Path(self.app.static_folder) / f["archivo"]).unlink(missing_ok=True)
        con.close()
        super().tearDown()

    def marcar(self, c=None, tarea_id=1, fecha=None):
        return self.post(c or self.c, "/saneamiento/limpieza/marcar",
                         {"tarea_id": tarea_id, "fecha": (fecha or HOY).isoformat()})

    def n(self, sql):
        return self.uno(sql)["n"]

    def auxiliar(self):
        self.crear_usuario(self.c, "aux1", "auxiliar")
        aux = self.cliente()
        self.entrar(aux, "aux1")
        return aux

    def claves_inicio(self):
        return re.findall(r'data-clave="([a-z_]+)"', self.c.get("/").get_data(as_text=True))


class TestPeriodos(BaseSaneamiento):
    def test_periodos(self):
        from app.saneamiento import periodo
        jueves = date(2026, 10, 8)
        self.assertEqual(periodo("diaria", jueves), (jueves, jueves))
        self.assertEqual(periodo("semanal", jueves), (date(2026, 10, 5), date(2026, 10, 11)))   # lunes a domingo
        self.assertEqual(periodo("quincenal", jueves), (date(2026, 10, 1), date(2026, 10, 15)))
        self.assertEqual(periodo("quincenal", date(2026, 2, 20)), (date(2026, 2, 16), date(2026, 2, 28)))
        self.assertEqual(periodo("mensual", jueves), (date(2026, 10, 1), date(2026, 10, 31)))


class TestLimpieza(BaseSaneamiento):
    def test_vienen_las_tres_tareas_de_fernando(self):
        tareas = [(f["nombre"], f["frecuencia"]) for f in self.db().execute(
            "SELECT nombre, frecuencia FROM limpieza_tareas ORDER BY orden")]
        self.assertEqual(tareas, [("Pisos", "diaria"), ("Estanterías", "semanal"), ("Nevera", "mensual")])

    def test_marcar_una_vez_por_dia_y_no_futuro(self):
        self.marcar()
        self.marcar()                                            # repetido: no duplica
        self.marcar(fecha=HOY + timedelta(days=1))               # futuro: no
        self.assertEqual(self.n("SELECT COUNT(*) n FROM limpieza_registros"), 1)
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'limpieza_hecha'"))

    def test_semanal_queda_hecha_toda_la_semana(self):
        from app.saneamiento import estado_tareas, periodo
        inicio, _ = periodo("semanal", HOY)
        self.marcar(tarea_id=2, fecha=inicio)
        with self.app.app_context():
            estanterias = next(t for t in estado_tareas(HOY) if t["nombre"] == "Estanterías")
            pisos = next(t for t in estado_tareas(HOY) if t["nombre"] == "Pisos")
        self.assertIsNotNone(estanterias["hecho"])
        # "Pisos" nadie la marcó: sigue pendiente SIEMPRE. (Antes esta línea esperaba lo
        # contrario cuando hoy es el inicio de la semana, y la prueba fallaba los LUNES:
        # así falló la publicación de la 1.1.3, porque GitHub corre en hora UTC y ya era lunes.)
        self.assertIsNone(pisos["hecho"])

    def test_auxiliar_marca_hasta_7_dias_atras_y_quita_solo_lo_suyo(self):
        aux = self.auxiliar()
        self.marcar(aux, fecha=HOY - timedelta(days=8))          # muy viejo para un auxiliar
        self.assertEqual(self.n("SELECT COUNT(*) n FROM limpieza_registros"), 0)
        self.marcar(aux, fecha=HOY - timedelta(days=3))
        self.marcar(self.c, tarea_id=2)                          # esta la marcó el jefe
        self.assertEqual(self.n("SELECT COUNT(*) n FROM limpieza_registros"), 2)
        id_jefe = self.uno("SELECT id FROM limpieza_registros WHERE tarea_id = 2")["id"]
        self.post(aux, f"/saneamiento/limpieza/{id_jefe}/quitar")   # no es suya: no la quita
        self.assertEqual(self.n("SELECT COUNT(*) n FROM limpieza_registros"), 2)
        id_aux = self.uno("SELECT id FROM limpieza_registros WHERE tarea_id = 1")["id"]
        self.post(aux, f"/saneamiento/limpieza/{id_aux}/quitar")    # suya y de hoy: sí
        self.assertEqual(self.n("SELECT COUNT(*) n FROM limpieza_registros"), 1)
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'limpieza_quitada'"))
        # El auxiliar no administra tareas
        self.assertEqual(aux.get("/saneamiento/limpieza/tareas").status_code, 403)

    def test_tareas_crear_editar_desactivar(self):
        self.post(self.c, "/saneamiento/limpieza/tareas", {"nombre": "Baño", "frecuencia": "quincenal"})
        t = self.uno("SELECT * FROM limpieza_tareas WHERE nombre = 'Baño'")
        self.assertEqual((t["frecuencia"], t["orden"]), ("quincenal", 4))
        self.post(self.c, f"/saneamiento/limpieza/tareas/{t['id']}", {"nombre": "Baño", "frecuencia": "semanal"})
        self.assertEqual(self.uno("SELECT frecuencia FROM limpieza_tareas WHERE id = ?", t["id"])["frecuencia"], "semanal")
        self.post(self.c, f"/saneamiento/limpieza/tareas/{t['id']}", {"accion": "activar"})
        self.assertEqual(self.uno("SELECT activa FROM limpieza_tareas WHERE id = ?", t["id"])["activa"], 0)
        self.marcar(tarea_id=t["id"])                            # inactiva: no se marca
        self.assertEqual(self.n("SELECT COUNT(*) n FROM limpieza_registros"), 0)

    def test_planilla_cuenta_el_cumplimiento(self):
        from app.saneamiento import planilla_mes
        self.marcar(tarea_id=1)
        with self.app.app_context():
            dias, filas = planilla_mes(HOY.replace(day=1))
        pisos = next(f for f in filas if f["tarea"]["nombre"] == "Pisos")
        self.assertEqual(pisos["periodos"], 1)                   # la tarea se creó hoy: solo cuenta hoy
        self.assertEqual(pisos["hechos"], 1)
        self.assertIn(HOY.day, pisos["marcas"])

    def test_aviso_de_limpieza_pendiente(self):
        from app.saneamiento import limpieza_pendiente_para_aviso
        with self.app.app_context():
            temprano = [t["nombre"] for t in limpieza_pendiente_para_aviso(datetime.combine(HOY, datetime.min.time()).replace(hour=9))]
            tarde = [t["nombre"] for t in limpieza_pendiente_para_aviso(datetime.combine(HOY, datetime.min.time()).replace(hour=16))]
        self.assertNotIn("Pisos", temprano)                      # las diarias se recuerdan desde las 3 p. m.
        self.assertIn("Pisos", tarde)
        self.marcar(tarea_id=1)
        with self.app.app_context():
            tarde = [t["nombre"] for t in limpieza_pendiente_para_aviso(datetime.combine(HOY, datetime.min.time()).replace(hour=16))]
        self.assertNotIn("Pisos", tarde)


class TestPlagas(BaseSaneamiento):
    def test_sin_registro_avisa_y_al_registrar_calcula_la_proxima(self):
        self.assertIn("plagas_sin", self.claves_inicio())
        self.post(self.c, "/saneamiento/plagas", {"fecha": "2026-01-31", "empresa": "Fumigar SAS",
                                                   "tipo": "integral",
                                                   "certificado": (io.BytesIO(b"%PDF-1.4 x"), "c.pdf")},
                  content_type="multipart/form-data")
        p = self.uno("SELECT * FROM control_plagas")
        self.assertEqual(p["proxima"], "2026-07-31")             # 6 meses después
        self.assertTrue(p["archivo"].startswith("uploads/saneamiento/"))
        self.assertNotIn("plagas_sin", self.claves_inicio())

    def test_validaciones_y_permisos(self):
        self.post(self.c, "/saneamiento/plagas", {"fecha": HOY.isoformat(), "empresa": ""})
        self.post(self.c, "/saneamiento/plagas", {"fecha": (HOY + timedelta(days=1)).isoformat(), "empresa": "X"})
        self.assertEqual(self.n("SELECT COUNT(*) n FROM control_plagas"), 0)
        aux = self.auxiliar()
        self.assertEqual(aux.get("/saneamiento/plagas").status_code, 200)
        self.assertEqual(self.post(aux, "/saneamiento/plagas", {"fecha": HOY.isoformat(), "empresa": "X"}).status_code, 403)


class TestResiduos(BaseSaneamiento):
    def test_registro_y_consolidado(self):
        self.post(self.c, "/saneamiento/residuos/registro", {"tipo": "cortopunzantes", "cantidad_kg": "0,5"})
        self.post(self.c, "/saneamiento/residuos/registro", {"tipo": "cortopunzantes", "cantidad_kg": "0,25"})
        self.post(self.c, "/saneamiento/residuos/registro", {"tipo": "cohetes", "cantidad_kg": "1"})      # tipo malo
        self.post(self.c, "/saneamiento/residuos/registro", {"tipo": "ordinarios", "cantidad_kg": "0"})   # sin kilos
        from app.saneamiento import resumen_residuos
        with self.app.app_context():
            registros, _, por_tipo = resumen_residuos(HOY.replace(day=1))
        self.assertEqual(len(registros), 2)
        self.assertAlmostEqual(por_tipo["cortopunzantes"], 0.75)

    def test_residuos_viejos_sin_entregar_avisan(self):
        viejo = (HOY - timedelta(days=100)).isoformat()
        self.post(self.c, "/saneamiento/residuos/registro", {"tipo": "farmaceuticos", "cantidad_kg": "1", "fecha": viejo})
        self.assertIn("residuos_sin_entregar", self.claves_inicio())
        self.post(self.c, "/saneamiento/residuos/entrega", {"fecha": HOY.isoformat(), "gestor": "Ecocapital",
                                                            "tipos": ["farmaceuticos"], "cantidad_kg": "1"})
        self.assertEqual(self.uno("SELECT tipos FROM residuos_entregas")["tipos"],
                         "Medicamentos vencidos, deteriorados o parcialmente usados")
        self.assertNotIn("residuos_sin_entregar", self.claves_inicio())

    def test_baja_de_vencidos_saca_del_inventario_y_registra_el_residuo(self):
        con = self.db()
        con.execute("INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
                    "costo_unitario, estado, creado_en) VALUES (1, 'V1', ?, 10, 10, 100, 'disponible', ?)",
                    ((HOY - timedelta(days=5)).isoformat(), HOY.isoformat()))
        con.execute("INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
                    "costo_unitario, estado, creado_en) VALUES (1, 'BUENO', ?, 10, 10, 100, 'disponible', ?)",
                    ((HOY + timedelta(days=300)).isoformat(), HOY.isoformat()))
        con.commit()
        con.close()
        self.post(self.c, "/saneamiento/residuos/baja-vencidos", {"lote_id": ["1", "2"], "cantidad_kg": ""})
        self.assertEqual(self.uno("SELECT cantidad_disponible c FROM lotes WHERE id = 1")["c"], 10)   # sin peso: nada
        self.post(self.c, "/saneamiento/residuos/baja-vencidos", {"lote_id": ["1", "2"], "cantidad_kg": "0,2"})
        self.assertEqual(self.uno("SELECT cantidad_disponible c FROM lotes WHERE id = 1")["c"], 0)
        self.assertEqual(self.uno("SELECT cantidad_disponible c FROM lotes WHERE id = 2")["c"], 10)   # el bueno no
        mov = self.uno("SELECT * FROM movimientos_inventario WHERE tipo = 'baja'")
        self.assertEqual((mov["cantidad"], mov["referencia"]), (-10, "Baja por vencimiento"))
        r = self.uno("SELECT * FROM residuos_registros")
        self.assertEqual((r["tipo"], r["cantidad_kg"]), ("farmaceuticos", 0.2))
        self.assertIn("V1", r["descripcion"])

    def test_auxiliar_registra_pero_no_entrega_ni_da_de_baja(self):
        aux = self.auxiliar()
        self.post(aux, "/saneamiento/residuos/registro", {"tipo": "ordinarios", "cantidad_kg": "2"})
        self.assertEqual(self.n("SELECT COUNT(*) n FROM residuos_registros"), 1)
        self.assertEqual(self.post(aux, "/saneamiento/residuos/entrega", {"fecha": HOY.isoformat(), "gestor": "X"}).status_code, 403)
        self.assertEqual(self.post(aux, "/saneamiento/residuos/baja-vencidos", {"lote_id": ["1"], "cantidad_kg": "1"}).status_code, 403)


class TestPantallasYPdf(BaseSaneamiento):
    def test_pantallas_y_pdfs(self):
        self.marcar()
        self.post(self.c, "/saneamiento/residuos/registro", {"tipo": "ordinarios", "cantidad_kg": "1,5"})
        for url in ("/saneamiento/", "/saneamiento/limpieza", "/saneamiento/limpieza?mes=2026-01",
                    "/saneamiento/limpieza/tareas", "/saneamiento/limpieza/tareas/1",
                    "/saneamiento/plagas", "/saneamiento/residuos"):
            self.assertIn(self.c.get(url, follow_redirects=True).status_code, (200,), url)
        for url in ("/saneamiento/limpieza/planilla.pdf", "/saneamiento/residuos/mes.pdf"):
            r = self.c.get(url)
            self.assertEqual(r.mimetype, "application/pdf", url)
            self.assertTrue(r.data.startswith(b"%PDF"))
