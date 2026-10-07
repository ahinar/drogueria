# Sistema de droguería Fervifarma

Sistema completo de gestión de calidad + POS para droguería.
Funciona en la red local, sin internet. Diseñado para **dos computadores**:
el PC del mostrador es el **servidor**; el PC de la bodega se conecta por navegador.

---

## 1. Qué incluye el sistema

### Gestión de calidad
- **Usuarios con roles:** Administrador, Director Técnico y Auxiliar, con permisos diferenciados.
- **Bitácora de auditoría inmutable:** cada acción queda registrada con usuario, fecha, IP y detalle. No se puede editar ni borrar (ni siquiera desde SQLite directamente).
- **Respaldos automáticos y manuales** de la base de datos y de los PDF.

### Control de temperatura y humedad
- Zonas configurables (Nevera, Ambiente, Vitrina, Cuarentena…).
- Registro **una vez por la mañana y una vez por la tarde** (AM/PM) en cada zona.
- **Alarma sonora y visual** que aparece en cualquier página del sistema hasta que se registra la lectura.
- Registro de acciones correctivas cuando la lectura está fuera de rango.
- Historial con gráfico de evolución.
- **Plantilla mensual en PDF** para imprimir y firmar (una hoja por zona y mes).

### Productos, catálogos y proveedores
- Catálogo de productos con:
  - Código interno auto-generado.
  - Nombre, concentración, principio activo, forma farmacéutica, laboratorio.
  - Registro sanitario INVIMA y fecha de vencimiento del registro.
  - Categorías (se pueden elegir varias).
  - Usos / indicaciones (se pueden elegir varios).
  - Precio de compra (opcional), precio de venta, precio máximo regulado, IVA (gravado / excluido / exento).
  - Banderas: requiere fórmula médica, cadena de frío, control especial (FNE).
  - **Múltiples unidades de venta** (Unidad, Sello x 10, Caja x 100, etc.) con precio por unidad.
  - Imagen del producto.
  - Vista **Mosaico** (con imagen) o **Lista** (tabla), recordada por usuario.
- **Búsqueda por:** nombre, código, código de barras, principio activo, laboratorio, concentración.
- **Autocompletado** en todas las búsquedas.
- **Alta rápida de producto** desde la recepción, sin salir del formulario.
- Proveedores con NIT, razón social, contacto y documentación sanitaria.

### Recepción técnica
- Registro de cada entrega de proveedor con:
  - Número consecutivo (REC-0001, REC-0002…).
  - Proveedor, factura / remisión, temperatura de llegada.
  - Por cada línea: producto, lote, vencimiento, cantidad, costo unitario, estado del empaque y resultado (aceptado / cuarentena / rechazado).
  - Temperatura de ingreso (obligatoria para cadena de frío).
  - Foto adjunta opcional.
- **Acta de Recepción Técnica en PDF** conforme a la norma, con:
  - Encabezado con logo y datos del negocio.
  - Detalle por producto (DCI, forma farmacéutica, presentación, INVIMA, lote, vencimiento, vida útil restante %).
  - Concepto técnico automático.
  - Bloque de firmas: recibido por (Auxiliar) y aprobado por (Director Técnico).
- **Estados:** cuarentena → aprobada (crea lotes disponibles) / rechazada.
- Al aprobar, se generan **lotes disponibles** para venta.

### Inventario por lote
- Kardex por producto con historial de movimientos.
- Semáforo de vencimiento: 🟢 >90 días · 🟡 30-90 días · 🔴 <30 días · ⚫ vencido.
- Bloqueo/desbloqueo manual de lotes con motivo.
- Ajustes de cantidad con motivo (queda en el kardex).

### Punto de venta (POS)
- **Apertura de caja** con conteo de efectivo por denominación (billetes y monedas colombianas).
- Pantalla principal con carrito y buscador.
- **Menú lateral derecho** con:
  - Cerrar caja.
  - Ingreso de efectivo (efectivo / Nequi / Davivienda).
  - Salida de efectivo.
  - Últimas ventas (próximamente).
  - Cliente (próximamente).
  - Nota (próximamente).
  - Consulta de inventario.
  - Reimprimir último (próximamente).
- **Cierre de caja** como modal con desglose completo:
  - Efectivo: apertura, ventas del turno, ingresos, salidas, esperado, contado, diferencia.
  - Nequi y Davivienda: ventas + ingresos − salidas.
  - Tarjeta: ventas del turno.
  - Conteo por denominación con calculadora de total.

### Importar productos desde Excel / CSV
- Descarga de plantilla.
- Vista previa antes de importar.
- Detección automática de duplicados.
- Creación automática de catálogos faltantes.
- Reporte de errores por fila.

