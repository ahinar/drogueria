"""
PRUEBAS DE LA VERSIÓN 1.1.19 (la lista de pedidos de Fernando del 10 y 13 de noviembre)
=======================================================================================
  1. TestLimpiezaInicio: el recuadro «Limpieza» del Inicio desde que se abre el local,
     con colores (gris / amarillo / hecha / atrasada) y el botón «✓ Hecho».
  2. TestSubtotalRecepcion: la columna «Subtotal» al ver una recepción, que cuadra con
     el «Subtotal (sin IVA)» de abajo.
  3. TestTablasCompactas: todas las listas en un renglón, cebra y columnas ajustables
     (static/js/tablas.js), menos la recepción donde se recibe.
  4. TestListaProductos: sin botones en las filas, el nombre como enlace a la ficha y el
     botón «Acciones (N) ▾» arriba.
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reportes import BaseReportes


# =====================================================================
# 1. LIMPIEZA EN EL INICIO
# =====================================================================
class TestLimpiezaInicio(BaseReportes):
    def tareas(self, cuando):
        with self.app.test_request_context():
            from app.saneamiento import limpieza_para_inicio
            return {t["nombre"]: t for t in limpieza_para_inicio(cuando)}

    def marcar(self, nombre, fecha):
        con = self.db()
        tid = con.execute("SELECT id FROM limpieza_tareas WHERE nombre = ?", (nombre,)).fetchone()[0]
        con.execute("INSERT INTO limpieza_registros (tarea_id, fecha, usuario_id, usuario_nombre, creado_en) "
                    "VALUES (?, ?, 1, 'x', ?)", (tid, fecha, fecha + " 10:00:00"))
        con.commit()
        con.close()

    def antiguas(self):
        """Que las tareas existan desde hace tiempo (si no, no pueden estar «atrasadas»)."""
        con = self.db()
        con.execute("UPDATE limpieza_tareas SET creado_en = '2020-01-01 00:00:00'")
        con.commit()
        con.close()

    def test_se_ve_desde_temprano(self):
        """A las 9 a. m. ya salen todas (antes solo salían a las 3 p. m. o al final de la semana)."""
        t = self.tareas(datetime.combine(date.today(), datetime.min.time()).replace(hour=9))
        self.assertEqual(t["Pisos"]["estado"], "gris")
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("limpieza-inicio", html)
        self.assertIn("✓ Hecho", html)
        self.assertIn("Pisos", html)

    def test_amarillo_en_la_tarde(self):
        t = self.tareas(datetime.combine(date.today(), datetime.min.time()).replace(hour=16))
        self.assertEqual(t["Pisos"]["estado"], "amarillo")

    def test_hecha_y_atrasada(self):
        self.antiguas()
        hoy = date.today()
        self.marcar("Pisos", hoy.isoformat())
        t = self.tareas(datetime.combine(hoy, datetime.min.time()).replace(hour=10))
        self.assertEqual(t["Pisos"]["estado"], "hecha")
        self.assertTrue(t["Pisos"]["atrasada"])                  # ayer no se marcó
        self.marcar("Pisos", (hoy - timedelta(days=1)).isoformat())
        t = self.tareas(datetime.combine(hoy, datetime.min.time()).replace(hour=10))
        self.assertFalse(t["Pisos"]["atrasada"])

    def test_tarea_nueva_no_sale_atrasada(self):
        con = self.db()
        con.execute("UPDATE limpieza_tareas SET creado_en = ?", (date.today().isoformat() + " 08:00:00",))
        con.commit()
        con.close()
        t = self.tareas(datetime.now())
        self.assertFalse(any(x["atrasada"] for x in t.values()))

    def test_boton_hecho_desde_el_inicio(self):
        tid = self.uno("SELECT id FROM limpieza_tareas WHERE nombre = 'Pisos'")["id"]
        self.post(self.c, "/saneamiento/limpieza/marcar", {"tarea_id": str(tid)}, headers={"Referer": "/"})
        self.assertEqual(self.uno(f"SELECT COUNT(*) n FROM limpieza_registros WHERE tarea_id = {tid}")["n"], 1)

    def test_el_aviso_viejo_no_se_repite_en_el_inicio(self):
        html = self.c.get("/").get_data(as_text=True)
        self.assertNotIn('data-clave="limpieza_pendiente"', html)


# =====================================================================
# 2. SUBTOTAL AL VER UNA RECEPCIÓN
# =====================================================================
class TestSubtotalRecepcion(BaseReportes):
    def test_columna_subtotal_y_suma(self):
        self.recepcion(costo=500, cantidad=4)
        rid = self.uno("SELECT MAX(id) i FROM recepciones")["i"]
        html = self.c.get(f"/recepciones/{rid}").get_data(as_text=True)
        self.assertIn(">Subtotal<", html)
        self.assertIn("$2.000", html)                          # 4 × $500
        self.assertIn("Suma de las líneas (sin IVA)", html)


# =====================================================================
# 3. TABLAS COMPACTAS
# =====================================================================
class TestTablasCompactas(BaseReportes):
    def test_todas_las_paginas_cargan_el_codigo(self):
        html = self.pagina_con_js(self.c, "/productos/?vista=lista")
        self.assertIn("js/tablas.js", html)
        self.assertIn("compactarTodo", html)
        self.assertIn("tabla-recepcion", html)                  # (la de recibir queda por fuera)

    def test_estilos(self):
        css = (Path(__file__).resolve().parent.parent / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("table.compacta { font-size: 12px; }", css)
        self.assertIn("nth-child(even)", css)
        self.assertIn(".col-asa", css)

    def test_recepcion_en_curso_no_se_compacta(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn('class="tabla tabla-recepcion"', html)


# =====================================================================
# 4. LISTA DE PRODUCTOS: ACCIONES ARRIBA
# =====================================================================
class TestListaProductos(BaseReportes):
    def test_sin_botones_en_las_filas(self):
        html = self.c.get("/productos/?vista=lista").get_data(as_text=True)
        tabla = html[html.index('<table class="tabla tabla-productos">'):]
        tabla = tabla[:tabla.index("</table>")]
        self.assertNotIn(">Desactivar</button>", tabla)
        self.assertNotIn(">Editar</a>", tabla)
        self.assertIn('class="enlace-fila" href="/productos/1/editar"', tabla)     # el nombre es el enlace
        self.assertIn('data-url="/productos/1/editar"', tabla)                     # doble clic

    def test_boton_acciones(self):
        html = self.pagina_con_js(self.c, "/productos/?vista=lista")
        self.assertIn('id="acciones-boton"', html)
        self.assertIn('data-accion="editar" class="solo-uno"', html)
        self.assertIn('data-accion="eliminar"', html)
        self.assertIn("dblclick", html)

    def test_las_acciones_siguen_funcionando(self):
        r = self.post(self.c, "/productos/masivo", {"ids": ["1", "2"], "accion": "desactivar"}, follow_redirects=True)
        self.assertIn("Desactivar", r.get_data(as_text=True))
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM productos WHERE id IN (1, 2) AND activo = 0")["n"], 2)

    def test_auxiliar_no_ve_acciones(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c2 = self.cliente()
        self.entrar(c2, "aux")
        html = c2.get("/productos/?vista=lista").get_data(as_text=True)
        self.assertNotIn('id="acciones-boton"', html)
        self.assertNotIn('class="enlace-fila"', html)
