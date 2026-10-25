# PROYECTO: Sistema de gestión de calidad + POS para droguería Fervifarma

> Documento maestro. Se adjunta al inicio de cada chat nuevo para retomar el trabajo sin perder el hilo.

## 0. Cómo usar este documento

1. En un chat nuevo, adjunta este archivo (y el código actual de la carpeta del proyecto si ya existe).
2. Escribe: "Continuamos con la Fase X, paso Y" (mira la sección 8).
3. Trabaja **un paso pequeño por vez**. Nunca pidas "todo el programa" en un solo mensaje.
4. Al terminar cada paso: guarda los archivos, prueba que funcione y actualiza la sección 8 (Estado).
5. Si el chat se llena, no pasa nada: abre uno nuevo y repite desde el punto 1.

## 1. Decisiones tomadas

- Programa para una droguería en Colombia con **gestión de calidad + POS**.
- **Temperaturas:** registro con recordatorios sonoros y visuales llamativos, una lectura AM y una PM por zona.
- **Recepción técnica:** alimenta el inventario, guarda el Acta en PDF según la norma.
- **Utilidades y ganancias** calculadas por períodos.
- **Fácil y sencillo**, datos respaldados.
- **Dos computadores en el local:** mostrador (servidor) y bodega (cliente por navegador).
- **Sin facturación electrónica por ahora**, pero con campos reservados para agregarla.
- A futuro: conexión a alertas sanitarias (INVIMA), IA para clasificación de productos.
- **Control especial (FNE):** el flujo completo se deja para una fase posterior.

## 2. Stack técnico (CONFIRMADO: Flask + SQLite)

- **Python + Flask + SQLite**, interfaz web en la red local.
- PC principal = servidor. PC secundario = cliente por navegador.
- Funciona **sin internet**.
- **Pillow** para imágenes, **reportlab** para PDFs, **openpyxl** para Excel, **Chart.js** local para gráficos, **Waitress** para servir en producción.

### Estructura de carpetas

### Principios

- Los registros legales (temperaturas, recepciones) **no se editan ni se borran**: una corrección es un registro nuevo que referencia al anterior, con motivo. Las ventas se **anulan**, no se borran.
- **Bitácora inmutable** con triggers a nivel de SQLite.
- **Roles:** Administrador, Director Técnico, Auxiliar.
- **Respaldo diario automático** verificado con `PRAGMA integrity_check`.
- Servidor solo en red local.

## 3. Modelo de datos (tablas implementadas)

### Base
- `usuarios`: nombre, usuario, clave_hash, rol, activo, creado_en, ultimo_ingreso.
- `bitacora`: fecha, usuario_id, usuario_nombre, accion, tabla, registro_id, detalle, ip. **Con triggers que impiden UPDATE y DELETE.**
- `config`: clave (PK), valor. Almacena NIT, razón social, dirección, teléfono, regente, `logo_ruta`, `pie_pagina`.
- `schema_version`: versiones de migración aplicadas.

### Catálogos
- `catalogos`: tipo (categoria / forma_farmaceutica / principio / laboratorio / uso / tipo_pago), nombre, descripcion, activo. Único por (tipo, nombre).
- `unidades_medida`: nombre, cantidad (factor), referencia_id, activo.

### Productos y proveedores
- `proveedores`: NIT, razón social, nombre_comercial, contacto, teléfono, correo, dirección, ciudad, concepto sanitario, concepto_vence, certificaciones, activo.
- `productos`: código único, código de barras, nombre, descripción, grupo, `principio_id`, `laboratorio_id`, `forma_farmaceutica_id`, `unidad_venta_id`, concentración, registro_sanitario, registro_vence, precio_compra, precio_venta, precio_maximo, IVA (tipo + tarifa), stock_minimo, requiere_formula, cadena_frio, control_especial, maneja_vencimiento, imagen, activo.
- `productos_categorias`: M:N producto ↔ categorías.
- `productos_usos`: M:N producto ↔ usos.
- `producto_presentaciones`: otras formas de vender un producto (sobre, caja…): `unidad_id` (nombre de unidades_medida), `factor` (cuántas unidades principales trae, > 1), `precio_venta`, `precio_maximo`, `codigo_barras`. Única por (producto, unidad).

### Temperaturas
- `zonas_temperatura`: nombre, descripción, temp_min, temp_max, controla_humedad, humedad_min, humedad_max, horarios, dias_semana, minutos_tolerancia, activa.
- `temperatura_registros`: zona_id, equipo_id, fecha, programada_para, temperatura, humedad, dentro_de_rango, accion_correctiva, usuario_id, usuario_nombre.
- `equipos`: nombre, tipo (termohigrómetro, nevera, data logger, termómetro, balanza, tensiómetro, glucómetro, otro), marca, modelo, serie, zona_id, fecha_calibracion, proxima_calibracion, frecuencia_meses, activo.
- `calibraciones`: equipo_id, fecha, proxima, empresa, certificado_numero, resultado (conforme / no_conforme), archivo (PDF o foto en `static/uploads/certificados/`, que no se sube a GitHub), usuario.

