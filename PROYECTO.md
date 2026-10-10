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
- CRUD tipo Odoo: Unidad (factor 1), Sello x 10 (factor 10), Caja x 100 (factor 100), etc.
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
- **Botón "i"** en cada tarjeta (ventana estilo Odoo): franja amarilla (nombre, precio, a la mano, IVA, insignias), **Inventario** (lotes vendibles FEFO + aviso de lotes en cuarentena/bloqueados/vencidos), **Reabastecimiento** (últimas 4 compras aprobadas + stock mínimo) y **Finanzas** de 1 unidad (precio sin IVA, costo = promedio ponderado de lotes, margen sobre precio sin IVA, precio máximo). Ruta `/pos/api/producto/<id>`.
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
Problema que lo originó: el acetaminofén tenía 308 **tabletas**; al cambiar "Se vende por" a Sobre x 10 el programa leyó **308 sobres** y vender 2 sobres dejó 306 (debían quedar 288). Se investigó cómo lo hacen los POS de droguería y Odoo: inventario en la unidad más pequeña, presentaciones con factor, compras en otra unidad convertida, y la unidad no se cambia si ya hay movimientos.
- **Unidad de inventario** (antes "Se vende por"; columna `productos.unidad_venta_id`): la más pequeña que se vende (tableta, cápsula, frasco). Las existencias, el precio normal y el costo son de 1 unidad de inventario. **Queda bloqueada** cuando el producto ya tiene lotes, movimientos o ventas (el servidor también lo impide). Aviso si se escoge una unidad "grande" (Caja x 100).
- **"El POS lo vende por defecto como"** (`productos.venta_defecto_unidad_id`): tableta, sobre o caja. Al tocar la tarjeta en el POS se agrega esa presentación directo; la tarjeta muestra su precio ("Sobre x 10 · $1.800"), el stock en la unidad de inventario ("Stock: 288 Tableta") y "📦 Otras: …", que se puede tocar para escoger otra.
- **Asistente "Cambiar unidad de inventario"** (`/productos/<id>/cambiar-unidad`, `app/unidad_inventario.py`): (1) *solo corregir el nombre* (los números ya eran de la unidad nueva) o (2) *convertir* con factor N (1 unidad vieja = N nuevas): cantidades × N en lotes, kardex, conteos, recepciones, devoluciones y factor de las ventas; costos ÷ N; presentaciones × N; la unidad vieja queda como presentación con su precio y como venta por defecto. Bitácora `producto_unidad_cambiada`.
- **Recepciones por caja/sobre:** cada línea tiene **"viene en"** (presentaciones del producto); cantidad y costo se escriben como en la factura (3 cajas a $25.000) y se guardan en unidades (300 tabletas a $250); `recepcion_lineas.presentacion` y `factor` para mostrarlo. Escanear el código de barras de la caja deja la línea en "Caja". El detalle muestra "3 Caja x 100 = 300 Tableta".
- **Importador:** columnas nuevas **Unidad de inventario**, **Costo/Precio de 1 unidad**, **Presentación 2 / 3** (nombre, cuántas trae, precio) y **El POS lo vende como**. Unidades que no existen se crean ("Blíster x 12" → cantidad 12). Los números aceptan punto de miles (1.800). La plantilla y la ayuda salen de la misma lista de columnas.
- Conteo físico y kardex dicen en qué unidad se cuenta ("se cuenta en Tableta").
- Pruebas: `tests/test_unidades.py` (incluye el caso de Fernando).

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

### Fase 4: gestión documental y cumplimiento ⏳
- Documentos (PNO) con versiones.
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

### Fase 7: empaquetado y distribución ⏳
- Ventana nativa con pywebview (sin CMD).
- Ejecutable .exe con PyInstaller.
- Instalador con Inno Setup.
- Arranque automático en Windows 11 LTSC.
- Ícono personalizado.

## 8. Pendientes por hacer

### Inmediatos (dependen de Fernando)
- [ ] Probar el importador con el Excel real (1500+ productos).
- [ ] Inventario inicial: primer conteo con los productos reales y sus costos.
- [ ] Registrar los equipos reales y subir sus certificados de calibración.

### Corto plazo
- [~] **Parte visual — que el programa se vea más profesional** (temas, letra, íconos, barra superior, Inicio, POS con carrito y teclado a la izquierda, reportes en pestañas, toasts, fechas dd/mm/aaaa, ventanas propias en vez de prompt, tirilla 80 mm ✅; queda: unificar estilos de tablas y PDF con el mismo encabezado) (pedido por Fernando, 2026-10-10). Propuesta:
  1. **Guía de estilo única:** colores de la marca Fervifarma, tipografía Inter (archivo local), tamaños y espacios en variables CSS; una página interna que muestre todos los componentes.
  2. **Unificar componentes repetidos:** un solo estilo de botón, de tabla (hoy hay `.tabla`, `.rep-tabla`, `.sug-tabla`, `.eres-tabla`…), de tarjeta y de formulario.
  3. **Íconos de verdad en vez de emojis** (juego SVG local, por ejemplo Lucide): los emojis se ven distintos en cada Windows.
  4. **Barra superior útil:** título de la página, ruta (Inicio › Reportes › Ventas), caja abierta y usuario con su rol.
  5. **Pantalla de ingreso con la marca** (logo, colores) y favicon.
  6. **Formularios:** fechas en dd/mm/aaaa siempre (selector propio, no el del navegador en inglés), errores al lado del campo, campos agrupados.
  7. **Mensajes tipo "toast"** que aparecen y se van solos, en vez de franjas que empujan la página.
  8. **Tablas:** encabezado fijo al bajar, números alineados a la derecha, estados vacíos amables, paginación.
  9. **POS táctil:** botones grandes (mínimo 44 px), contraste alto.
  10. **Impresos coherentes:** comprobante de venta en tirilla de 80 mm y todos los PDF con el mismo encabezado.
  Forma de trabajo: primero la guía de estilo y una maqueta de 2–3 pantallas para aprobar, luego módulo por módulo.
- [ ] (Idea) Cotizaciones. (Las deudas quedaron en **Cartera** ✅, ver 5.9d.)
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

## 11. Estado del proyecto (actualizar al final de cada sesión)

- [x] Fase 0: base completa
- [x] 1.1 Productos, proveedores, catálogos, unidades
- [x] 1.2 Temperaturas con alarma y reportes
- [x] 1.3 Recepción técnica con Acta PDF
- [x] 1.4 Inventario por lote
- [~] 1.5a Importador (código listo, sin probar con Excel real)
- [x] 1.5b Inventario inicial (Toma de inventario lista; falta cargar los datos reales)
- [x] 2.1 POS (caja, carrito, cobro, anulación, cambio de precio con motivo, botón "i")
- [ ] 2.2 Gastos discriminados
- [ ] 2.3 Utilidades
- [ ] 2.4 Estado de resultados
- [ ] 2.5 IVA con prorrateo
- [ ] 2.6 Flujo de caja
- [ ] 3.1 Devoluciones
- [ ] 3.2 Precios máximos
- [ ] 3.3 Alertas INVIMA
- [ ] 3.4 Control especial (FNE)
- [ ] Fase 4: Gestión documental
- [ ] Fase 5: Facturación electrónica
- [ ] Fase 6: IA
- [ ] Fase 7: Empaquetado

**Última sesión:** 2026-10-09 (tarde). Se completó:
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