### Configuración
- Datos del negocio (NIT, razón social, dirección, teléfono, correo).
- Datos del Director Técnico.
- Logo (cualquier formato: JPG, PNG, WEBP, GIF, TIFF, BMP, HEIC).
- Pie de página legal para comprobantes.

### Reportes
- Reporte de temperaturas con gráfico y PDF.
- Plantilla mensual de temperaturas en PDF (para imprimir y firmar).
- Más reportes en camino (utilidades, gastos, recepciones, vencimientos).

---

## 2. Instalación (solo en el PC principal, una vez)

1. Instala **Python 3.11 o superior** desde python.org. En el instalador marca **"Add Python to PATH"**.
2. Copia esta carpeta al PC principal, por ejemplo en `C:\drogueria`.
3. Abre la carpeta, haz clic en la barra de direcciones, escribe `cmd` y pulsa Enter.
4. Ejecuta estos comandos, uno por uno:

---

## 3. Arrancar

Doble clic en `iniciar_servidor.bat`. Verás dos direcciones:

- En el mismo PC: `http://localhost:5000`
- Desde el otro PC: `http://192.168.x.x:5000` (la dirección exacta aparece en la ventana)

La primera vez el sistema pide crear el **administrador**. Después, desde **Usuarios**, crea los
demás usuarios (Director Técnico, Auxiliar).

Si Windows pregunta por el Firewall, permite el acceso en **redes privadas**.

### Primeros pasos
1. Entra con el administrador.
2. Ve a **Configuración** y llena los datos del negocio, del Director Técnico y sube el logo.
3. Ve a **Administración → Catálogos** y revisa los valores predefinidos.
4. Ve a **Administración → Unidades de medida** y crea las presentaciones que uses (Sello x 10, Caja x 100, etc.).
5. Crea los **Productos** (a mano o importando desde Excel).
6. Crea los **Proveedores**.
7. Configura las **zonas de temperatura**.
8. Registra la primera **Recepción técnica** con una factura real.
9. Abre la **Caja del POS** y empieza a vender.

---

## 4. Que arranque solo al encender el PC

1. Presiona `Win + R`, escribe `shell:startup` y pulsa Enter.
2. Copia ahí un acceso directo a `iniciar_servidor.bat`.

---

## 5. Respaldos

- El sistema hace un respaldo automático al iniciar si el último tiene más de 24 horas.
- También puedes crearlo desde **Respaldos** o con `hacer_respaldo.bat`.
- Para un respaldo diario a las 10 p. m. (ajusta la ruta), abre `cmd` como administrador:

- Para copiar cada respaldo a una memoria USB o a una carpeta sincronizada con la nube, define la
  variable de entorno `DROGUERIA_BACKUP_EXTRA` con esa carpeta (ejemplo: `setx DROGUERIA_BACKUP_EXTRA "E:\respaldos"`).
- **Restaurar:** cierra el sistema, copia el respaldo que quieras sobre `db\drogueria.db` (renómbralo) y
  borra los archivos `drogueria.db-wal` y `drogueria.db-shm` si existen.

---

## 6. Recomendaciones

- Usa un **UPS** en el PC principal.
- Reserva una IP fija para ese PC en el router, para que la dirección no cambie.
- No expongas el puerto 5000 a internet.
- Guarda una copia de los respaldos fuera del local.
- **Nunca borres `db/secret.key`** (mantiene las sesiones válidas).

---

## 7. Pruebas (opcional)

---

## Estructura del proyecto

---

## 8. Módulos del sistema (menú lateral)

- 🏠 **Inicio** — dashboard con KPIs y alertas.
- 🛒 **Vender (POS)** — punto de venta.
- 💊 **Productos** — catálogo.
- 📦 **Recepciones** — recepción técnica.
- 🗃️ **Inventario** — lotes, kardex, vencimientos.
- 🌡️ **Temperaturas** — registro y alarma.
- 📊 **Reportes** — informes en pantalla y PDF.
- 🗂️ **Administración** — clientes, proveedores, catálogos, unidades.
- 📋 **Bitácora** — auditoría.
- 👤 **Usuarios** — gestión de usuarios y roles.
- ⚙️ **Configuración** — datos del negocio y logo.
- 💾 **Respaldos** — copias de seguridad.

---

## 9. Requisitos técnicos

- **Python:** 3.11 o superior.
- **Sistema operativo:** Windows 10 / 11 (probado en Windows 11 LTSC).
- **Navegador:** Chrome, Edge, Firefox (actualizados).
- **Red:** ambos PCs en la misma red local (WiFi o cable).
- **Espacio en disco:** 500 MB libres.
- **RAM:** 4 GB mínimo.

---

**Última actualización:** 2026-10-07