### Recepción técnica e inventario
- `recepciones`: número único (REC-####), fecha, proveedor_id, factura_numero, remision_numero, temperatura_llegada, estado (borrador/cuarentena/aprobada/rechazada), recibido_por, aprobado_por, observaciones, foto_ruta.
- `recepcion_lineas`: recepcion_id, producto_id, lote, vencimiento, cantidad_facturada, cantidad_recibida, costo_unitario, estado_empaque, resultado, motivo_rechazo, temperatura_ingreso, clasificacion_defecto.
- `lotes`: producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, costo_unitario, estado (cuarentena/disponible/bloqueado/agotado/rechazado), motivo_bloqueo, recepcion_id, recepcion_linea_id.
- `movimientos_inventario`: fecha, lote_id, producto_id, tipo (recepcion/venta/devolucion/ajuste/baja/traslado), cantidad, referencia, referencia_id, usuario_id, usuario_nombre, observaciones.

### POS y contabilidad
- `cajas`: número único, abierta_en, abierta_por, efectivo_inicial, detalle_apertura (JSON), cerrada_en, cerrada_por, efectivo_contado, diferencia, detalle_cierre (JSON), observaciones_apertura, observaciones_cierre, estado.
- `caja_movimientos`: caja_id, fecha, tipo (ingreso/salida), forma_pago (efectivo/nequi/davivienda/tarjeta), monto, motivo, usuario_id, usuario_nombre.
- `ventas`: consecutivo (V-####), fecha, caja_id, cliente_nombre, cliente_documento, subtotal, descuento, iva, total, forma_pago, monto_recibido, cambio, observaciones, usuario_id, usuario_nombre, estado (completada/anulada), motivo_anulacion, anulada_en, anulada_por, y campos reservados para facturación electrónica (factura_numero, cufe, estado_dian, pdf_ruta, xml_ruta).
- `venta_lineas`: venta_id, producto_id, producto_codigo, producto_nombre, presentacion, factor, cantidad, precio_unitario, descuento_linea, iva_tipo, iva_tarifa, subtotal, iva_valor, total, lotes_json.

## 4. Reglas de negocio implementadas

**Estados de lote:** cuarentena → disponible (al aprobar la recepción) → agotado. Puede quedar bloqueado o rechazado.

**Recepción técnica:**
- Requiere proveedor + (factura o remisión) + al menos una línea.
- Por línea: producto, cantidad recibida > 0, costo > 0. Si el producto maneja vencimiento, también lote y vencimiento obligatorios.
- Guarda el Acta de Recepción Técnica en PDF con logo y firmas.
- Solo lo aceptado genera lotes disponibles.

**Temperaturas:**
- Máximo **una lectura AM y una PM por zona por día**.
- AM: antes de las 12:00. PM: de 12:00 a 19:00. Noche: después de las 19:00 (para zonas configuradas con 3 horarios).
- Alarma sonora y visual **global** en todas las páginas cuando hay lectura pendiente.
- Botones: silenciar sonido (10 min) y aplazar 10 minutos.
- Lectura fuera de rango → obliga acción correctiva.

**POS:**
- Solo una caja abierta a la vez.
- Movimientos de caja: ingreso / salida por efectivo, Nequi o Davivienda.
- Cierre de caja: desglose por forma de pago, arqueo con diferencia.
- Venta: descuenta del lote con **vencimiento más próximo (FEFO)**.

**Utilidades (pendiente):**
- Utilidad bruta = ventas netas − costo de lo vendido.
- Utilidad neta = utilidad bruta − gastos − mermas.

## 5. Módulos implementados

### 5.1 Dashboard (Inicio)
- Saludo personalizado, fecha en español.
- Tarjeta de temperatura (Al día / X pendientes).
- Tarjeta de productos activos.
- Tarjeta de lotes por vencer (clicable a semáforo).
- Tarjeta de ventas del día.
- **Panel "Para atender hoy"** (`app/alertas.py`): tarjetas que se abren y se cierran; rojas primero y abiertas; máximo 5 casos por tarjeta con enlace, más "… y N más" y un botón "Ver todos". Si no hay nada: "✅ Todo en orden".
  - 🔴 Lotes vencidos que aún tienen unidades · precio por encima del máximo (también por presentación) · INVIMA vencido · proveedor con concepto sanitario vencido · productos agotados (solo los que tienen stock mínimo).
  - 🟡 INVIMA vence en ≤ 90 días · concepto del proveedor vence en ≤ 30 días · en o por debajo del stock mínimo · lotes que vencen en ≤ 30 días · recepciones en cuarentena · productos sin precio · caja abierta desde un día anterior.
  - Por rol: el auxiliar no ve las de proveedores ni "sin precio"; sus enlaces de producto van al kardex (no puede editar). El jefe va directo a editar.
- Panel de últimas lecturas de temperatura.
- Panel de últimos productos agregados.
- Botón verde "Comenzar a vender".

### 5.2 Productos
- CRUD completo con validaciones.
- Tabs: General / Inventario / Categorías y usos / Notas.
- Código interno auto-generado (P00001, P00002…).
- Múltiples categorías y usos.
- Imagen del producto con preview.
- Vista Mosaico / Lista con toggle.
- Autocompletado de concentración.
- Cálculo de precio sugerido (÷ 1 − margen).
- Alta rápida desde recepción.
- **Otras presentaciones** (en la pestaña General, debajo de Precios): filas con unidad, ¿cuántas trae?, precio, precio máximo y código de barras. "¿Cuántas trae?" se sugiere solo con la cantidad de la unidad; debajo muestra "≈ $180 por Tableta (normal: $200)". Valida: factor > 1, precio > 0, precio ≤ su máximo, no repetir la unidad principal ni otra fila, código de barras único (contra productos y otras presentaciones).

### 5.3 Proveedores
- CRUD con NIT, razón social, contacto, documentación sanitaria.

### 5.4 Catálogos (Administración)
- Índice con 6 tarjetas.
- Categorías, Categorías de gasto, Formas farmacéuticas, Principios activos, Laboratorios, **Usos y síntomas**.
- **Usos y síntomas = mini vademécum:** en el POS se puede buscar por síntoma ("gripa", "agrieras", "rasquiña"). Busca en el nombre del uso y en su **descripción**, donde van palabras parecidas separadas por coma. Los 15 usos de fábrica ya traen sinónimos (migración 19). La tarjeta muestra "🩺 Sirve para…" y la ventana "i" muestra principio activo y usos.
- ~~Tipos de pago~~ se quitó: el POS usa formas de pago fijas (efectivo, Nequi, Davivienda, tarjeta).
- CRUD completo, activar / desactivar.
- Predefinidos: 15 categorías, 14 formas, 20 usos (con sinónimos).

### 5.5 Unidades de medida
- CRUD: Unidad (factor 1), Sello x 10 (factor 10), Caja x 100 (factor 100), etc.
- No permite referenciarse a sí misma ni eliminar la base.
- Bloquea eliminar si está en uso.

### 5.6 Temperaturas
- Pantalla principal con las zonas y su último registro.
- Registrar lectura con validación de turno AM/PM.
- Historial con filtros (zona, rango, fuera de rango).
- Gráfico de evolución (Chart.js local).
- Reporte PDF con logo.
- Plantilla mensual en PDF (una hoja A4).
- Alarma global con sonido + notificación + pantalla roja.

### 5.6b Equipos y calibraciones ✅
- Menú Día a día → 📏 Equipos (`app/equipos.py`, ruta `/equipos`). Ver: todos. Crear, editar, dar de baja y registrar calibración: admin y DT.
- Cada equipo puede asignarse a una zona de temperatura; al registrar una lectura en esa zona se guarda `temperatura_registros.equipo_id` (trazabilidad).
- Registrar calibración: fecha (no futura), próxima (si se deja, se sugiere con la frecuencia del equipo: 12 meses por defecto), empresa, n.º de certificado, resultado y el certificado en PDF o foto (`guardar_documento` valida que el PDF sea real). El equipo queda con la calibración más reciente.
- Estado: al día, vence pronto (≤ 30 días), vencida, no conforme (la última calibración salió no conforme) o sin calibración. Aviso en la lista si hay zonas de temperatura sin equipo.
- Panel de alertas del Inicio: 🔴 calibración vencida o no conforme · 🟡 por vencer o sin calibración.

### 5.7 Recepción técnica
- Formulario con cabecera y líneas dinámicas.
- Autocompletado de productos.
- Muestra registro INVIMA debajo del producto.
- Alta rápida de productos desde el "+" con modal.
- Validaciones HTML5 + validación de servidor con preservación de datos.
- Acta de Recepción Técnica en PDF con:
  - Encabezado con logo y datos del negocio.
  - Detalle con DCI, forma, presentación, INVIMA, lote, vencimiento, vida útil %.
  - Concepto técnico automático.
  - Firmas de recibido y aprobado.
- Estados: cuarentena → aprobada / rechazada.
- Al aprobar crea lotes disponibles + movimiento de kardex.

### 5.8 Inventario por lote
- Pantalla de resumen con KPIs (por vencer 30, 90 días, vencidos, cuarentena, bloqueados).
- Lista de lotes con filtros.
- Semáforo de vencimiento.
- Detalle de lote con acciones (bloquear, desbloquear, ajustar).
- Kardex por producto.
- Reporte de semáforo de vencimientos.

### 5.9 POS
- Apertura de caja con conteo por denominación (billetes + monedas). Sale de la **caja menor**; si no alcanza, exige marcar "Permitir sobregiro".
- **Cambio de precio al vender (Opción B):** cualquier usuario puede cambiarlo con la tecla "Precio", pero al cobrar se pide un **motivo obligatorio**, nunca puede superar el **precio máximo** del producto, y queda en `venta_lineas` (precio_original, motivo_precio) y en la bitácora (`venta_precio_modificado`).
- **Botón "i"** en cada tarjeta: franja amarilla (nombre, precio, a la mano, IVA, insignias), **Inventario** (lotes vendibles FEFO + aviso de lotes en cuarentena/bloqueados/vencidos), **Reabastecimiento** (últimas 4 compras aprobadas + stock mínimo) y **Finanzas** de 1 unidad (precio sin IVA, costo = promedio ponderado de lotes, margen sobre precio sin IVA, precio máximo). Ruta `/pos/api/producto/<id>`.
- **Editar** (solo admin y DT): ventana encima de la "i" con nombre, código de barras, maneja lotes, precio de venta, precio máximo, IVA, categorías, fórmula/control y foto. Ruta `/pos/api/producto/<id>/editar`; valida precio ≤ máximo, código de barras único, control especial con INVIMA; deja bitácora con los cambios; actualiza el carrito si el producto estaba en él.
- **Venta por presentación (unidad / sobre / caja):** el inventario SIEMPRE se cuenta en la unidad principal del producto ("Se vende por"), con el precio normal. Si el producto tiene otras presentaciones, la tarjeta dice "📦 También: Sobre x 10 · Caja x 100" y al tocarla sale la ventana **"¿Cómo lo vendes?"** (teclas 1, 2, 3…; las que no alcanzan el stock salen apagadas). Escanear el código de barras de la caja agrega la caja directamente. En el carrito cada presentación es una línea aparte ("📦 Sobre x 10") y todas comparten el stock del producto. El servidor (`api_cobrar`) toma precio y precio máximo **de la presentación**, descuenta `cantidad × factor` unidades por FEFO y guarda en `venta_lineas` presentacion, presentacion_id y factor. La anulación devuelve las unidades (están en `lotes_json`). El comprobante muestra la presentación. La "i" muestra una tabla con precio y margen de cada presentación. Código en `app/presentaciones.py` (id 0 = unidad principal).
- **Varias ventas a la vez:** pestañas "Venta 1", "Venta 2"… arriba del carrito y botón **+** (o tecla **F4**) para atender a otro cliente sin perder la venta a medias. Cada venta guarda su carrito, cliente y nota; todas quedan guardadas en el navegador (se conservan al recargar o si se va la luz). Al cobrar, la pestaña cobrada se cierra y se pasa a la siguiente. La ✕ descarta una venta (pregunta si tiene productos). Máximo 8. El carrito con el teclado numérico va a la **izquierda** y el botón ☰ (menú de la caja) a la derecha del buscador (pedido de Fernando, 2026-10-10). En el celular primero van los productos, el carrito queda abajo y un botón flotante "Carrito · total · Ver" baja hasta él. El botón **+ Venta libre** va al inicio de la fila de categorías.
- Mientras haya una ventana abierta, el teclado del POS (Enter = cobrar, números) no actúa.
- Carrito guardado en el navegador por caja (no se pierde al recargar; se borra al cobrar).
- Pantalla principal con layout de 2 columnas.
- Menú lateral derecho (drawer) con 8 opciones.
- Movimientos de caja (ingreso / salida) para efectivo, Nequi, Davivienda.
- **Regla del dinero:** *salida de efectivo* = solo **mover plata** (consignar, pasar a caja menor, cambiar billetes). Todo **pago** (domicilio, insumos, servicios) es un **gasto** (desde el POS o desde Contabilidad; es la misma tabla). *Retiro* de caja menor = sacar plata del fondo (consignar o lo que retira el dueño); si es plata que se lleva el dueño, se marca la casilla "Es plata que me llevo como dueño" (columna `retiro_dueno`) y sale aparte en Utilidades. La ventana de salida lo explica y tiene un botón directo a "Registrar gasto".
- Cierre de caja como modal con desglose completo.
- Modal de conteo reutilizable.

### 5.2b Unidades: inventario vs. venta ✅ (2026-10-10)
Problema que lo originó: el acetaminofén tenía 308 **tabletas**; al cambiar "Se vende por" a Sobre x 10 el programa leyó **308 sobres** y vender 2 sobres dejó 306 (debían quedar 288). Se investigó cómo lo hacen los POS de droguería y otros programas: inventario en la unidad más pequeña, presentaciones con factor, compras en otra unidad convertida, y la unidad no se cambia si ya hay movimientos.
- **Unidad de inventario** (antes "Se vende por"; columna `productos.unidad_venta_id`): la más pequeña que se vende (tableta, cápsula, frasco). Las existencias, el precio normal y el costo son de 1 unidad de inventario. **Queda bloqueada** cuando el producto ya tiene lotes, movimientos o ventas (el servidor también lo impide). Aviso si se escoge una unidad "grande" (Caja x 100).
- **"El POS lo vende por defecto como"** (`productos.venta_defecto_unidad_id`): tableta, sobre o caja. Al tocar la tarjeta en el POS se agrega esa presentación directo; la tarjeta muestra su precio ("Sobre x 10 · $1.800"), el stock en la unidad de inventario ("Stock: 288 Tableta") y "📦 Otras: …", que se puede tocar para escoger otra.
- **Asistente "Cambiar unidad de inventario"** (`/productos/<id>/cambiar-unidad`, `app/unidad_inventario.py`): (1) *solo corregir el nombre* (los números ya eran de la unidad nueva) o (2) *convertir* con factor N (1 unidad vieja = N nuevas): cantidades × N en lotes, kardex, conteos, recepciones, devoluciones y factor de las ventas; costos ÷ N; presentaciones × N; la unidad vieja queda como presentación con su precio y como venta por defecto. Bitácora `producto_unidad_cambiada`.
- **Recepciones por caja/sobre:** cada línea tiene **"viene en"** (presentaciones del producto); cantidad y costo se escriben como en la factura (3 cajas a $25.000) y se guardan en unidades (300 tabletas a $250); `recepcion_lineas.presentacion` y `factor` para mostrarlo. Escanear el código de barras de la caja deja la línea en "Caja". El detalle muestra "3 Caja x 100 = 300 Tableta".
- **Importador:** columnas nuevas **Unidad de inventario**, **Costo/Precio de 1 unidad**, **Presentación 2 / 3** (nombre, cuántas trae, precio) y **El POS lo vende como**. Unidades que no existen se crean ("Blíster x 12" → cantidad 12). Los números aceptan punto de miles (1.800). La plantilla y la ayuda salen de la misma lista de columnas.
- Conteo físico y kardex dicen en qué unidad se cuenta ("se cuenta en Tableta").
- **Trabajar "por sobre", como en el POS de Fernando, pero sin decimales** (2026-10-10, tarde): en su POS anterior la unidad de venta era el sobre ($1.600 x Sobre x 10) y 5 pastas había que venderlas como 0,5. Aquí por dentro se cuentan pastas, pero:
  - Las **existencias se muestran como se vende**: "29 Sobre x 10 + 5 Tableta" (POS: tarjeta, "i" y "¿Cómo lo vendes?"; lista de productos, que además muestra el precio de lo que se vende normalmente; kardex). Función `presentaciones.texto_existencias` (y su copia en `pos_carrito.js`).
  - **"Se vende suelto"** (`productos.vende_suelto`, migración 28): si se desmarca, el POS no ofrece la pasta suelta, el servidor no la deja vender, debe haber al menos una presentación, "Se vende normalmente por" se escoge solo y el **precio de la pasta se calcula** (precio del sobre ÷ cuántas trae) para costos y márgenes. Un formulario sin la casilla (campo oculto `vende_suelto_en_form`) deja "sí".
  - **Recepciones: "Otra caja…"** en "viene en", para cajas que no están en la ficha (hoy x 300, mañana x 100): se escribe cuántas trae y se guarda como "Caja x 300".
  - Importador: columna **"¿Se vende suelto? (SI/NO)"** (vacío = SI); con NO el precio de 1 unidad puede ir vacío.
- **La ficha empieza por la UNIDAD DE VENTA** (2026-10-10, 13:17, pedido de Fernando: "primero poner precio a la unidad de venta y después preguntar si está suelto"). Sección "Venta y precios" de `productos/form.html`:
  1. **Unidad de venta** (Sello x 10, Frasco, Unidad) + **precio de esa unidad** ($4.000) + **¿cuántas unidades trae?** (se llena sola con la unidad de medida; se puede corregir: "Sello" x 7) + costo de la unidad de venta + precio máximo.
  2. **¿Se vende suelto?** (solo aparece si trae más de 1): el precio de 1 unidad se calcula ($4.000 ÷ 10 = $400) y se puede cambiar a mano.
  3. Un recuadro explica con su ejemplo: "si recibes una caja de 300 unidades, entran 30 Sello x 10…".
  4. "El inventario se cuenta en: **Unidad** (cambiar)" queda plegado (avanzado); por defecto es "Unidad". Sigue bloqueado si hay historia.
  5. "Otras presentaciones (opcional)": solo para vender de otra forma con otro precio (la caja completa). La de venta no se repite ahí.
  - Por dentro no cambió el modelo: `productos._traducir_venta()` convierte lo escrito en unidad mínima + presentación de venta (factor, precio) + `venta_defecto_unidad_id` + precios/costo de 1 unidad. `_venta_de()` hace lo contrario para mostrar la ficha. Si el formulario no trae `venta_unidad_id` (formularios viejos/pruebas) se usa el camino anterior. Los números aceptan "4.000".
  - **Recepción → producto nuevo rápido** pregunta lo mismo (unidad de venta, precio, cuántas trae, ¿suelto?) y devuelve las presentaciones para el "viene en" de la línea.
  - **Conteo físico en paquetes:** si se vende por Sello x 10, cada lote tiene dos casillas, **sellos + sueltas** (27 y 4 → se guarda 274). "Sistema" y la diferencia se muestran como "27 Sello x 10 + 4 Unidad". La API de búsqueda del conteo manda `paquete` ({nombre, factor}).
  - **Importador con el mismo orden que la ficha:** Unidad de venta, ¿Cuántas unidades trae?, Precio de venta, Costo de la unidad de venta, Precio máximo, ¿Se vende suelto?, Precio de 1 unidad suelta (opcional), Otra presentación 1 y 2. Las columnas anteriores (Unidad de inventario, Precio de 1 unidad, Presentación 2/3, Se vende normalmente por) se siguen entendiendo (`COLUMNAS_ANTIGUAS`), pero ya no salen en la plantilla.
  - **POS:** escanear el código de barras del PRODUCTO agrega lo que se vende normalmente (el sello), igual que tocar la tarjeta; el código de una caja agrega la caja.
- **Ajustes según capturas de Fernando** (2026-10-10, tarde):
  - Ficha: `Precio de venta $ [ ] por [UdM ▾] [+]` y `Costo $ [ ] por <la misma UdM>` en una línea; "¿Cuántas trae?" solo se pregunta si el nombre de la unidad no lo dice.
  - Recepción: columna **UdM** con cualquier unidad de medida (valor `u<id>`; `recepciones._presentacion_por_unidad`: usa el factor de la ficha si la tiene, si no cantidad de la unidad ÷ la del inventario) y "+ Crear unidad…" en la misma línea (`/recepciones/api/crear-unidad`, también para auxiliares). El costo de la línea es el de compra por esa UdM.
  - Conteo en lista: sin buscar solo salen productos con existencias; buscando aparece cualquiera (en 0 con "⚠ Está en 0" y una línea lista). Un solo botón **"+ Agregar"** (junto al buscador) abre una ventana: buscar el producto (también los que están en 0) o "No está: crear producto", y luego lote, vencimiento (si maneja), cantidad (en sellos + sueltas si se vende por paquete) y costo si el producto no tiene. (Antes había un "+ Agregar lote" por producto: ocupaba mucho espacio.) Si el lote ya existió (agotado) se reutiliza. Si lo buscado no existe: **"+ Crear producto"** (ventana con precio por unidad de venta, costo, laboratorio, INVIMA, código de barras si se escaneó) que usa `/recepciones/api/crear-producto`. Se quitó la ventana "Producto encontrado".
- **Importar el Excel del programa anterior tal cual** (`importador._es_formato_externo` / `_traducir_externo`): se reconoce por las columnas "Unidad de medida" y "Precio de venta" (sin nuestra "Unidad de venta") y se traduce a nuestra plantilla: código nuevo P00001… (si la referencia interna es un código de barras, va como código de barras), "Unidades" → Unidad, precio y costo por la unidad de medida (SELLO X 10), "Seguimiento: Por lotes" → maneja vencimiento (si no viene esa columna: según si el producto aparece en el archivo de lotes), IVA "0% IVA Exc" → excluido (sin columna: excluido), categoría "All" se ignora, descripción sin HTML. Un producto ya existe si tiene el mismo código o el mismo código de barras (importar dos veces no repite). La previsualización muestra primero las filas con error. Probado con el archivo real de Fernando: 1.336 filas, 1.335 listas, 1 sin precio (MISCELANEA).
- **Un solo importador: productos + fotos + inventario inicial** (`app/carga_inicial.py`): en la misma pantalla se sube el archivo de productos y, opcional, el de lotes (Producto, Número de serie/lote, Fecha de caducidad, Cantidad a la mano; las filas de título de grupo se saltan). Al confirmar: se crean los productos, se les pone la foto (columna "Imagen…" en base64, se detecta el formato y se reduce a 600 px; no reemplaza fotos existentes) y se carga el inventario: cada lote con cantidad > 0 en unidades (22,5 SELLO X 10 = 225, se usa el factor de la unidad de venta), y lo que el producto tenga en "Cantidad a la mano" que no esté en lotes entra "sin lote" (sin archivo de lotes, solo para productos que no manejan lote). Negativos/0 no se cargan y se listan. Lote "disponible" con el costo de la ficha y kardex "ajuste" referencia "Carga inicial". Un lote que ya existe no se repite. Límite de subida 300 MB.
- **Recepción: "✎ Completar datos"** debajo del producto de cada línea: ventana con registro INVIMA, vence registro, laboratorio, concentración, principio activo y forma farmacéutica, que se guardan en la **ficha del producto** (`recepciones.api_datos_tecnicos`, GET/POST `/recepciones/api/producto/<id>/tecnicos`, bitácora `producto_datos_tecnicos`). Cadena de frío/control especial exigen INVIMA. La línea se actualiza al guardar (el aviso "SIN registro INVIMA" desaparece).
- Pruebas: `tests/test_unidades.py` (incluye el caso de Fernando: caja x 300 → 30 sellos → vende 2 sellos y 3 sueltas → "27 Sello x 10 + 7 Unidad").

### 5.9c Venta libre y otros ingresos ✅
- **Venta libre** (botón "Venta libre" debajo del carrito o menú del POS): cobrar algo que **no está en el inventario** (inyectología, toma de presión…). Ventana propia con: qué se vende, precio de cada uno (con IVA), cantidad, IVA (sin IVA / 19 % / 5 %) y **costo opcional** (para que Utilidades calcule bien la ganancia). Entra al carrito como una línea más (se puede cambiar cantidad, % y precio sin pedir motivo, porque no hay precio guardado con qué comparar) y **no descuenta inventario**. Se guarda en `venta_lineas` con `es_libre = 1`, `producto_id` vacío, código `LIBRE` y `costo_libre`; queda en la bitácora (`venta_libre`). Sale en el comprobante. **No se puede devolver** (si se cobró mal, se anula la venta). No aparece en Top productos ni en Sugerido.
- **Otros ingresos**: plata que entra y **no es venta** (comisión de recargas, arriendo de un espacio, reciclaje, reintegros, intereses). Tabla `otros_ingresos` (espejo de `gastos`), categorías en Administración → Catálogos → "Categorías de otros ingresos".
  - **Desde el POS** (menú → "Otro ingreso"): si es en **efectivo entra a la caja abierta** (caja_movimientos "ingreso") y el cierre cuadra; por Nequi/Davivienda/transferencia solo queda registrado. La ventana "Ingreso de efectivo" aclara la diferencia: *ingreso de efectivo* = meter plata (base, cambio); *otro ingreso* = plata ganada; tiene un botón directo.
  - **Desde Contabilidad** (`/contabilidad/ingresos`, admin y DT): lista con filtros, nuevo, editar y anular. Para la plata que no pasó por la caja (ej: arriendo que llegó al banco). A un ingreso que entró por la caja del POS **no se le cambia monto, forma de pago ni fecha** (para que la caja siga cuadrando): si quedó mal, se anula y se registra otra vez. Contabilidad muestra el total del mes.
- **En reportes:** R1 Ventas tiene el filtro **"Mostrar: Todo / Solo productos del inventario / Solo venta libre"** (ahora cuenta por líneas de venta), muestra cuánto fue de productos y cuánto de venta libre, y una sección aparte **"Otros ingresos (no son ventas)"** por categoría. Utilidades: la venta libre está dentro de las ventas con su costo; los otros ingresos se **suman** antes de la utilidad neta, una línea por categoría (se despliega el detalle).
- Código: `app/pos.py` (`_guardar_linea_libre`, `api_otro_ingreso`), `app/otros_ingresos.py`, `static/js/pos_carrito.js` (`pedirVentaLibre`, `pedirOtroIngreso`). `window.pedirDatos` (ui.js) ahora también pide números y listas.

### 5.9d Cartera (cuentas por cobrar, ventas a crédito) ✅
- **Clientes** (`clientes`): nombre, cédula/NIT (no se repite), teléfono, dirección, **cupo** (vacío = sin límite), observaciones, activo. Los crea y edita el administrador o el DT en **Dinero → Cartera → + Nuevo cliente**.
- **Vender a crédito en el POS:** en la ventana de pago, forma **"Crédito"** → buscador de clientes (nombre, cédula o teléfono) con lo que debe y su cupo disponible; muestra cuánto quedará debiendo. El servidor exige cliente activo y **no deja pasar el cupo**. No entra plata a la caja (el cierre lo muestra aparte, "Ventas a crédito"). `ventas.forma_pago = 'credito'` y `ventas.cliente_id`. El comprobante dice **VENTA A CRÉDITO**, el saldo total del cliente y una línea para su **firma**. Cualquier usuario puede vender a crédito a un cliente ya registrado.
- **Abonos** (`cartera_abonos`, AB-0001): desde el POS (menú → "Abono de cartera", lista de quienes deben) o desde el estado de cuenta. No se puede abonar más de lo que debe. Efectivo, Nequi y Davivienda entran a la **caja abierta** (caja_movimientos "ingreso"); el efectivo exige caja abierta; transferencia/tarjeta solo quedan registradas. **Recibo de abono** en tirilla 80 mm (con el saldo pendiente). Anular un abono (admin/DT, con motivo) devuelve la deuda y, si su caja sigue abierta, saca la plata (salida).
- **Saldo** = ventas a crédito (no anuladas) − devoluciones descontadas de la deuda − abonos. Los abonos pagan primero las ventas más viejas (FIFO), así se sabe qué ventas siguen pendientes y cuántos días llevan.
- **Pantalla Cartera** (`/cartera`, admin y DT): total por cobrar, vencida (> 30 días), antigüedad 0–30 / 31–60 / 61–90 / +90, lista de clientes con lo que deben, cupo, disponible y días. **Estado de cuenta** por cliente: ventas pendientes, movimientos con saldo acumulado (como un extracto), registrar abono, imprimir.
- **Devolución de una venta a crédito:** no se devuelve plata, se **descuenta de la deuda** (forma de reembolso "credito"; no necesita caja). Anular una venta a crédito borra esa deuda.
- **Alerta en Inicio** (admin y DT): "Clientes con deuda de más de 30 días". R1 Ventas muestra "Crédito (cartera)" en las formas de pago.
- Código: `app/cartera.py`, plantillas `cartera/`, `static/css/tirilla.css` (estilo compartido del comprobante y el recibo). Demo: 3 clientes de prueba.
- **Ancho de la tirilla: 58 u 80 mm** (Configuración del negocio → "Impresora de tirillas"; por defecto 80). Cada tirilla (comprobante y recibo) tiene botones **58 / 80** para imprimir una vez en el otro ancho (`?papel=58`). `static/js/tirilla.js` mide el largo de la tirilla y le da a la impresora el tamaño exacto del papel (ancho × largo); el contenido va centrado (72 mm útiles en 80, 48 mm en 58).

### 5.9b Devoluciones ✅
- `app/devoluciones.py`, ruta `/devoluciones` (solo admin y DT). Entradas: botón **↩️ Devolución** en la lista de ventas del POS, Inventario → Devoluciones y **🚚 Devolver al proveedor** en el detalle de un lote.
- **De cliente (DC-0001):** se busca la venta (V-0012 o solo 12); por producto se elige cuánto devuelve (máximo lo comprado menos lo ya devuelto) y si **vuelve al inventario** (al mismo lote del que salió, empezando por el último; un lote "agotado" vuelve a disponible) o se da de **baja**. El valor es proporcional a lo que pagó (con descuento). La plata sale de la **caja abierta** como "salida" (efectivo, Nequi, Davivienda o tarjeta), así el cierre cuadra. Motivo obligatorio. Una venta con devolución ya no se puede anular.
- **A proveedor (DP-0001):** por defecto muestra lotes vencidos y que vencen en 90 días (o se busca). Motivos: vencido, próximo a vencer, averiado, error en el pedido, retiro del mercado, otro. Si el proveedor reconoce el valor (nota crédito o cambio) el kardex registra 'devolucion'; si no, 'baja' (pérdida en Utilidades). Acta PDF para firmar (también para las de cliente).
- **En reportes:** Utilidades resta las devoluciones de clientes de las ventas (y su costo si reingresó; con baja el costo se queda como pérdida), márgenes sobre ventas netas. R1 muestra cuántas devoluciones hubo. R4 resta lo devuelto al proveedor con nota crédito de lo comprado.

### 5.10 Importador (parcial)
- Descarga de plantilla .xlsx / .csv.
- Vista previa con análisis de errores.
- Detección de duplicados por código.
- Creación automática de catálogos.
- **Pendiente:** probar con Excel real de 1500+ productos.

### 5.11 Configuración
- Datos del negocio, Director Técnico, pie legal.
- Subida de logo (cualquier formato: JPG, PNG, WEBP, GIF, TIFF, BMP, HEIC).
- Conversión automática de TIFF/BMP/HEIC a PNG.
- Redimensionado automático.

### 5.12 Reportes
- Índice con tarjetas.
- Reporte de temperaturas con gráfico y PDF.
- Plantilla mensual de temperaturas.
- **R2 Utilidades / Estado de resultados ✅** (`app/utilidades.py`, ruta `/reportes/utilidades`, solo admin y DT; también hay un botón en Contabilidad):
  - Ventas sin IVA (ventas completadas, con descuento) − **costo real** de cada lote vendido (`lotes_json`) = utilidad bruta y margen.
  - − Gastos por categoría (al tocar una categoría se ven sus gastos; "Sueldo del dueño" es una categoría más) − pérdidas de inventario en dos líneas: bajas/vencidos/averías y faltantes del conteo (ajustes negativos al costo del lote; los sobrantes no suman porque incluyen el inventario inicial) = **utilidad neta**.
  - Informativo: retiros del dueño (retiros de caja menor marcados "Es plata que me llevo como dueño") y "Queda en el negocio".
  - Período: mes (selector de 12 meses) o rango libre. Mes en curso → se compara con los mismos días del mes anterior; mes cerrado → mes anterior completo; rango → rango anterior de igual duración. Cambio en % en verde/rojo según si es bueno o malo.
  - Aviso si se vendieron unidades de lotes con costo $0. PDF para el contador. En el celular se oculta la columna "Anterior".
- **R6 Sugerido de compra ✅** (`app/sugerido.py`, ruta `/reportes/sugerido`, admin y DT): por producto, stock vendible, venta diaria (unidades vendidas en 30 días ÷ 30, cajas cuentan cantidad × factor), días que alcanza y sugerido = max(venta diaria × cobertura, stock mínimo) − stock. Sin ventas → solo stock mínimo. Proveedor y costo de la última recepción aprobada. Cobertura 7/15/30/45 días. Pestañas: **Pedido** por proveedor (cantidades editables, total estimado, botón **WhatsApp** con el pedido escrito —wa.me con el celular del proveedor si es un celular colombiano válido— e **Imprimir** solo ese proveedor), **Se agota en < 7 días**, **Bajo stock mínimo**, **Sin rotación** 60/90 días con el valor quieto al costo. El pedido no se guarda en la base.
- **Molde común** (`reportes/_base.html`): menú de reportes a la izquierda (en celular, fila deslizable), reporte a la derecha; selector de período compartido (`reportes/_periodo.html`: mes o rango, con botón Imprimir); números con `reportes/_macros.html`. Cálculos en `app/informes.py`.
- **R1 Ventas ✅** `/reportes/ventas`: con IVA, sin IVA, número, ticket promedio con cambio vs período anterior; anuladas aparte; gráfico de barras por día (todos los días, aunque estén en 0); por forma de pago, por vendedor, por hora del día y día por día.
- **R3 Top productos ✅** `/reportes/top`: por dinero, unidades (cantidad × factor) o utilidad (costo real del lote); top 5/10/20; % de las ventas.
- **R4 Ventas vs compras ✅** `/reportes/ventas-vs-compras`: 12 meses, vendido sin IVA vs comprado (recepciones aprobadas, líneas aceptadas, al costo); gráfico y tabla.
- **R5 Gastos ✅** `/reportes/gastos`: por categoría con período anterior, por forma de pago y detalle.
- **R7 Recepciones ✅** `/reportes/recepciones` (todos): por proveedor (recepciones, aprobadas, rechazadas, en cuarentena, productos rechazados y %, valor aprobado) y lista de productos rechazados con motivo.
- **R8 Vencimientos ✅** `/reportes/vencimientos` (todos) + PDF con firma del DT; usa `inventario.agrupar_vencimientos()`, la misma agrupación de Inventario → Vencimientos.
- Arreglado: `temperaturas.html` cargaba Chart.js dos veces.
- **📥 Excel ✅** en todos los reportes (botón arriba a la derecha): `static/js/excel.js` lee las tablas que se ven y `/reportes/excel` arma un .xlsx con una hoja por tabla, convirtiendo "$1.234" y "45,0 %" en números (códigos de barras y códigos con 0 adelante quedan como texto).
- **Resumen en el Inicio ✅** (solo admin y DT): ventas de la semana (desde el lunes), del mes y utilidad neta del mes con su margen; cada tarjeta lleva a su reporte.

### 5.13 Bitácora
- Registro inmutable de todas las acciones.
- Filtros y paginación.

### 5.14 Respaldos
- Botón manual con verificación de integridad.
- Automático cada 24 horas al arrancar.
- Retención configurable (30 por defecto).
- Carpeta adicional opcional (USB / nube).

### 5.15 Toma de inventario (conteo físico)
- Inventario → "📋 Toma de inventario". Ruta `/inventario/conteos/`.
- Crear conteo (admin/DT): toda la droguería o una categoría. Solo uno abierto a la vez. Consecutivo CNT-####.
- Contar (cualquier usuario), **sin conteo ciego**: **lista en orden alfabético**, una fila por lote (producto, lote, vence, sistema, casilla "Contado", diferencia). Enter guarda y pasa a la siguiente. Buscador (nombre/código/lector de barras) y filtros todos / pendientes / contados / con diferencia, fijos arriba al bajar. En el celular cada lote ocupa 3 líneas.
- Botón general **"Producto encontrado"**: para mercancía que está en la estantería y no en el sistema. Se busca el producto (o se escanea) y se ingresa lote, vence, costo (sugerido) y cantidad. Así se carga el **inventario inicial** después de importar productos. Si el lote ya existía, se cuenta sobre el existente. Los productos sin lotes aparecen en la lista con un botón "Ingresar".
- **Se puede vender mientras se cuenta**: al guardar se anota lo que decía el sistema en ese momento; al aplicar se SUMA la diferencia a lo que haya (no se reemplaza), así no se pierden las ventas.
- Revisar: faltantes, sobrantes y encontrados (en unidades y a costo) + lista de lotes con existencias sin contar (esos NO se tocan al aplicar).
- Aplicar (admin/DT): corrige todo de una vez (movimientos `ajuste` en kardex con referencia "Conteo CNT-####"), bitácora, y **Acta PDF** con firmas. Anular: sin cambios en lotes.

## 5.16 Temas y diseño visual
- **Volver atrás:** la rama de GitHub `antes-del-rediseno` guarda el programa como estaba antes; y dentro del programa el tema **Clásico** lo muestra igual que antes.
- Cada usuario escoge su tema (menú → Mi cuenta → **Apariencia (temas)**; en computador también tocando su nombre abajo en el menú): **Verde salud** (por defecto), **Azul** o **Clásico**. Se guarda en `usuarios.tema`.
- `static/css/temas.css`: colores de cada tema como variables CSS (`--acento`, `--menu-fondo`, `--fondo`, `--texto`…) y la letra IBM Plex Sans (archivos locales en `static/fonts/`, licencia OFL). `app.css` y `pos_nuevo.css` usan esas variables.
- `static/css/moderno.css`: el diseño nuevo, todo bajo la clase `.moderno` que base.html pone en `<html>` cuando el tema no es Clásico (botones, tablas, tarjetas, formularios, menú, barra superior).
- Íconos de línea: `templates/_iconos.html`, macro `ico('carrito', '🛒')` (en Clásico se ve el emoji).
- Barra superior: ☰, ruta "Inicio › página", estado de la caja (abierta/cerrada) y Salir.
- Inicio: sin "Accesos rápidos" (pedido de Fernando).
- **Piezas comunes (`static/js/ui.js`, rediseño parte 4):**
  - Mensajes tipo **toast** (arriba a la derecha; los buenos se van solos en 5 s, los de error se quedan hasta tocar ×). Desde JS: `window.avisar('texto', 'ok'|'error')`. En Clásico siguen como franjas.
  - **Ventana para pedir datos** `await window.pedirDatos({...})` en vez de `prompt()`: Cliente, Nota y motivo de cambio de precio del POS, nuevo laboratorio en Recepciones. Ya no queda ningún `prompt()` ni `alert()` (hay una prueba que lo vigila).
  - **Fechas dd/mm/aaaa** con calendario propio en español (lunes primero, « » cambia de año) en todo `<input type="date">`; al servidor le sigue llegando aaaa-mm-dd. Las "/" se ponen solas al escribir; año de 2 cifras → 20xx; revisa fechas imposibles (31/02) y mínimos/máximos.
- **Comprobante en tirilla de 80 mm** (`pos/comprobante.html`): logo, datos del negocio, fecha dd/mm/aaaa, pesos con punto de miles, nota de la venta, "Documento interno · no es factura". Filtros de plantilla nuevos: `pesos` y `fecha_hora`.
- Emojis decorativos de botones y títulos: envueltos en `<span class="ico-emoji">` → se ocultan en el diseño nuevo y se ven en Clásico.
- En el celular la barra superior se compacta (solo el nombre de la página, la caja como un punto de color y Salir con ícono).

## 6. Sistema de imágenes

### Formatos aceptados
- **Directos:** JPG, JPEG, PNG, WEBP, GIF.
- **Con conversión a PNG:** TIFF, TIF, BMP, HEIC, HEIF.

### Límites
- Logo: 2 MB, redimensionado a 800×800.
- Foto de producto: 5 MB, redimensionado a 1200×1200.
- Adjunto de recepción: 5 MB.
- Carpeta: `static/uploads/<categoria>/`.

## 7. Plan por fases

### Fase 0: base ✅
- Instalar Python y Flask, estructura, base de datos.
- Login con roles, bitácora inmutable, respaldos.

### Fase 1: calidad e inventario ✅
- **1.1** Productos, proveedores, catálogos, unidades de medida.
- **1.2** Temperaturas con alarma + historial + reportes PDF.
- **1.3** Recepción técnica con Acta PDF.
- **1.4** Inventario por lote, kardex, semáforo.
- **1.5a** Importador de productos (parcial).
- **1.5b** Inventario inicial ✅ (con la Toma de inventario; falta hacerlo con datos reales).

### Fase 2: ventas y contabilidad 🔄
- **2.1** POS interno ✅ (caja, carrito, cobro, anulación, cambio de precio, ventana "i", **venta por presentación**).
- **2.2** Gastos discriminados ✅ (módulo Contabilidad + caja menor).
- **2.3 / 2.4** Utilidades y estado de resultados ✅ → hechos como **R2** en Reportes.
- **2.5** IVA con prorrateo ⏸ solo si el contador lo pide.
- **2.6** Flujo de caja ⏸ lo cubren R1 Ventas (por día y forma de pago) + el cierre de caja.

### Fase R: módulo Reportes ✅
Idea (tomada de DATA FARMAC): una pantalla con la lista de reportes a un lado y el
reporte elegido al otro, con **selector de período** (día, semana, mes, año o
fechas), gráfico (Chart.js local), tabla y descarga en PDF/Excel.
**Reglas de todos:** las ventas anuladas no cuentan; los montos van con y sin IVA.

Se juntaron los reportes que repetían el mismo cálculo con otro período
(antes eran 15, quedan 8 + Temperaturas, que ya existe):

| # | Reporte | Qué muestra | Reemplaza a | Quién lo ve |
|---|---|---|---|---|
| R1 ✅ | **Ventas** | Ventas por día, semana, mes o año; comparación con el período anterior; desglose por forma de pago y por vendedor | Ventas de la semana, Ventas anuales, Ingresos por día, Ingresos por usuario | Admin y DT |
| R2 ✅ | **Utilidades y estado de resultados** | Ventas − costo de lo vendido (costo real del lote) − gastos, por día o por período; estado de resultados simplificado | Ganancia de la semana, Utilidades (Fase 2.3 y 2.4) | Admin y DT |
| R3 ✅ | **Top productos** | Los más vendidos por unidades y por dinero (top 5, 10 o 20) | Top 5 productos | Admin y DT |
| R4 ✅ | **Ventas vs compras** | Comparativo mensual: lo vendido vs lo comprado (recepciones aprobadas) | — | Admin y DT |
| R5 ✅ | **Gastos** | Gastos del período por categoría | Gastos administrativos | Admin y DT |
| R6 ✅ | **Sugerido de compra** | Qué pedir y cuánto, por proveedor: venta diaria promedio (30 días), días que alcanza el stock, cantidad para cubrir N días. Listas: **bajo stock mínimo**, **se agota en < 7 días**, **sin rotación** (60/90 días). Pedido para imprimir o enviar por WhatsApp | — | Admin y DT |
| R7 ✅ | **Recepciones** | Recepciones por proveedor y período, rechazos y motivos | — | Todos |
| R8 ✅ | **Vencimientos** | Semáforo en PDF para inspección | — | Todos |
| — | Temperaturas | Ya existe (gráfico, PDF y plantilla mensual) | — | Todos |

Notas:
- El **Resumen** de DATA FARMAC no es un reporte aparte: sus números (ventas de hoy,
  semana y mes, utilidad del mes, alertas) van en la pantalla de **Inicio**.
- **Utilidades** vive en Reportes; la tarjeta de Contabilidad lleva a ese reporte (un solo lugar).
- R6: solo cuenta stock vendible (no cuarentena ni vencidos). Las primeras semanas tras
  el inventario inicial no hay historial de ventas; mientras tanto se guía por el stock mínimo.
- **Venta libre** y **otros ingresos** ✅ quedaron como filtro y sección dentro de R1 Ventas
  (no como reportes aparte). Ver 5.9c.
- _Descartados por decisión de Fernando: Top 5 servicios y Medicamentos vs Servicios._
- Visto en DATA FARMAC y anotado como idea: **Cotización** y **Deudas** (fiados).

### Fase 3: alertas y precios ⏳
- **3.1** Devoluciones ✅ (de cliente y a proveedor, con acta PDF).
- **3.2** Precios máximos de venta ✅ (tope al vender + alerta en Inicio).
- **3.3** Alertas INVIMA ✅ (panel de alertas del Inicio).
- **3.4** Control especial (FNE) — flujo completo.

### Fase 4: gestión documental y cumplimiento 🔄
- **4.1 Documentos** ✅ (2026-10-10) — `app/documentos.py`, menú **Calidad → Documentos**:
  listado maestro (estados por hacer / borrador / vigente / obsoleto), botón "Cargar el
  listado sugerido" (28 documentos: SGC-DOC, PR-01…PR-18, FT), subir versión (PDF, Word,
  Excel o foto) como borrador o vigente, aprobar borrador, control de cambios (las versiones
  viejas quedan como "reemplazada", nada se borra), "Revisado: sigue igual" (deja constancia
  y corre la próxima revisión), próxima revisión = aprobación + frecuencia (12 meses),
  aviso amarillo en Inicio cuando la revisión vence o faltan ≤ 30 días, PDF del listado
  maestro con firma del DT. Ver y abrir: todos; modificar: administrador y DT.
- **4.2 Saneamiento** ✅ (2026-10-10) — `app/saneamiento.py`, menú **Calidad → Saneamiento** (3 pestañas):
  - *Limpieza*: tareas con frecuencia diaria/semanal/quincenal/mensual (vienen Pisos diaria,
    Estanterías semanal, Nevera mensual); "Marcar hecha hoy" con un toque (todos los usuarios;
    auxiliar hasta 7 días atrás); "Deshacer" (quien la marcó el mismo día, o el jefe; queda en
    bitácora); planilla del mes con cumplimiento (períodos hechos / transcurridos desde que existe
    la tarea) y PDF; aviso en Inicio: diarias desde las 3 p. m., semanales/quincenales/mensuales
    cuando quedan 1/2/3 días del período.
  - *Control de plagas*: registro con empresa, certificado (archivo), próxima = +6 meses; aviso en
    Inicio si no hay ninguno, si vence en ≤ 30 días o si venció.
  - *Residuos* (Resolución 591 de 2024, que reemplazó la 1164 de 2002): registro por tipo y kg
    (farmacéuticos, cortopunzantes, biosanitarios, químicos = peligrosos; aprovechables, ordinarios),
    consolidado mensual + PDF, entregas al gestor con certificado, "Dar de baja lotes vencidos"
    (movimiento `baja` "Baja por vencimiento" + registro de residuo farmacéutico). Aviso en Inicio
    si hay peligrosos guardados > 90 días sin entregar. La alerta de lotes vencidos ahora apunta aquí.
- **4.3 Capacitaciones** ✅ (2026-10-11) — `app/capacitaciones.py`, menú **Calidad → Capacitaciones**:
  - *Personal*: nombre, documento, cargo, ingreso, "ocasional", usuario del programa (opcional);
    retirar (no se borra); columna de capacitaciones y horas del año e inducción hecha/pendiente.
  - *Plan del año*: "Cargar plan sugerido" (12 temas internos con contenido: recepción, almacenamiento,
    residuos Res. 591, dispensación, vencimientos, limpieza, farmacovigilancia, cadena de frío, quejas,
    normatividad, bioseguridad, uso del programa). Año futuro: el 15 de cada mes; año en curso ya
    avanzado: repartidos entre dentro de 7 días y el 15/12 (`fechas_del_plan`), para que no nazcan atrasados.
  - Cada capacitación: programar (interna / externa con entidad / inducción), "Registrar como realizada"
    (fecha, horas, asistentes con nota 0–5, acta firmada escaneada; se puede corregir), cancelar o
    reprogramar. Acta en PDF para firmar (con el personal activo ya escrito si aún no hay asistencia)
    y cronograma del año en PDF. Aviso en Inicio (jefe) por capacitaciones atrasadas.
- **4.4 Quejas (PQRS)** ✅ (2026-10-11) — `app/pqrs.py`, menú **Calidad → Quejas**: registrar (todos;
  tipo queja/reclamo/petición/sugerencia/felicitación, canal, usuario, descripción) → número PQ-0001 y
  fecha límite = 15 días hábiles (Ley 1755/2015) con `app/festivos.py` (festivos de Colombia: fijos,
  Ley Emiliani y los de Pascua); responder y cerrar (jefe: respuesta, acción de mejora, ¿satisfecho?),
  reabrir, PDF; indicadores del año (por tipo, sin responder, % a tiempo). Avisos en Inicio: vencida
  (rojo), ≤ 3 días hábiles (amarillo).
- **4.5 Farmacovigilancia** ✅ (2026-10-11) — `app/farmacovigilancia.py`, menú **Calidad →
  Farmacovigilancia**: registrar caso (todos): RAM, fallo terapéutico, error de medicación o problema
  de calidad; grave sí/no; paciente solo iniciales/edad/sexo; medicamento con sugerencias de los
  productos (enlaza `producto_id` y completa laboratorio y registro sanitario). Plazo de reporte:
  grave 72 h; no grave día 5 del mes siguiente; sin reportes en cero. Botón al formulario eReporting
  del INVIMA (primaryreporting.who-umc.org/CO), "Ya lo reporté" (fecha, medio, número), PDF con los
  datos mínimos (FOREAM), enlace para bloquear el lote si está en inventario. Avisos en Inicio:
  graves o vencidos (rojo), no graves a ≤ 5 días (amarillo).
- Plan de saneamiento, capacitaciones, calibraciones.
- Farmacovigilancia.
- **Modo Inspección** (paquete ZIP).

### Fase 5: facturación electrónica ⏳
- Escoger proveedor y conectar el adaptador.

### Fase 6: IA y automatización ⏳
- Sugerencia de categorías y principio activo al escribir nombre.
- ~~Búsqueda semántica~~ → la cubre el buscador por síntoma (usos) del POS.
- Imágenes automáticas por código de barras.
- Resumen de noticias regulatorias.

### Fase 7: empaquetado y distribución ✅ (2026-10-11, versión 1.0.0)
- **Carpeta de DATOS aparte** (`config.py`): instalado (`sys.frozen`), datos en `%LOCALAPPDATA%\Fervifarma`
  (db/, uploads/, respaldos/, logs/, ventana/); el programa en `%LOCALAPPDATA%\Programs\Fervifarma`.
  Programando, todo sigue en la carpeta del proyecto. Variable `FERVIFARMA_DATOS` para cambiarla.
  Las subidas usan `utils_imagenes.carpeta_uploads()` / `ruta_de()` y se sirven en `/static/uploads/...`
  desde `UPLOADS_DIR` (regla más específica que la de static). Instalado: 127.0.0.1:8765.
- **Lanzador** `escritorio.py` (el .exe): si `/salud` contesta, solo abre otra ventana; si no, prende
  Waitress en un hilo + reloj de respaldos y abre Edge/Chrome en modo aplicación (`--app`, maximizado,
  perfil propio en datos/ventana); al cerrar la ventana se apaga. Sin Edge/Chrome: navegador predeterminado.
  `--solo-servidor` prende sin ventana. Errores en `logs/fervifarma.log`.
  (Se descartó pywebview: el comprobante usa ventanas nuevas, window.opener e impresión, que en modo
  aplicación del navegador funcionan igual que siempre.)
- **Respaldos**: reloj cada hora (`backup_utils.iniciar_reloj_de_respaldos`, lo arrancan run.py y escritorio.py):
  base de datos cada 24 h y ZIP semanal de uploads (fotos, certificados, actas, documentos; se guardan 4).
  Carpeta adicional (USB/Drive) escogida en Administración → Respaldos (config `respaldo_carpeta_extra`),
  botón para abrir la carpeta en el Explorador. Ya no se respalda dentro de `create_app`.
- **Versión** en `app/version.py` (se ve en el pie del menú).
- **PyInstaller** `instalador/fervifarma.spec` (sin consola, ícono `instalador/fervifarma.ico`, sin static/uploads).
- **Inno Setup** `instalador/fervifarma.iss`: por usuario sin admin, ícono escritorio/menú, tarea "Abrir al
  prender el computador" ({userstartup}), cierra el programa si está abierto al actualizar, no borra datos.
- **GitHub Actions** `.github/workflows/instalador.yml` (windows-latest): pruebas en Windows → PyInstaller →
  prueba de arranque del .exe (`--solo-servidor` + /salud) → Inno Setup → artefacto; con etiqueta `v*`
  al publicar una versión en GitHub (Releases → Draft a new release → etiqueta vX.Y.Z → Publish) agrega el .exe a esa
  publicación. Para sacar versión: subir `VERSION` en app/version.py, commit, y publicar la versión en GitHub.
  (Desde la sesión de Claude no se pueden crear etiquetas ni publicaciones: lo hace Fernando en la web.)

### Versiones publicadas
| Versión | Fecha | Qué trae |
|---|---|---|
| 1.0.0 | 2026-10-11 | Primera con instalador de Windows |
| 1.0.1 | 2026-10-11 | Menú lateral en el orden de Fernando (Calidad desplegable) |
| 1.1.0 | 2026-10-13 | Dos computadores (mostrador + portátil por Tailscale) y tirilla directa ESC/POS |
| 1.1.1 | 2026-10-13 | Importación con fotos ya no bloquea la base (error 500 en POS); nunca dos programas prendidos |
| 1.1.2 | 2026-10-17 | Cajón y tirilla directa abren de verdad (winspool.drv); instalable desde Chrome; la ventana abre con Chrome |
| 1.1.3 | 2026-10-18 | Tipo de orden del cajón (estándar / pulso largo / tiempo real DLE DC4); la alarma registra sin salir de la página; código de barras en el alta rápida de la recepción; búsqueda por palabras con LABORATORIO en todo el programa; total de cada línea en la recepción; producto creado en la recepción queda excluido de IVA; el buscador de la recepción ya no deja por fuera los que «contienen» lo escrito; laboratorios al día y «+» en «Completar datos»; cantidad, UdM y costo obligatorios; PAGO MIXTO en el POS |
| 1.1.4 | 2026-10-18 | Todo lo de 1.1.3 (su instalador no se armó) + fechas en líneas agregadas de la recepción (28 → 2028, calendario) + prueba de limpieza que fallaba los lunes |
| 1.1.5 | 2026-10-19 | POS como el programa anterior: cursor en el producto agregado (números = cantidad, Suprimir con Deshacer), búsqueda que no se borra con X, lector reconocido por velocidad, numerito en las tarjetas, búsqueda más rápida |
| 1.1.6 | 2026-10-19 | (Junta lo planeado para 1.1.6 y 1.1.7) Clic en el buscador del POS selecciona todo; ícono propio en la barra de tareas; varios principios activos con comas; catálogos en orden alfabético (tildes bien) y UdM por tamaño; laboratorio opcional («Laboratorio o marca»); sin repetidos + «Buscar repetidos»; IVA por línea en la recepción y «¿La droguería declara IVA?»; dashboard contable nuevo; Sesiones de caja (azul / rojo − / verde +) y sobrantes/faltantes automáticos en la contabilidad |
| 1.1.7 | 2026-10-20 | Recepción en una sola línea por producto; BANCOS (Nequi y Davivienda: saldo automático, traslados, plata del dueño, cuadre); CUENTAS POR PAGAR a proveedores (crédito/contado, pago desde caja menor, POS, Nequi o Davivienda; facturas viejas «por revisar»); acciones de GitHub en Node 24 |
| 1.1.8 | 2026-10-21 | RECEPCIÓN EN ESPERA (guardar a medias y seguir otro día); Acta de recepción con 20+ productos por hoja; foto del producto desde la recepción (Nuevo producto y Completar datos); fotos .jfif; en los campos de números el 0 desaparece al dar clic y el campo se pone azul; el conteo de efectivo no se borra hasta cerrar/abrir la caja (botón Limpiar); botón «Abrir cajón» en la pantalla Abrir caja |
| 1.1.9 | 2026-10-22 | Recepción ABIERTA que se guarda sola (como el conteo) hasta «Confirmar recepción»; «Continuar recibiendo»; foto arriba en «Nuevo producto» y «Completar datos»; el 0 vuelve al dar Enter |
| 1.1.10 | 2026-10-23 | Igual a 1.1.9 (su instalador no se armó en GitHub: faltaba pypdf para una prueba) |
| 1.1.11 | 2026-10-24 | Toma de inventario: si el producto no tiene costo (inventario inicial), se estima con el precio de venta − margen de Configuración (30 %). POS: ya no sale «Unexpected token '<'» al cobrar (clave de seguridad vieja se renueva sola; sesión cerrada o error interno → mensaje claro). Búsqueda con lo más parecido de primero (TAM → TAMPONES antes que aceTAMinofen) |
| 1.1.12 | 2026-10-25 | Botón «Eliminar» de la foto en la ficha funciona; agotados en Inicio con «✔ Entendido» (vuelve a salir si llega mercancía y se agota otra vez; el reporte no cambia); Pedido sugerido con el proveedor MÁS BARATO (último precio por unidad con IVA), otras opciones con fecha y cambio a mano; toma de inventario: barra azul que selecciona todo y el cursor vuelve a ella tras guardar; botón ✏️ con la ventana «Editar producto» del POS, ahora con «Cómo se vende» (unidad, suelta, presentaciones, por defecto) |

### Versión 1.1.12 — foto, «Entendido» en agotados, proveedor más barato, inventario con ✏️ (2026-10-25)
- **Foto en la ficha**: el botón «Eliminar» no hacía nada (el JS guardaba una referencia vieja a la vista previa y
  no existía el campo oculto). Ahora `productos/form.html` tiene `_imagen_accion` (hidden) y `ponerEnCuadro()`
  busca la vista previa por id cada vez; al Guardar, `productos.editar` borra el archivo y deja `imagen = NULL`.
- **Agotados en Inicio → «✔ Entendido»** (Fernando no quería «No volver a pedir»). Migración 41:
  `alertas_vistas (clave, producto_id, usuario_nombre, creado_en)`. `main.alerta_entendido` (POST
  /alertas/entendido) guarda la marca; `alertas.py` borra solas las marcas de productos que vuelven a tener stock,
  así que si se agota de nuevo vuelve a salir. El Sugerido de compra NO usa esta tabla (sigue igual).
- **Pedido sugerido con el proveedor más barato**. `sugerido.precios_por_proveedor(db)`: último costo por unidad
  de inventario con IVA (`COALESCE(costo_con_iva, costo_unitario)`) de cada proveedor en recepciones aprobadas o en
  cuarentena (sin líneas rechazadas). Elección: `productos.proveedor_preferido_id` (migración 41, «✋ escogido por
  usted») → el más barato («💲 el más barato») → el de la última compra. Debajo del producto: «Otros: proveedor $x
  (dd/mm)» y un selector (POST /reportes/sugerido/proveedor, vacío = automático; `static/js/sugerido.js` recarga).
- **Toma de inventario**: al dar clic en la barra se pone azul y selecciona todo (`conteo.js irAlBuscador`); al
  guardar una cantidad con Enter, si hay búsqueda y la siguiente casilla es de otro producto, el cursor vuelve a la
  barra listo para el siguiente código. Botón ✏️ por producto (solo administrador/DT) que abre la MISMA ventana
  «Editar producto» del POS.
- **Ventana «Editar producto»** sacada a `static/js/editar_producto.js` (`window.EditarProducto.abrir(id_o_datos,
  {alGuardar})`), usada por el POS (`pos_carrito.js`) y el conteo. Nueva sección «Cómo se vende»: la unidad del
  inventario (precio, máximo, «se vende suelta») y las presentaciones (unidad, trae, precio, máximo, código de
  barras, ✕ quitar, + agregar), con «Por defecto» = lo que vende el POS. Se envía con `formato=presentaciones`;
  `pos.api_producto_editar` usa `presentaciones.leer_del_formulario/validar/guardar` como la ficha completa (si no
  se vende suelta, el precio de la unidad = precio de la presentación por defecto ÷ lo que trae). El formato viejo
  (precio_venta + otros precios) sigue aceptándose. `api_producto_info` devuelve `vende_suelto` y `unidad_venta_id`.
- Pruebas: `tests/test_version_1112.py` y `tests/test_sugerido.py` (más barato y escogido a mano).

### Versión 1.1.11 — costo estimado en el conteo, cobro sin «Unexpected token», búsqueda por parecido (2026-10-24)
- Pedido de Fernando: en el inventario inicial ningún producto tiene compras registradas y el conteo pedía el
  costo de cada lote encontrado (sacar facturas y dividir). `conteos._costo_sugerido(producto, opciones)`:
  1) último lote con costo, 2) `precio_compra` de la ficha, 3) **NUEVO** precio de venta de 1 unidad ×
  (1 − margen). `_precio_de_una_unidad`: precio de la unidad suelta o, si no tiene, precio de la presentación ÷
  factor (el más bajo). Margen en Configuración (`margen_costo_estimado`, 0–90, por defecto 30). La pantalla
  ya ocultaba el campo de costo cuando `costo_sugerido > 0`, así que deja de pedirlo. Sin precio de venta →
  sigue pidiendo el costo. Pruebas en `tests/test_conteos.py`.
