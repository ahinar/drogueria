"""Crea una base de datos de DEMOSTRACIÓN con datos inventados para probar el programa.

¿Para qué sirve?
    Para probar el programa en la nube (GitHub Codespaces) o en otro computador
    SIN usar la base de datos real de la droguería.

¿Cómo se usa?
    1. Se indica dónde va la base de demo con la variable DROGUERIA_DB
       (si no se indica, NO hace nada, para no tocar nunca la base real).
    2. Se ejecuta:  python scripts/crear_demo.py
    3. Si esa base ya tiene usuarios, no hace nada (se puede ejecutar muchas veces).

Usuarios de prueba (contraseña de todos: Demo1234!):
    admin -> Administrador      dt -> Director técnico      aux -> Auxiliar
"""
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Para poder importar "app" y "config" desde la carpeta del proyecto
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

CLAVE_DEMO = "Demo1234!"


def main():
    # ---- 0. Seguridad: solo trabaja si se le dice explícitamente qué base usar ----
    ruta = os.environ.get("DROGUERIA_DB")
    if not ruta:
        print("No se indicó DROGUERIA_DB. Para no tocar la base real, no se hace nada.")
        return
    if Path(ruta).resolve() == (RAIZ / "db" / "drogueria.db").resolve():
        print("DROGUERIA_DB apunta a la base REAL. La demo no se crea ahí.")
        return

    # ---- 1. Crear la base con todas sus tablas (las migraciones las hace create_app) ----
    from werkzeug.security import generate_password_hash
    from app import create_app
    create_app({"DB_PATH": ruta, "TESTING": True, "SECRET_KEY": "solo-para-crear-tablas"})

    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    if con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]:
        print(f"La demo ya existe en {ruta}. No se cambia nada.")
        return

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hoy = date.today()
    dias = lambda n: (hoy + timedelta(days=n)).isoformat()   # fecha a n días de hoy

    # ---- 2. Datos del negocio (inventados) ----
    for clave, valor in {
        "nombre_comercial": "Fervifarma (DEMO)", "razon_social": "Droguería de Prueba S.A.S.",
        "nit": "900.000.000-1", "ciudad": "Colombia", "direccion": "Calle Falsa 123",
        "regente_nombre": "Director Técnico de Prueba", "regente_tarjeta": "TP-0000",
        "pie_pagina": "Documento de demostración. Datos inventados.",
    }.items():
        con.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)", (clave, valor))

    # ---- 3. Usuarios de prueba (uno por rol) ----
    for nombre, usuario, rol in (("Fernando (demo)", "admin", "administrador"),
                                 ("Director técnico (demo)", "dt", "director_tecnico"),
                                 ("Auxiliar (demo)", "aux", "auxiliar")):
        con.execute("INSERT INTO usuarios (nombre, usuario, clave_hash, rol, activo, creado_en) "
                    "VALUES (?, ?, ?, ?, 1, ?)",
                    (nombre, usuario, generate_password_hash(CLAVE_DEMO), rol, ahora))

    # ---- 4. Proveedores ----
    proveedores = {}
    for nit, nombre in (("900111222", "DISTRIBUIDORA EJEMPLO S.A.S."), ("900333444", "DROGUERÍAS MAYORISTAS DEMO")):
        cur = con.execute("INSERT INTO proveedores (nit, razon_social, creado_en) VALUES (?, ?, ?)",
                          (nit, nombre, ahora))
        proveedores[nombre] = cur.lastrowid

    def catalogo(tipo, nombre):
        fila = con.execute("SELECT id FROM catalogos WHERE tipo = ? AND nombre = ?", (tipo, nombre)).fetchone()
        return fila["id"] if fila else None

    # ---- 5. Productos con categoría y usos (para probar el buscador por síntoma) ----
    # (nombre, concentración, código de barras, precio, precio máximo, IVA %, fórmula, categoría, usos, stock mínimo)
    productos = [
        # Estos dos se venden por TABLETA y además por sobre y caja (ver paso 5b)
        ("ACETAMINOFEN 500 MG TABLETA", "500 mg", "7700000000011", 200, 250, 0, 0, "Analgésicos", ["Dolor", "Fiebre"], 30),
        ("IBUPROFENO 400 MG TABLETA", "400 mg", "7700000000028", 300, 350, 0, 0, "Antiinflamatorios", ["Dolor", "Inflamación"], 20),
        ("DOLEX GRIPA X 12 TAB", "", "7700000000035", 9800, 11000, 0, 0, "Antigripales", ["Gripe", "Congestión nasal", "Dolor"], 5),
        ("NOXPIRIN NOCHE SOBRE", "", "7700000000042", 3600, 4000, 0, 0, "Antigripales", ["Gripe", "Tos"], 10),
        ("LORATADINA X 10 TAB", "10 mg", "7700000000059", 2000, 2600, 0, 0, "Antihistamínicos", ["Alergia"], 5),
        ("SAL DE FRUTAS LUA SOBRE", "", "7700000000066", 1200, 0, 0, 0, "Gastrointestinales", ["Acidez"], 20),
        ("SUERO ORAL X 500 ML", "", "7700000000073", 4500, 0, 0, 0, "Gastrointestinales", ["Diarrea"], 5),
        ("AMOXICILINA X 50 CAP", "500 mg", "7700000000080", 18000, 22000, 0, 1, "Antibióticos", ["Infección"], 3),
        ("ACICLOVIR CREMA", "5 %", "7700000000097", 9800, 11200, 0, 0, "Dermatológicos", ["Dermatitis"], 3),
        ("CREMA CICATRIZANTE X 30 G", "", "7700000000103", 12500, 0, 19, 0, "Dermatológicos", ["Cicatrizante"], 3),
        ("JERINGA 5 ML", "", "7700000000110", 600, 0, 19, 0, "Dispositivos médicos y ayudas", [], 50),
        ("VITAMINA C X 100 TAB", "500 mg", "7700000000127", 15000, 0, 0, 0, "Vitaminas y suplementos", ["Cansancio", "Deficiencia de vitaminas"], 5),
    ]
    # Unidades de medida para vender por presentación (la "Unidad" ya existe)
    unidades = {"Unidad": con.execute("SELECT id FROM unidades_medida WHERE nombre = 'Unidad'").fetchone()[0]}
    for nombre_u, cantidad_u in (("Tableta", 1), ("Sobre x 10", 10), ("Caja x 100", 100)):
        unidades[nombre_u] = con.execute(
            "INSERT INTO unidades_medida (nombre, cantidad, activo, creado_en) VALUES (?, ?, 1, ?)",
            (nombre_u, cantidad_u, ahora)).lastrowid

    ids = []
    for i, (nombre, conc, barras, precio, maximo, iva, formula, cat, usos, minimo) in enumerate(productos, start=1):
        cur = con.execute(
            "INSERT INTO productos (codigo, codigo_barras, nombre, concentracion, precio_venta, precio_maximo, "
            "precio_compra, iva_tipo, iva_tarifa, requiere_formula, maneja_vencimiento, stock_minimo, "
            "unidad_venta_id, activo, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (f"P{i:05d}", barras, nombre, conc or None, precio, maximo or None, round(precio * 0.62),
             "gravado" if iva else "excluido", iva, formula, 0 if nombre.startswith("JERINGA") else 1,
             minimo, unidades["Tableta" if "TABLETA" in nombre else "Unidad"], ahora))
        pid = cur.lastrowid
        ids.append(pid)
        if catalogo("categoria", cat):
            con.execute("INSERT INTO productos_categorias (producto_id, catalogo_id) VALUES (?, ?)",
                        (pid, catalogo("categoria", cat)))
        for uso in usos:
            if catalogo("uso", uso):
                con.execute("INSERT INTO productos_usos (producto_id, catalogo_id) VALUES (?, ?)",
                            (pid, catalogo("uso", uso)))

    # Para ver el panel de alertas del Inicio: un registro INVIMA por vencer
    # y un proveedor con el concepto sanitario vencido
    con.execute("UPDATE productos SET registro_sanitario = 'INVIMA 2016M-0000000-R1', registro_vence = ? "
                "WHERE id = ?", (dias(45), ids[8]))
    con.execute("UPDATE proveedores SET concepto_sanitario = 'Favorable', concepto_vence = ? WHERE id = ?",
                (dias(-5), proveedores["DROGUERÍAS MAYORISTAS DEMO"]))

    # ---- 5b. Presentaciones: sobre x 10 y caja x 100 (el inventario va en tabletas) ----
    # (producto, unidad, cuántas tabletas trae, precio, código de barras de esa presentación)
    for idx, unidad_nombre, factor, precio, barras in (
            (0, "Sobre x 10", 10, 1800, "7700000001011"),
            (0, "Caja x 100", 100, 15000, "7700000002011"),
            (1, "Sobre x 10", 10, 2800, "7700000001028")):
        con.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                    "codigo_barras, creado_en) VALUES (?,?,?,?,?,?)",
                    (ids[idx], unidades[unidad_nombre], factor, precio, barras, ahora))

    # ---- 6. Compras aprobadas (recepciones) que crean los lotes ----
    # Cada fila: (producto, lote, vence en N días, cantidad, costo, proveedor, compra hace N días)
    compras = [
        (0, "AC2401", 400, 300, 90, "DISTRIBUIDORA EJEMPLO S.A.S.", 40),   # en tabletas
        (0, "AC2455", 25, 8, 88, "DROGUERÍAS MAYORISTAS DEMO", 70),        # vence pronto
        (1, "IB1102", 500, 200, 150, "DISTRIBUIDORA EJEMPLO S.A.S.", 20),
        (2, "DG3301", 300, 4, 6100, "DISTRIBUIDORA EJEMPLO S.A.S.", 30),     # bajo stock mínimo
        (3, "NX0901", 200, 30, 2200, "DROGUERÍAS MAYORISTAS DEMO", 15),
        (4, "LO5521", 350, 20, 1100, "DISTRIBUIDORA EJEMPLO S.A.S.", 45),
        (5, "LU7788", 600, 50, 650, "DROGUERÍAS MAYORISTAS DEMO", 10),
        (6, "SO1200", 180, 12, 2700, "DISTRIBUIDORA EJEMPLO S.A.S.", 25),
        (7, "AM4411", 365, 6, 11500, "DISTRIBUIDORA EJEMPLO S.A.S.", 35),
        (8, "AV2209", 250, 5, 6300, "DROGUERÍAS MAYORISTAS DEMO", 12),
        (9, "CC6610", 420, 6, 7800, "DISTRIBUIDORA EJEMPLO S.A.S.", 18),
        (10, "", 900, 100, 350, "DROGUERÍAS MAYORISTAS DEMO", 5),
        (11, "VC3030", -10, 3, 9000, "DISTRIBUIDORA EJEMPLO S.A.S.", 200),   # ya vencido
    ]
    for n, (idx, lote, vence, cant, costo, prov, hace) in enumerate(compras, start=1):
        fecha = (datetime.now() - timedelta(days=hace)).strftime("%Y-%m-%d 10:00:00")
        rec = con.execute(
            "INSERT INTO recepciones (numero, fecha, proveedor_id, factura_numero, estado, recibido_por_nombre, "
            "aprobado_por_nombre, aprobado_en, creado_en) VALUES (?,?,?,?, 'aprobada', 'Auxiliar (demo)', "
            "'Director técnico (demo)', ?, ?)",
            (f"REC-{n:04d}", fecha, proveedores[prov], f"FV-{1000 + n}", fecha, fecha)).lastrowid
        linea = con.execute(
            "INSERT INTO recepcion_lineas (recepcion_id, producto_id, lote, vencimiento, cantidad_facturada, "
            "cantidad_recibida, costo_unitario, resultado) VALUES (?,?,?,?,?,?,?, 'aceptado')",
            (rec, ids[idx], lote or None, dias(vence) if lote else None, cant, cant, costo)).lastrowid
        con.execute(
            "INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
            "costo_unitario, estado, recepcion_id, recepcion_linea_id, creado_en) "
            "VALUES (?,?,?,?,?,?, 'disponible', ?,?,?)",
            (ids[idx], lote or None, dias(vence) if lote else None, cant, cant, costo, rec, linea, fecha))

    # Un lote en cuarentena (recepción sin aprobar) para ver ese estado
    rec = con.execute("INSERT INTO recepciones (numero, fecha, proveedor_id, factura_numero, estado, "
                      "recibido_por_nombre, creado_en) VALUES ('REC-0099', ?, ?, 'FV-2000', 'cuarentena', "
                      "'Auxiliar (demo)', ?)", (ahora, proveedores["DISTRIBUIDORA EJEMPLO S.A.S."], ahora)).lastrowid
    con.execute("INSERT INTO recepcion_lineas (recepcion_id, producto_id, lote, vencimiento, cantidad_facturada, "
                "cantidad_recibida, costo_unitario, resultado) VALUES (?,?, 'LO6001', ?, 20, 20, 1150, 'aceptado')",
                (rec, ids[4], dias(380)))

    # ---- 7. Plata en la caja menor para poder abrir la caja del POS sin "sobregiro" ----
    con.execute("INSERT INTO caja_menor_movimientos (fecha, tipo, monto, motivo, usuario_nombre, creado_en) "
                "VALUES (?, 'aporte', 300000, 'Fondo inicial (demo)', 'Fernando (demo)', ?)", (ahora, ahora))

    # ---- 7b. Equipos con su calibración (Equipos y calibraciones) ----
    # El de la nevera vence en 20 días, para ver el aviso amarillo en el Inicio.
    zonas = {f["nombre"]: f["id"] for f in con.execute("SELECT id, nombre FROM zonas_temperatura")}
    for nombre, tipo, zona, calibrado_hace, vence_en in (
            ("Termohigrómetro ambiente", "termohigrometro", "Ambiente", 300, 65),
            ("Termohigrómetro nevera", "termohigrometro", "Nevera", 345, 20)):
        eq = con.execute(
            "INSERT INTO equipos (nombre, tipo, marca, zona_id, fecha_calibracion, proxima_calibracion, "
            "frecuencia_meses, activo, creado_en) VALUES (?,?, 'Marca demo', ?,?,?, 12, 1, ?)",
            (nombre, tipo, zonas.get(zona), dias(-calibrado_hace), dias(vence_en), ahora)).lastrowid
        con.execute("INSERT INTO calibraciones (equipo_id, fecha, proxima, empresa, certificado_numero, resultado, "
                    "usuario_nombre, creado_en) VALUES (?,?,?, 'Laboratorio de metrología (demo)', ?, 'conforme', "
                    "'Fernando (demo)', ?)", (eq, dias(-calibrado_hace), dias(vence_en), f"CAL-{eq:04d}", ahora))

    # ---- 8. Gastos de este mes y del anterior (para ver Reportes → Utilidades) ----
    # Las ventas no se inventan: haz unas ventas en el POS y mira cómo cambia la utilidad.
    mes_pasado = (hoy.replace(day=1) - timedelta(days=1)).replace(day=5).isoformat()
    for categoria, descripcion, monto, fecha in (
            ("Arriendo", "Arriendo del local", 1200000, hoy.replace(day=1).isoformat()),
            ("Servicios públicos", "Energía y agua", 185000, hoy.isoformat()),
            ("Sueldo del dueño", "Sueldo Fernando", 900000, hoy.isoformat()),
            ("Arriendo", "Arriendo del local", 1200000, mes_pasado),
            ("Servicios públicos", "Energía y agua", 172000, mes_pasado)):
        con.execute("INSERT INTO gastos (fecha, categoria_id, descripcion, monto, forma_pago, usuario_nombre, "
                    "creado_en) VALUES (?,?,?,?, 'transferencia', 'Fernando (demo)', ?)",
                    (fecha, catalogo("categoria_gasto", categoria), descripcion, monto, ahora))
    # Un retiro de ganancia del dueño desde la caja menor
    con.execute("INSERT INTO caja_menor_movimientos (fecha, tipo, monto, motivo, usuario_nombre, retiro_dueno, "
                "creado_en) VALUES (?, 'retiro', 50000, 'Retiro de ganancia (demo)', 'Fernando (demo)', 1, ?)",
                (ahora, ahora))

    con.commit()
    con.close()
    print(f"Demo creada en {ruta}")
    print(f"Usuarios: admin / dt / aux   ·   Contraseña: {CLAVE_DEMO}")


if __name__ == "__main__":
    main()
