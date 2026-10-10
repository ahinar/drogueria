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
- `presentaciones_producto` (antigua tabla, sin uso actual).

### Temperaturas
- `zonas_temperatura`: nombre, descripción, temp_min, temp_max, controla_humedad, humedad_min, humedad_max, horarios, dias_semana, minutos_tolerancia, activa.
- `temperatura_registros`: zona_id, equipo_id, fecha, programada_para, temperatura, humedad, dentro_de_rango, accion_correctiva, usuario_id, usuario_nombre.
- `equipos`: nombre, tipo, marca, modelo, serie, zona_id, fecha_calibracion, proxima_calibracion (sin uso aún).

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
- Tarjeta de ventas del día (pendiente del POS completo).
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
- Mientras haya una ventana abierta, el teclado del POS (Enter = cobrar, números) no actúa.
- Carrito guardado en el navegador por caja (no se pierde al recargar; se borra al cobrar).
- Pantalla principal con layout de 2 columnas.
- Menú lateral derecho (drawer) con 8 opciones.
- Movimientos de caja (ingreso / salida) para efectivo, Nequi, Davivienda.
- **Regla del dinero:** *salida de efectivo* = solo **mover plata** (consignar, pasar a caja menor, cambiar billetes). Todo **pago** (domicilio, insumos, servicios) es un **gasto** (desde el POS o desde Contabilidad; es la misma tabla). *Retiro* de caja menor = sacar plata del fondo (consignar o lo que retira el dueño). La ventana de salida lo explica y tiene un botón directo a "Registrar gasto".
- Cierre de caja como modal con desglose completo.
- Modal de conteo reutilizable.

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
- **Pendientes:** ver el plan del módulo Reportes en la sección 7 (Fase R).

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
- **2.1** POS interno ✅ (caja, carrito, cobro, anulación, cambio de precio, ventana "i").
- **2.2** Gastos discriminados ✅ (módulo Contabilidad + caja menor).
- **2.3 / 2.4** Utilidades y estado de resultados → se hacen como **R2** en Reportes (pendiente).
- **2.5** IVA con prorrateo ⏸ solo si el contador lo pide.
- **2.6** Flujo de caja ⏸ lo cubren R1 Ventas (por día y forma de pago) + el cierre de caja.

### Fase R: módulo Reportes ⏳
Idea (tomada de DATA FARMAC): una pantalla con la lista de reportes a un lado y el
reporte elegido al otro, con **selector de período** (día, semana, mes, año o
fechas), gráfico (Chart.js local), tabla y descarga en PDF/Excel.
**Reglas de todos:** las ventas anuladas no cuentan; los montos van con y sin IVA.

Se juntaron los reportes que repetían el mismo cálculo con otro período
(antes eran 15, quedan 8 + Temperaturas, que ya existe):

| # | Reporte | Qué muestra | Reemplaza a | Quién lo ve |
|---|---|---|---|---|
| R1 | **Ventas** | Ventas por día, semana, mes o año; comparación con el período anterior; desglose por forma de pago y por vendedor | Ventas de la semana, Ventas anuales, Ingresos por día, Ingresos por usuario | Admin y DT |
| R2 | **Utilidades y estado de resultados** | Ventas − costo de lo vendido (costo real del lote) − gastos, por día o por período; estado de resultados simplificado | Ganancia de la semana, Utilidades (Fase 2.3 y 2.4) | Admin y DT |
| R3 | **Top productos** | Los más vendidos por unidades y por dinero (top 5, 10 o 20) | Top 5 productos | Admin y DT |
| R4 | **Ventas vs compras** | Comparativo mensual: lo vendido vs lo comprado (recepciones aprobadas) | — | Admin y DT |
| R5 | **Gastos** | Gastos del período por categoría | Gastos administrativos | Admin y DT |
| R6 | **Sugerido de compra** | Qué pedir y cuánto, por proveedor: venta diaria promedio (30 días), días que alcanza el stock, cantidad para cubrir N días. Listas: **bajo stock mínimo**, **se agota en < 7 días**, **sin rotación** (60/90 días). Pedido para imprimir o enviar por WhatsApp | — | Admin y DT |
| R7 | **Recepciones** | Recepciones por proveedor y período, rechazos y motivos | — | Todos |
| R8 | **Vencimientos** | Semáforo en PDF para inspección | — | Todos |
| — | Temperaturas | Ya existe (gráfico, PDF y plantilla mensual) | — | Todos |

Notas:
- El **Resumen** de DATA FARMAC no es un reporte aparte: sus números (ventas de hoy,
  semana y mes, utilidad del mes, alertas) van en la pantalla de **Inicio**.
- **Utilidades** vive en Reportes; la tarjeta de Contabilidad lleva a ese reporte (un solo lugar).
- R6: solo cuenta stock vendible (no cuarentena ni vencidos). Las primeras semanas tras
  el inventario inicial no hay historial de ventas; mientras tanto se guía por el stock mínimo.
- Más adelante, cuando existan: **venta libre** en el POS y **otros ingresos** → se agregan
  como filtros dentro de R1 Ventas (no como reportes aparte).
- _Descartados por decisión de Fernando: Top 5 servicios y Medicamentos vs Servicios._
- Visto en DATA FARMAC y anotado como idea: **Cotización** y **Deudas** (fiados).

### Fase 3: alertas y precios ⏳
- **3.1** Devoluciones.
- **3.2** Precios máximos de venta.
- **3.3** Alertas INVIMA con cruce de lotes.
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

### Inmediatos
- [x] Carrito funcional del POS (agregar producto, cobrar, comprobante).
- [ ] Probar el importador con el Excel real (1500+ productos).
- [ ] Inventario inicial (cargar stock real de la droguería).
- [ ] Módulo de gastos discriminados.
- [ ] Reporte de utilidades por período.

### Corto plazo
- [ ] Estado de Resultados simplificado.
- [ ] (⏸ solo si el contador lo pide) Reporte de IVA con prorrateo (Art. 490 ET).
- [ ] Módulo Reportes (Fase R, sección 7): R1 a R8. Venta libre y otros ingresos entran después como filtros de R1.
- [ ] Venta libre en el POS y registro de otros ingresos.
- [ ] (Idea) Cotizaciones y deudas/fiados.
- [ ] Reemplazar todos los `confirm()` nativos por el modal de confirmación.

### Mediano plazo
- [ ] Devoluciones (a proveedor y de cliente).
- [ ] Control de precios máximos con alerta.
- [ ] Módulo de control especial (FNE) con libro oficial.
- [ ] Gestión documental (POE).
- [ ] Modo Inspección.

### Largo plazo
- [ ] (⏸ lejano) IA para clasificación automática de productos.
- [ ] Imágenes automáticas por código de barras.
- [ ] Facturación electrónica DIAN.
- [ ] App móvil.
- [ ] Alertas a Telegram / WhatsApp.

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
- Orden acordado para seguir: importar productos (Excel real) → primer conteo = inventario inicial → venta por presentación → panel de alertas → utilidades/estado de resultados → reportes → equipos/calibraciones → devoluciones.
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