- **«Unexpected token '<' ... is not valid JSON» al cobrar** (mostrador, 24-oct, caja #1008; con F5 cobró
  bien sin volver a entrar): la página del POS tenía la clave `_csrf` VIEJA (se volvió a entrar al programa en
  otra ventana) → `verificar_csrf` hacía `abort(400)` y salía la página de error en HTML. Ahora:
  - `auth.es_pedido_api()` ("/api/" en la dirección) y `respuesta_api_error()`: para /api/ los errores 400,
    401 (sesión cerrada, en `login_required`/`roles_required`), 403, 404 y 500 contestan JSON
    `{ok: false, error, sesion}`. El 500 queda en fervifarma.log con la dirección.
  - Clave vieja con la sesión viva → 400 JSON con `csrf_nuevo`. En `base.html` (primer `<script>` del head)
    `window.fetch` envuelto: si llega `csrf_nuevo` y el cuerpo es FormData con `_csrf`, cambia la clave en todos
    los `input[name=_csrf]` y repite el pedido UNA vez (seguro: nada se guardó). Si un pedido a /api/ recibe
    HTML (pantalla de Ingresar u otra), lo cambia por JSON con un mensaje claro.
- **Búsqueda: lo más parecido de primero** (pedido de Fernando: "TAM" daba ACETAMINOFEN de primero y TAMPONES ni
  salía si había más de 40 resultados). `busqueda.orden_relevancia(q)` → CASE con puestos: 0 código/barras
  exacto, 1 nombre empieza por todo lo escrito, 2 por la primera palabra, 3 una palabra del nombre empieza
  (separadores espacio / - ( +), 4 lo contiene, 5 lo demás. Sin nada escrito devuelve "NULL" (un "0" SQLite lo
  toma como número de columna). Va ANTES del LIMIT 40 en el POS (después: stock > 0, nombre, laboratorio),
  recepción (reemplaza su regla propia), toma de inventario y lista de productos.
- Pruebas: `tests/test_version_1111.py`.

### Versión 1.1.10 — la 1.1.9 no se armó en GitHub (2026-10-23)
- La publicación V.1.1.9 falló en «Pruebas del programa en Windows»: `test_version_118` lee el Acta con
  `pypdf`, que estaba instalada aquí pero no en GitHub (no está en requirements.txt porque el programa no la
  usa). Se agregó `pypdf` a la línea `pip install` del workflow (solo pruebas). El programa es igual a 1.1.9.
  Para revisar este tipo de falla: simular que falta la librería con `sys.modules['pypdf'] = None`.

### Versión 1.1.9 — recepción abierta hasta confirmar, foto arriba (2026-10-22)
- Pedido de Fernando: que la recepción funcione como el conteo de inventario. Pruebas: `tests/test_version_119.py`.
- **Recepción ABIERTA con guardado automático**: 3 s después de cada cambio la pantalla manda todo el formulario
  (menos la foto) a `POST /recepciones/api/borrador` → `_guardar_borrador()` (la misma función del botón
  «⏸ Guardar y seguir después», antes «Guardar en espera»). Al salir con cambios pendientes: `sendBeacon`
  en `pagehide`. Indicador `#borrador-estado` junto a los botones.
- **Migración 40**: `recepciones_espera.token` y `recepciones.borrador_token`. Cada pantalla trae un
  `borrador_token` al azar (`_token_nuevo`): el borrador se busca por `espera_id` o por token (así el
  primer guardado y el siguiente no crean dos); al confirmar se guarda el token en la recepción y se borran
  las abiertas con ese id o token. Si ya hay recepción con ese token: el borrador se ignora
  (`confirmada: true`) y un segundo «Confirmar» redirige a la ya creada (sin duplicar).
- Botón principal **«✔ Confirmar recepción»** (con pregunta `data-confirmar`; el script respeta
  `e.defaultPrevented` para no dejar de guardar si dicen Cancelar). Lista **«Recepciones abiertas»** con
  **«▶ Continuar recibiendo»**; título «Recepción abierta · continuar recibiendo»; alerta renombrada.
- **Foto arriba** (hecho en el otro chat, revisado aquí): `modal-con-foto` (campos | cuadro de 120 px que se
  toca para escoger la foto) en «Nuevo producto» y «Completar datos».
- **El 0 vuelve al dar Enter** (`ui.js`, listener `submit` en captura → `devolverCero` en los campos con
  `data-cero-oculto`).

### Versión 1.1.8 — recepción en espera, Acta compacta, fotos y conteo que no se borra (2026-10-21)
- Pedidos de Fernando del 20 y 21 de octubre. Pruebas: `tests/test_version_118.py`.
- **Recepción EN ESPERA** (migración 39, tabla `recepciones_espera`): botón «⏸ Guardar en espera»
  (`name="accion" value="espera"`, `formnovalidate`) guarda TODO el formulario como JSON
  (`{campo: [valores]}`), sin validar y sin crear recepción, número REC-, lotes ni pago. Lista «En espera»
  arriba de Recepciones con «Continuar» (`/recepciones/nueva?espera=ID`, repinta con
  `_form_de_espera` → `MultiDict` → `_valores_previos` + `_lineas_previas_formulario(form)`) y «Descartar».
  Campo oculto `espera_id`: al guardar la recepción de verdad se borra la espera en el mismo commit; si
  hay error, la espera sigue. Si el número REC- quedó ocupado, se sugiere el siguiente. La foto de la
  factura no se guarda en espera (se avisa). Alerta amarilla `recepciones_espera` en Inicio.
- **Acta de recepción en PDF**: cada producto en UN renglón (nombre + concentración · laboratorio; forma ·
  presentación; vida útil y condiciones seguidas), columna producto 6,8 cm e INVIMA 3,2 cm, relleno 1,5,
  datos generales en 2 filas. Con 45 líneas: 37 en la 1.ª hoja y ~44 en las siguientes (antes ~13).
- **Foto del producto desde la recepción**: cuadro «Foto del producto» (`fotoRapida()` en form.html, vista
  previa con `URL.createObjectURL`) en «Nuevo producto» y «Completar datos». `_guardar_foto_producto()`
  (campo `imagen` o `imagen_accion=eliminar`; borra la foto vieja). Si la foto falla, el producto se guarda
  igual y vuelve `aviso`. `api/producto/<id>/tecnicos` GET trae `imagen_url`.
- **Fotos .jfif** (y .jpe, .pjpeg, .pjp): `utils_imagenes.EXT_JPG_OTROS`, se guardan como `.jpg`; también en
  la foto de la recepción y en Documentos. Los selectores de archivo dicen `accept="image/*,.jfif"`.
- **El 0 desaparece al dar clic** (`static/js/ui.js`, en todo el programa): campos `type=number` o
  `inputmode=numeric|decimal`; focus (captura) → clase `campo-num-activo` (azul, al final de app.css con
  `!important` para ganarle a moderno.css) y si vale 0 se vacía (`data-cero-oculto`); change/blur en
  captura → si quedó vacío vuelve el 0 ANTES de que la pantalla lo lea (así la toma de inventario nunca
  guarda un campo vacío).
- **El conteo de efectivo no se borra**: `window.conteoEfectivo` (script en `pos/_modal_conteo.html`) guarda
  cada cambio en `localStorage` (`fervifarma.conteoEfectivo.apertura` / `.cierre-<caja_id>`, con
  `detalle` y `confirmado`). Abrir «Contar» ya no pone todo en 0; el modal de cierre recupera el contado.
  Se borra: apertura al cargar el POS con caja abierta; cierre al cerrar la caja (y los de cajas viejas).
  Botón «Limpiar» para empezar de cero.
- **Abrir cajón antes de abrir caja**: botón «🔓 Abrir cajón» en `pos/abrir_caja.html` →
  `POST /pos/api/abrir-cajon-apertura` (administrador, director técnico y auxiliar; funciona con la caja
  CERRADA, a diferencia de `/pos/api/abrir-cajon`). Bitácora `cajon_abierto` con `motivo=apertura`.

### Versión 1.1.7 — recepción en una línea, Bancos y Cuentas por pagar (2026-10-20)
- Pruebas: `tests/test_version_117.py` (incluye una que revisa que TODO formulario POST lleve `_csrf`).
- **Recepción en una línea**: columnas propias Cant. | UdM | Costo | IVA | Importe (`#tabla-lineas`,
  `table-layout: fixed`, anchos en app.css «RECEPCIÓN EN UNA LÍNEA»). Debajo del producto solo una línea
  pequeña (INVIMA + Completar datos). En pantallas angostas la tabla se desliza dentro de su caja.
- **Migración 38**: `cuentas_bancarias` (nequi, davivienda; `fecha_inicial` = día de la primera venta),
  `bancos_movimientos` (traslados y retiro/aporte del dueño), `caja_movimientos.origen` (manual/cartera/
  devolucion/gasto/otro_ingreso/proveedor), caja menor reconstruida con tipos `pago_proveedor`, `a_banco`,
  `de_banco`; `proveedores.plazo_dias`; `recepciones.total_pagar/pago_estado/pago_vence`; `pagos_proveedores`.
- **Bancos** (`app/bancos.py`): el saldo NO se copia: se suma cada vez con un UNION de ventas (y partes de
  pagos mixtos), abonos, devoluciones, otros ingresos, gastos, movimientos manuales de la caja POS, pagos a
  proveedores y `bancos_movimientos`, filtrando por forma de pago = clave de la cuenta. Cuadrar: diferencia
  → retiro/aporte del dueño o gasto «Gastos bancarios» / otro ingreso «Intereses bancarios». Retiros del
  dueño en bancos se suman a «retiros del dueño» (informativo) de Utilidades. Aviso de gastos/ingresos/abonos
  con forma «transferencia» (no se sabe a qué cuenta).
- **Cuentas por pagar** (`app/cuentas_pagar.py`): la recepción pregunta crédito (vence = hoy + plazo del
  proveedor; 30 si no tiene) o contado (de dónde salió la plata). Pago completo (Fernando no hace abonos).
  El pago NO es gasto (la mercancía se vuelve costo al venderse): solo saca plata (caja menor, salida de
  efectivo de la caja POS, Nequi/Davivienda o «otro»). Anular devuelve la plata. Recepciones de antes →
  `por_revisar`: «Ya estaba pagada» (solo Nequi/Davivienda/otro, para no tocar el efectivo de hoy) o «Se
  debe». Rechazar recepción → `no_aplica`. Dashboard: «Le debo a proveedores», «Plata disponible», pagos en
  el flujo de caja; alerta `cxp_vencidas` (vencidas o a 3 días).
- **GitHub Actions**: checkout@v5, setup-python@v6, upload-artifact@v6, action-gh-release@v3 (las primeras en
  Node 24; mismas entradas).

### Versión 1.1.6 — catálogos, IVA, dashboard contable y sesiones de caja (2026-10-19)
- Fernando pidió juntar las listas de 1.1.6 y 1.1.7 en una sola versión. Pruebas: `tests/test_version_116.py`.
- **POS**: clic en el buscador (o F3) selecciona todo el texto (`pos_carrito.js`, mousedown → focus + select).
- **Ícono en la barra de tareas** (`icono_ventana.py`, llamado desde `escritorio.py`): un hilo busca las ventanas
  Chrome_WidgetWin_1 con «· Fervifarma» en el título (o «Comprobante/Recibo/Cotización») y les pone
  AppUserModelID `Fervifarma.Programa` + RelaunchCommand/Icon (SHGetPropertyStoreForWindow) y WM_SETICON (lo
  repone si Chrome lo cambia). El instalador pone el mismo AppUserModelID en los accesos directos. Usa WinDLL
  propios (no toca `windll` del cajón). Favicon por defecto: `img/app-192.png` (antes 💊 en SVG).
- **Nombres** (`app/nombres.py`): `clave()` = huella sin mayúsculas/tildes/espacios/signos para detectar
  repetidos; collation SQLite `ES` (todos los `ORDER BY ... COLLATE ES`) y función `PLANO()` para buscar sin
  tildes («codeina» encuentra «Codeína»). `orden_unidades`: «Unidad» primero, luego por cantidad, luego nombre.
- **Sin repetidos**: catálogos, unidades, importador y altas rápidas devuelven el existente. Pantalla
  `/admin/catalogos/repetidos` une los ya repetidos (reasigna productos, gastos, uniones; reactiva si hace falta).
- **Varios principios activos** (`app/principios.py`, tabla `producto_principios`, migración 35): campo de texto
  con comas y sugerencias (`campoConComas` en base.html) en el producto, «Completar datos» de la recepción e
  importador. `principio_id` queda con el primero (compatibilidad). La búsqueda mira todos.
- **Laboratorio opcional** en las altas rápidas (recepción y conteo); se llama «Laboratorio o marca».
- **IVA en la recepción** (migración 36): IVA % por línea (sale de la ficha), casilla «los precios ya incluyen
  IVA», Subtotal + IVA = Total. Se guardan `costo_sin_iva` y `costo_con_iva`; `costo_unitario` (el de la
  utilidad) = sin IVA si Configuración → «¿La droguería declara IVA?» = Sí; con IVA si = No (por defecto).
- **Dashboard contable** (`contabilidad._datos_dashboard`, reutiliza `utilidades.calcular`): 4 tarjetas con
  variación contra el período anterior, flujo de caja, dona de gastos, acciones rápidas, últimos movimientos,
  ventas vs. gastos 6 meses, cartera, compras, últimas cajas, alertas; tarjeta de IVA solo si declara IVA.
- **Sesiones de caja** (`app/cajas.py`, `/contabilidad/cajas` y detalle): diferencia azul (cuadró), roja con −
  (faltó), verde con + (sobró). Al cerrar caja, `registrar_diferencia` apunta el sobrante como otro ingreso
  («Sobrante de caja») o el faltante como gasto («Faltante de caja"), sin mover plata (el contado ya volvió a
  caja menor). `registrar_pendientes` lo hace al arrancar con las cajas cerradas antes (migración 37,
  `cajas.diferencia_revisada` evita repetir).

### Versión 1.1.5 — POS como en el programa anterior (2026-10-19)
- Pedido de Fernando y su esposa (videos del mostrador comparando con el programa anterior). Todo en
  `static/js/pos_carrito.js` (+ `pos/index.html`, `app.css`):
- `agregar()` → `quedarseEnElCarrito()`: el cursor sale del buscador y queda en la línea agregada, en modo
  cantidad. El teclado físico global (6b) recibe las teclas: números arman la cantidad (3 → 3, 3 0 → 30),
  Enter cobra, Suprimir/Backspace en 1 → `quitarConDeshacer()` (aviso «↶ Deshacer» 6 s).
- Lector vs. persona (6c): con el cursor fuera del buscador cada carácter se guarda 70 ms
  (`lectorGuardar`); si llegan con < 35 ms entre sí y son ≥ 4 → `escanear(código)` (no toca búsqueda ni
  tarjetas). Si es persona: números = cantidad (sin producto marcado → al buscador), letras → `irAlBuscador`
  (reemplaza la búsqueda). En el buscador: ráfaga rápida + Enter = lector → se devuelve el texto anterior.
- La búsqueda ya no se borra al agregar; «X» (`#pos-limpiar-busqueda`) la borra. Espera 120 ms (antes 250).
- `actualizarInsignias()`: numerito verde en cada tarjeta = cuántos van en el carrito.
- Línea marcada del carrito más visible.

### Versión 1.1.4 — fechas en líneas agregadas; la 1.1.3 no se publicó (2026-10-18)
- La publicación V.1.1.3 falló en GitHub: `test_saneamiento::test_semanal_queda_hecha_toda_la_semana` fallaba
  los LUNES (esperaba "Pisos" hecha cuando hoy es inicio de semana) y GitHub corre en UTC (ya era lunes).
  Error de la prueba, no del programa: «Pisos» nadie la marcó → siempre pendiente. Para revisar este tipo de
  fallas: correr las pruebas con `TZ=UTC`.
- Fechas (`static/js/ui.js`): en las líneas agregadas con «+ Agregar línea», el campo de fecha se copiaba
  "muerto" (marcado `data-fecha-propia`, ya oculto): no completaba 28 → 2028, no pasaba la fecha al programa y el
  calendario no abría. `mejorarFecha` usa un WeakSet de campos listos y rehace las copias; `mejorarFechas` busca
  también `input[data-fecha-propia]`. `textoAIso` acepta año de 2 cifras (→ 20xx). `original.required` se
  refleja en el campo visible (la recepción marca la fecha obligatoria si el producto maneja vencimiento).

### Versión 1.1.3 — cajón SAT, alarma sin perder la recepción (2026-10-18)
- Lo que vio Fernando (impresora SAT Q150U): el botón decía «Cajón abierto» pero no abría, ni al vender;
  sonó la alarma de temperatura en medio de una recepción, registró y la recepción se perdió;
  pidió el código de barras en el modal «Nuevo producto» de la recepción.
- `app/cajon.py`: `ORDENES` = estandar (ESC p 25 ms×2), largo (ESC p 100), tiempo_real (DLE DC4 1 m 5),
  todas precedidas de ESC @. `impresora_usada()` dice a qué impresora llegó la orden.
  Configuración: «Tipo de orden para abrir el cajón» (`cajon_orden`); «Probar cajón» usa lo que está
  en pantalla sin guardar y dice impresora + orden. El POS dice «Orden de abrir enviada a «X»».
  (El programa no puede saber si el cajón abrió: solo que la orden llegó a la impresora.)
- `app/temperaturas.py`: `_guardar_lectura()` (reglas comunes) + `POST /temperaturas/api/registrar/<zona>`.
  `static/js/alarma.js`: «Registrar ahora» abre `pedirDatos` encima de la página (sin navegar);
  si hay error (fuera de rango sin acción) vuelve a abrir con lo escrito.
- `recepciones/form.html`: campo «Código de barras» (Enter del lector pasa al siguiente campo; si en
  el buscador de la línea se escaneó un código, se copia); aviso «¿Salir del sitio?» si hay cambios sin guardar.
- Búsqueda con LABORATORIO (pedido de Fernando: muchos productos se llaman igual y solo cambia el
  laboratorio, ej. TRAZODONA CLORHIDRATO 50 MG · SAN FER). `app/busqueda.py`: `condicion_palabras(q)`
  — cada palabra debe estar en nombre, código, barras, concentración, principio activo o laboratorio;
  `ORDEN_NOMBRE_LAB`. Se usa en recepción (y kardex), lista de productos, conteo, devolución a
  proveedor e inventario; el POS agrega concentración y laboratorio a su búsqueda por palabras.
  En pantalla: `window.chipLaboratorio()` (base.html) + `.lab-chip` (app.css) — etiqueta del laboratorio
  a la derecha de cada resultado, en la tarjeta del POS y en el conteo; «Sin laboratorio» en naranja.
- Recepción: debajo del costo de cada línea, «Total: $…» = cantidad × costo (ej. 4 × 10.058,2 = 40.232,8),
  se actualiza al escribir (`.linea-total-txt`, en `recalcularTotales`).
- Alta rápida (`/recepciones/api/crear-producto`, también la usa el conteo): el producto queda
  `iva_tipo='excluido'`, `iva_tarifa=0` (antes, el valor por defecto de la base: gravado 19 %). El IVA se ajusta en la ficha.
- Buscador de la recepción (y kardex): «meloxi» no mostraba «MEBLAINEX MELOXICAM» porque solo salían 8
  resultados y los que EMPIEZAN igual (MELOXICAM …) ocupaban todos. Ahora 40 resultados y orden: código exacto →
  nombre empieza → nombre contiene → lo demás (laboratorio, principio activo).
- «Completar datos» no mostraba laboratorios creados después de abrir la página (BLASKOV, ECAR): la lista se
  llenaba una sola vez. `GET /admin/catalogos/<tipo>/api/lista` + `refrescarLaboratorios()` al abrir los dos
  modales; botón «+» (`crearLaboratorio`) también en «Completar datos»; el nuevo queda en las dos listas.
- Recepción: cantidad, UdM y costo obligatorios en toda línea CON producto (`ajustarRequeridos`; antes las
  líneas agregadas perdían el `required`). Líneas vacías no estorban (campos en blanco, no "0"). Mensajes en
  español (`invalid`). Servidor: error si falta la UdM. Los errores de la recepción salen TODOS en una lista.
- PAGO MIXTO (una parte por Nequi/Davivienda/tarjeta y el resto en efectivo). Migración 34: tabla
  `venta_pagos (venta_id, forma_pago, monto)`; la venta queda `forma_pago='mixto'`. `pos._pagos_mixtos()` valida
  (mínimo dos formas, no pasar el total, el efectivo recibido alcanza la parte en efectivo). `_resumen_caja`
  parte las mixtas: cada parte suma en su forma (el efectivo entra al efectivo esperado); n_ventas cuenta ventas.
  Comprobante y tirilla directa: una línea por forma de pago. Informes: fila «Mixto (varias formas)».
  POS: botón «🔀 Mixto», campos Nequi/Davivienda/Tarjeta, «En efectivo» = el resto, efectivo recibido y cambio;
  el cajón se abre si hubo parte en efectivo (modo «Al cobrar en efectivo»).

### Versión 1.1.2 — cajón, instalar desde Chrome (2026-10-17)
- Lo que vio Fernando: el cajón no abría ni al cobrar ni con el botón «Abrir cajón»; la ventana del
  programa abría con Edge; quería el botón «Instalar» de Chrome en la barra de direcciones.
- Causa del cajón: `ctypes.windll.winspool` hace que Windows busque `winspool.dll`, que no existe
  (el archivo real es `winspool.drv`). Fallaba antes de hablarle a la impresora. Afectaba también la
  tirilla directa (usa el mismo `cajon.enviar_crudo`).
- `app/cajon.py`: `_winspool()` carga `ctypes.WinDLL("winspool.drv")` con argtypes/restype (64 bits);
  `enviar_crudo` atrapa cualquier error de Windows y devuelve un mensaje claro (y lo anota en el log).
- `escritorio.py`: `buscar_navegador()` busca primero Chrome; Edge queda de respaldo.
- `app/instalable.py`: `/manifest.webmanifest` y `/sw.js` (sin caché, sin contraseña); íconos
  `static/img/app-192.png` y `app-512.png`; `<link rel="manifest">` en base.html y login.html.
  Chrome solo ofrece instalar en localhost/127.0.0.1 o https (no por 192.168.x.x ni 100.x.x.x).

### Versión 1.1.1 — "database is locked" (2026-10-13)
- Lo que vio Fernando en el PC del local: error 500 al abrir caja y al borrar productos; productos sin cantidad.
- Causa (fervifarma.log): la importación guardaba miles de fotos dentro de UNA transacción; mientras
  tanto la base quedaba bloqueada para todos y las cantidades (que se cargan al final) aún no estaban.
- `importador.confirmar`: cada foto se procesa sin bloquear y se guarda (commit) enseguida. WEBP method=4.
- `__init__.py`: "database is locked" muestra "El programa está ocupado…" (503) en vez de error 500.
- `escritorio.py`: si el puerto 8765 está tomado, no prende otro programa (antes, con el programa
  ocupado, un doble clic prendía un segundo). Waitress con 12 hilos.

### Versión 1.1.0 — dos computadores (2026-10-13)
- Pedido de Fernando: el portátil (director técnico) hace tareas administrativas y ayuda a vender,
  en el local **y desde la casa**; la tirilla del portátil sale por la impresora del mostrador.
- `config.py` lee `<datos>/equipo.json` (lo escribe el instalador): principal que comparte,
  principal solo, o conectado (con la dirección del principal).
- `app/equipo.py`: candado de red (solo este PC, red privada y Tailscale 100.64.0.0/10; lo demás 403),
  lista de equipos conectados. Página **Administración → Red y equipos** (`red.html`).
- `escritorio.py`: en el portátil no prende servidor, abre la ventana del principal (con Reintentar si
  no contesta); en el principal que comparte, cerrar la ventana no apaga el programa.
- `app/tirilla_directa.py`: comprobante en ESC/POS (PC850, 32/48 letras), mandado RAW con
  `cajon.enviar_crudo`. Configuración: modo de tirilla (navegador/directa), tildes, «Imprimir prueba».
  POS: botón «Imprimir tirilla», «Reimprimir último» directo; comprobante: «Imprimir en el mostrador».
- Instalador: página «¿Cómo se usa este computador?», dirección del principal, regla de cortafuegos
  (programa + puerto 8765 + red local/Tailscale, con UAC una vez) y cierre del programa antes de copiar.
- Pendiente probar en el local: Tailscale real, cortafuegos, tirilla directa en la impresora térmica.

### Correcciones tras las pruebas de Fernando (2026-10-11)
- **Menú lateral reordenado** (pedido de Fernando): Inicio · Día a día (POS, Temperaturas) · Productos
  (Productos, Recepciones, Inventario, Cotizaciones, Proveedores*) · Contabilidad* (Contabilidad, Cartera,
  Caja menor) · ── · Calidad, desplegable como Administración (Equipos, Documentos, Saneamiento,
  Capacitaciones, Quejas, Farmacovigilancia; se abre sola en sus páginas) · Reportes · Administración* ·
  Mi cuenta (Apariencia). *solo administrador y director técnico.
- **POS, ventana Editar (sobre la "i")**: el precio que se edita es el de lo que se vende normalmente
  (Sello/Sobre/Blíster/Caja…, según `venta_defecto_unidad_id`), con su precio máximo; filas aparte para
  la unidad suelta (si `vende_suelto`) y las demás presentaciones (`precio_pres_<id>`). Si no se vende
  suelto, la unidad = precio ÷ factor (igual que `productos._traducir_venta`). La franja de la "i" muestra
  ese precio. El carrito actualiza cada línea con el precio de SU presentación.
- **Tirilla**: al imprimir, todo negro y en negrilla y letra Consolas/Lucida Console (Courier New salía
  tenue en la térmica); 58 mm un punto más grande. "Ver comprobante" abre con `rel="opener"` (Chrome trata
  `target=_blank` como noopener) y "Volver" intenta cerrar la pestaña aunque no conozca la ventana del POS.
- **Cajón monedero sin imprimir** (`app/cajon.py`): orden ESC/POS `ESC p 0/1 25 250` en modo RAW a la
  impresora de Windows (ctypes + winspool.drv, sin instalar nada). Configuración → Impresora de tirillas:
  nombre de la impresora (vacío = predeterminada) y "Abrir el cajón al cobrar" (nunca / efectivo /
  siempre) + botón "Probar cajón". En el POS: se abre solo al cobrar según eso y botón "Abrir cajón"
  (menú ☰). Cada apertura queda en la bitácora (`cajon_abierto`, motivo cobro/manual).
- **Cierre de caja**: el "Efectivo contado" se puede escribir directo (si ya está contado) o seguir usando
  "Contar" por denominación (`pos.js: leerContado`; toma solo los dígitos y recalcula la diferencia al escribir).
- **Campos de números en todo el programa**: sin flechitas de subir/bajar (app.css) y la rueda del mouse
  ya no cambia el valor (ui.js: al girar la rueda sobre el campo activo se le quita el cursor).
- **Caja menor: "Registrar aporte" / "Registrar retiro"** no se veían (y "Completar datos" de la recepción
  tampoco): a esas ventanas les faltaba la regla de ventana flotante en app.css. Se agregaron, y
  `tests/test_modales.py` revisa que toda ventana `<div id="modal-..." class="modal-oculto">` tenga su regla.
- **Recepción, nota de conversión**: si el producto se vende por Sello x 10 (u otra), la nota bajo la
  cantidad dice "= 15 Sello x 10 (150 Tableta) · $2.000 c/Sello x 10" (antes solo en la unidad mínima).
  `_presentaciones_simples` marca `defecto` (la de venta) y `cuenta` (cuántas mínimas trae la unidad de
  inventario); el JS (`prepararSelector`) divide las "Otras unidades" por esa cuenta, igual que el servidor
  (`_presentacion_por_unidad`): antes, con inventario en SELLO X 10, la pantalla mostraba de más.

## 8. Pendientes por hacer

### Inmediatos (dependen de Fernando)
- [x] Probar el importador con el Excel real (1.336 productos, 1.134 fotos, 981 lotes).
- [ ] Inventario inicial: primer conteo con los productos reales y sus costos.
- [ ] Registrar los equipos reales y subir sus certificados de calibración.

### Corto plazo
- [x] **Parte visual — que el programa se vea más profesional** (temas, letra, íconos, barra superior, Inicio, POS con carrito y teclado a la izquierda, reportes en pestañas, toasts, fechas dd/mm/aaaa, ventanas propias en vez de prompt, tirilla 80 mm ✅, todos los PDF con el mismo encabezado, colores y pie de página ✅ — ver `app/pdf_utils.py`: `encabezado_pdf`, `estilo_tabla`, `pie_de_pagina`) (pedido por Fernando, 2026-10-10). Propuesta:
  1. **Guía de estilo única:** colores de la marca Fervifarma, tipografía Inter (archivo local), tamaños y espacios en variables CSS; una página interna que muestre todos los componentes.
  2. **Unificar componentes repetidos:** un solo estilo de botón, de tabla (hoy hay `.tabla`, `.rep-tabla`, `.sug-tabla`, `.eres-tabla`…), de tarjeta y de formulario.
  3. **Íconos de verdad en vez de emojis** (juego SVG local, por ejemplo Lucide): los emojis se ven distintos en cada Windows.
  4. **Barra superior útil:** título de la página, ruta (Inicio › Reportes › Ventas), caja abierta y usuario con su rol.
  5. **Pantalla de ingreso con la marca** (logo, colores) y favicon.
  6. **Formularios:** fechas en dd/mm/aaaa siempre (selector propio, no el del navegador en inglés), errores al lado del campo, campos agrupados.
  7. **Mensajes tipo "toast"** que aparecen y se van solos, en vez de franjas que empujan la página.
  8. **Tablas:** encabezado fijo al bajar, números alineados a la derecha, estados vacíos amables, paginación.
  9. **POS táctil:** botones grandes (mínimo 44 px), contraste alto.
  10. **Impresos coherentes:** comprobante de venta en tirilla de 80 mm y todos los PDF con el mismo encabezado. ✅ (2026-10-11: color verde del programa, línea bajo el encabezado y pie "Impreso el … por … · Página N" en todas las hojas; la hoja mensual de temperaturas no lleva pie porque es de una sola hoja con márgenes mínimos)
  Forma de trabajo: primero la guía de estilo y una maqueta de 2–3 pantallas para aprobar, luego módulo por módulo.
- [x] **Cotizaciones** ✅ (`app/cotizaciones.py`, migración 29): en el POS, menú ☰ → "Guardar como cotización" (cliente, celular, validez en días, nota) guarda el carrito como COT-0001 sin tocar inventario ni caja; se abre en tirilla 58/80 con Imprimir, **WhatsApp** (mensaje con productos y total, al celular con +57) y **Vender** (carga en el POS: venta nueva con los precios cotizados y motivo "Cotización COT-…" si está vigente; vencida, con los precios de hoy). Al cobrarla queda "convertida" con su venta (`ventas.cotizacion_id`). Lista en el menú Día a día → Cotizaciones (abiertas/vendidas/anuladas, anular). `/pos/api/productos?ids=…` para cargar productos exactos.
- [ ] (⏸ solo si el contador lo pide) Reporte de IVA con prorrateo (Art. 490 ET).

### Mediano plazo
- [ ] Módulo de control especial (FNE) con libro oficial (hoy el POS bloquea su venta). ⏸ Fernando lo deja para una actualización posterior (2026-10-10).
- [ ] Gestión documental (POE con versiones), plan de saneamiento, capacitaciones, farmacovigilancia.
- [ ] Modo Inspección (paquete para la Secretaría de Salud).
- [ ] Empaquetado para Windows (ventana propia, instalador, arranque automático).

### Largo plazo
- [ ] Facturación electrónica DIAN (según lo que diga el contador).
- [ ] (⏸ lejano) IA para clasificación automática de productos.
- [ ] Imágenes automáticas por código de barras.
- [ ] App móvil.
- [ ] Alertas a Telegram / WhatsApp.

### Hecho (antes estaba en esta lista)
- [x] Cartera (ventas a crédito y abonos), venta libre y otros ingresos, carrito del POS, gastos discriminados, utilidades y estado de resultados, módulo Reportes R1–R8, control de precios máximos con alerta, venta por presentación, panel de alertas, equipos y calibraciones, confirmaciones con la ventana del programa.

## 9. Pendientes por confirmar (con el usuario y terceros)

- **Con la Secretaría de Salud:** formatos exactos exigidos, frecuencia de lecturas, tiempo de conservación de registros.
- **Con el contador:**
  - ¿Obligado a facturación electrónica? ¿Desde cuándo?
  - Régimen tributario (responsable de IVA o no).
  - Prorrateo de IVA: ¿lo maneja hoy?
  - Formato de Estado de Resultados preferido.
- **Con el proveedor tecnológico** (si aplica): facturación electrónica.
- **Sobre el local:** horarios exactos de apertura/cierre, días de mercado.

## 10. Registro de migraciones (schema_version)

| Versión | Contenido |
|---|---|
| 1 | usuarios, bitacora, config |
| 2 | proveedores, productos |
| 3 | zonas_temperatura, equipos, temperatura_registros |
| 4 | catalogos |
| 5 | campos nuevos en productos, productos_categorias, productos_usos, presentaciones_producto |
| 6 | renombrado de catálogos (presentacion → forma_farmaceutica) |
| 7 | unidades_medida |
| 8 | recepciones, recepcion_lineas, lotes, movimientos_inventario |
| 9 | temperatura_ingreso + clasificacion_defecto en recepcion_lineas |
| 10 | creado_en_importacion en productos |
| 11 | imagen en productos |
| 12 | cajas, ventas, venta_lineas |
| 13 | detalle_apertura y detalle_cierre en cajas |
| 14 | caja_movimientos |
| 15 | gastos |
| 16 | caja_menor_movimientos (fondo permanente) |
| 17 | precio_original y motivo_precio en venta_lineas (cambio de precio al vender) |
| 18 | conteos y conteo_lineas (toma de inventario) |
| 19 | limpieza: borra presentaciones_producto; sinónimos en los usos (buscador por síntoma) |
| 20 | `producto_presentaciones` (venta por unidad / sobre / caja) + `venta_lineas.presentacion_id` |
| 21 | `caja_menor_movimientos.retiro_dueno` + categoría de gasto "Sueldo del dueño" |
| 22 | `equipos` rehecha con más tipos y `frecuencia_meses`; tabla `calibraciones` |
| 23 | `devoluciones` y `devolucion_lineas` (de cliente y a proveedor) |
| 24 | `usuarios.tema` (verde, azul o clásico) |
| 25 | `venta_lineas` reconstruida: `producto_id` opcional + `es_libre`, `costo_libre` (venta libre); tabla `otros_ingresos`; categorías `categoria_ingreso` (se siembran en init_db) |
| 26 | Cartera: tabla `clientes` (cupo), `ventas.cliente_id`, tabla `cartera_abonos` |
| 27 | `productos.venta_defecto_unidad_id`; `recepcion_lineas.presentacion` y `factor` (recibir por caja/sobre) |
| 28 | `productos.vende_suelto` (1 = también se vende la unidad mínima suelta) |
| 29 | `cotizaciones`, `cotizacion_lineas` y `ventas.cotizacion_id` (cotizaciones del POS) |
| 30 | `documentos` y `documento_versiones` (gestión documental, Fase 4.1) |
| 31 | `limpieza_tareas` (con las 3 de Fernando), `limpieza_registros`, `control_plagas`, `residuos_registros`, `residuos_entregas` (Fase 4.2) |
| 32 | `personal`, `capacitaciones`, `capacitacion_asistentes` (Fase 4.3) |
| 33 | `pqrs` (Fase 4.4) y `farmacovigilancia` (Fase 4.5) |

## 11. Estado del proyecto (actualizar al final de cada sesión)

- [x] Fase 0: base completa
- [x] 1.1 Productos, proveedores, catálogos, unidades
- [x] 1.2 Temperaturas con alarma y reportes
- [x] 1.3 Recepción técnica con Acta PDF
- [x] 1.4 Inventario por lote
- [x] 1.5a Importador (probado con el archivo real: productos + fotos + lotes)
- [x] 1.5b Inventario inicial (Toma de inventario lista; falta cargar los datos reales)
- [x] 2.1 POS (caja, carrito, cobro, anulación, cambio de precio con motivo, botón "i")
- [x] 2.2 Gastos discriminados
- [x] 2.3 Utilidades (R2)
- [x] 2.4 Estado de resultados (R2)
- [ ] 2.5 IVA con prorrateo ⏸ solo si el contador lo pide
- [x] 2.6 Flujo de caja (lo cubren R1 + cierre de caja)
- [x] 3.1 Devoluciones
- [x] 3.2 Precios máximos
- [x] 3.3 Alertas INVIMA
- [ ] 3.4 Control especial (FNE) ⏸ para una actualización posterior
- [~] Fase 4: cumplimiento — 4.1 Documentos ✅, 4.2 Saneamiento ✅, 4.3 Capacitaciones ✅, 4.4 Quejas ✅, 4.5 Farmacovigilancia ✅; autoinspección y Modo Inspección ⏸ para una actualización posterior (decisión de Fernando, 2026-10-11: empieza a usar el programa en la droguería con lo que hay)
- [ ] Fase 5: Facturación electrónica
- [ ] Fase 6: IA
- [x] Fase 7: Empaquetado (instalador de Windows por GitHub Actions)

**Última sesión:** 2026-10-10. Se completó: login y temas, parte visual 4 (toasts, fechas, ventanas propias, tirilla 58/80 mm), venta libre y otros ingresos, Cartera, unidades (inventario en la unidad mínima, ficha por unidad de venta, conteo en paquetes), ajustes según capturas de Fernando (ficha, recepción con UdM, conteo con un solo "Agregar"), importador único (productos + fotos + lotes del programa anterior), acciones sobre varios productos, flechas en la ficha, ficha compacta, completar datos técnicos desde la recepción. **406 tests pasan**.

**Sesión 2026-10-09 (tarde).** Se completó:
- **Reparación:** el commit "ultimo" dejó cortados `app/pos.py` (de 776 a 108 líneas), `static/js/pos_carrito.js` y `static/css/pos_nuevo.css` (se guardaron a medias). Se restauraron desde el commit `9b1f54a` y se le sumaron los cambios nuevos.
- Cambio de precio al vender con motivo + tope de precio máximo + bitácora.
- Botón "i" con información del producto (nueva ruta `/pos/api/producto/<id>`).
- Tests ajustados a la regla de caja menor + 9 tests nuevos: **95 tests pasan**.
- Rediseño de la ventana "i" + ventana "Editar" encima: **104 tests pasan**.
- Módulo **Toma de inventario** (conteo físico, inventario inicial, vender durante el conteo, acta PDF): **126 tests pasan**.
- **Limpieza (2026-10-09):** menú por secciones (Día a día, Productos, Dinero, Consultas, Administración) y por rol (el auxiliar ya no ve enlaces que le niegan; el DT ahora ve Contabilidad y Caja menor); usos convertidos en buscador por síntoma; quitado el catálogo Tipos de pago y la tabla presentaciones_producto; aclarada salida de efectivo vs gasto; quitados avisos de "Próximamente" que estorbaban en el menú del POS; reportes reducidos de 15 a 8. **137 tests pasan**.
- **Ajustes tras probar en Codespaces (2026-10-09):** conteo como lista alfabética, botón "Producto encontrado" en vez de "Lote encontrado", buscador fijo arriba; textos de los métodos de pago del cobro visibles (estaban en blanco sobre blanco).
- **Venta por presentación (2026-10-09):** cada producto puede venderse por unidad, sobre, caja… con su propio precio; el inventario se descuenta en unidades. Ventana "¿Cómo lo vendes?" en el POS, presentaciones en el formulario de productos, código de barras de la caja, margen por presentación en la "i". La demo trae Acetaminofén e Ibuprofeno por tableta, sobre y caja. **158 tests pasan**.
- **Panel de alertas (2026-10-09):** "Para atender hoy" en el Inicio con 12 tipos de alerta (ver 5.1); arreglado el texto "con stock mínimo definido" de la tarjeta de productos, que salía vacío. **176 tests pasan**.
- **R2 Utilidades (2026-10-09):** estado de resultados con costo real por lote, gastos por categoría, pérdidas de inventario, retiros del dueño aparte, comparación con el período anterior y PDF. Casilla "retiro del dueño" en caja menor. Decisiones de Fernando: pérdidas en línea aparte; su sueldo (variable) es gasto en "Sueldo del dueño" y además retira ganancias; registra todos los gastos en Contabilidad; por defecto mes actual vs anterior. **194 tests pasan**.
- **Reportes (2026-10-09):** R6 Sugerido de compra (pedido por proveedor con WhatsApp e imprimir) y R1, R3, R4, R5, R7, R8 con menú común de reportes. **215 tests pasan**.
- **Equipos y limpieza (2026-10-09):** módulo de equipos y calibraciones con certificado y alertas; todas las confirmaciones usan la ventana del programa (atributo `data-confirmar` en formularios y botones, manejado en base.html; en JS `await window.confirmar(...)`); plata en mensajes con punto de miles (`app/formato.py`, `pesos()`); Contabilidad sin tarjetas "próximamente" (llevan a Reportes). **229 tests pasan**.
- **Devoluciones (2026-10-09):** de cliente (reingreso al mismo lote o baja, reembolso desde la caja abierta) y a proveedor (con o sin nota crédito, acta PDF); integradas en Utilidades, R1 y R4. **246 tests pasan**.
- **Resumen y Excel (2026-10-09):** tarjetas de semana, mes y utilidad del mes en el Inicio; descarga en Excel de cualquier reporte. **249 tests pasan**.
- **Rediseño parte 1 (2026-10-10):** temas por usuario (Verde salud, Azul, Clásico), letra IBM Plex Sans local, íconos de línea, menú y barra superior nuevos, Inicio sin accesos rápidos. Rama `antes-del-rediseno` para volver atrás. **255 tests pasan**.
- **Rediseño parte 2 (2026-10-10):** POS con varias ventas a la vez (pestañas, botón + y F4) y carrito a la derecha en el diseño nuevo.
- **Rediseño parte 3 (2026-10-10):** reportes con pestañas arriba (diseño nuevo), gráficos con el color del tema, títulos de página sin emoji en el diseño nuevo (en Clásico siguen).
- Orden acordado para seguir: importar productos (Excel real) → primer conteo = inventario inicial → ~~venta por presentación~~ ✅ → ~~panel de alertas~~ ✅ → ~~utilidades/estado de resultados~~ ✅ → ~~reportes~~ ✅ → ~~equipos/calibraciones~~ ✅ → ~~devoluciones~~ ✅.
- Consejo: antes de hacer commit, revisar que `git diff --stat` no muestre cientos de líneas borradas en un archivo que no se tocó.

**Sesión anterior:** 2026-10-07. Se completó:
- Sistema de imágenes (cualquier formato) con logo en login, sidebar y PDFs.
- Rediseño del dashboard con KPIs y alertas reales.
- Módulo de inventario por lote con kardex y semáforo.
- Plantilla mensual de temperaturas en PDF (una hoja A4).
- Importador de productos (pendiente prueba real).
- POS Bloque 1: apertura/cierre de caja con conteo por denominación.
- Menú lateral derecho del POS con ingresos/salidas de efectivo.
- Modal de cierre de caja con desglose por forma de pago.
- Modal de confirmación global (reemplazo de `confirm()` nativo).
- Cambio de layout: sidebar fijo, main con margin-left, modales flotan correctamente.

**Siguiente:** Módulo de contabilidad básica (gastos + utilidades + estado de resultados).

---

## 12. Notas técnicas importantes

### Layout CSS
- `body.layout`: sin `display: flex`.
- `.sidebar`: `position: fixed` a la izquierda.
- `.main`: `margin-left: 240px` (62px colapsado).
- Modales: `position: fixed; inset: 0` con `z-index: 10000`.

### Modales
- Todos usan `id` específicos: `#modal-crear`, `#modal-producto`, `#modal-conteo`, `#modal-confirmar`, `#modal-cierre-caja`, `#modal-movimiento`.
- Se cargan como bloques `{% block modales %}` en `base.html`.
- Se evitan `confirm()` nativos; se usa `window.confirmar()` (promesa).

### JavaScript
- `static/js/alarma.js`: alarma global de temperatura.
- `static/js/pos.js`: POS completo (drawer, movimientos, cierre).
- `static/js/chart.umd.min.js`: gráficos.

### Base de datos
- `PRAGMA journal_mode = WAL` para concurrencia.
- `PRAGMA foreign_keys = ON`.
- Bitácora con triggers inmutables.
- `schema_version` para migraciones incrementales.
- `_asegurar_columnas_productos()` como red de seguridad.

### Respaldos
- Uso de `sqlite3.backup()` (API oficial, seguro con WAL).
- Verificación con `PRAGMA integrity_check`.
- Retención de 30 por defecto.
- Carpeta adicional opcional (`BACKUP_EXTRA_DIR`).

---

**Última actualización:** 2026-10-07