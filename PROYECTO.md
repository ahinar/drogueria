# PROYECTO: Sistema de gestión de calidad + POS para droguería

> Documento maestro. Se adjunta al inicio de cada chat nuevo para retomar el trabajo sin perder el hilo.

## 0. Cómo usar este documento

1. En un chat nuevo, adjunta este archivo (y el código actual de la carpeta del proyecto si ya existe).
2. Escribe: "Continuamos con la Fase X, paso Y" (mira la sección 8).
3. Trabaja **un paso pequeño por vez**. Nunca pidas "todo el programa" en un solo mensaje.
4. Al terminar cada paso: guarda los archivos, prueba que funcione y actualiza la sección 8 (Estado).
5. Si el chat se llena, no pasa nada: abre uno nuevo y repite desde el punto 1.

## 1. Decisiones ya tomadas

- Es un programa para una droguería en Colombia con **gestión de calidad + POS**.
- **Temperaturas:** registro con recordatorios sonoros y visuales llamativos.
- **Recepción técnica:** alimenta el inventario y guarda el formato de cada recepción según la ley.
- **Utilidades y ganancias** calculadas por períodos.
- **Fácil y sencillo**, con datos que se puedan guardar.
- Se usarían **dos computadores a la vez** en el local.
- **Sin facturación electrónica por ahora**, pero el sistema debe quedar listo para agregarla después.
- A futuro: conexión a alertas sanitarias (INVIMA) y a información de medicamentos, con IA.

## 2. Stack técnico (CONFIRMADO: Flask + SQLite)

- **Python + Flask + SQLite** (un solo archivo `.db`), interfaz web en la red local.
- PC principal (mostrador) = servidor. PC secundario (bodega) entra por navegador, sin instalar nada.
- Funciona **sin internet**. Internet solo para avisos al celular y funciones futuras.
- Alternativa más simple si se usa un solo computador: Excel con macros (menos robusta para registros legales).

### Estructura de carpetas sugerida

```
drogueria/
  app/            (rutas, modelos, plantillas HTML)
  db/             (drogueria.db)
  pdfs/           (formatos de recepción, reportes)
  backups/        (copias automáticas)
  static/         (estilos, sonidos de alarma)
  tests/
  PROYECTO.md     (este documento)
```

### Principios

- Los registros legales (temperaturas, recepciones) **no se editan ni se borran**: una corrección es un registro nuevo que referencia al anterior, con motivo. Las ventas se **anulan**, no se borran.
- **Bitácora de auditoría:** quién hizo qué y cuándo.
- **Roles:** Administrador (dueño), Director Técnico, Auxiliar.
- **Respaldo diario automático** de la base de datos y de los PDF, con copia adicional semanal.
- Servidor solo en red local, con usuarios y contraseñas.

## 3. Modelo de datos (tablas y campos clave)

- **usuarios:** nombre, usuario, clave (cifrada), rol, activo.
- **productos:** código, código de barras, nombre, principio activo, concentración, forma farmacéutica, registro sanitario INVIMA, fabricante, unidad, tratamiento de IVA (excluido/exento/gravado) y tarifa, precio de venta, precio máximo de venta (si aplica), stock mínimo, requiere fórmula, cadena de frío, control especial.
- **proveedores:** NIT, razón social, contacto, documentos (concepto sanitario, certificaciones), estado.
- **clientes:** tipo y número de documento, nombre, correo (por defecto "consumidor final").
- **recepciones:** número, fecha y hora, proveedor, factura o remisión, temperatura de llegada, resultado (aceptada / cuarentena / rechazada), recibido por, aprobado por, observaciones, ruta del PDF.
- **recepcion_lineas:** producto, lote, fecha de vencimiento, cantidad facturada, cantidad recibida, costo unitario, estado del empaque, resultado por línea.
- **lotes:** producto, lote, vencimiento, cantidad disponible, costo, estado (cuarentena, disponible, bloqueado, agotado, rechazado), motivo de bloqueo.
- **movimientos_inventario (kardex):** fecha, lote, tipo (recepción, venta, devolución, ajuste, baja), cantidad, referencia, usuario.
- **ventas:** consecutivo interno, fecha y hora, cliente, forma de pago, subtotal, descuento, IVA, total, usuario, estado (interno / anulada). Campos **reservados y vacíos** para facturación electrónica: número de factura, CUFE, estado DIAN, rutas PDF/XML.
- **venta_lineas:** producto, lote, cantidad, precio unitario, descuento, tarifa IVA, valor IVA, total.
- **devoluciones:** vínculo a la venta o recepción original, motivo, líneas (base de futuras notas crédito).
- **zonas_temperatura:** nombre (bodega, vitrina, nevera), rango de temperatura, rango de humedad, frecuencia de lectura, horas programadas.
- **temperatura_registros:** zona, fecha y hora, temperatura, humedad, usuario, dentro de rango (sí/no), acción correctiva, vínculo a corrección.
- **equipos:** termohigrómetro/nevera, ubicación, fecha de calibración, próximo vencimiento.
- **gastos:** fecha, categoría, descripción, valor, usuario.
- **config:** datos del emisor (NIT, razón social, dirección), numeración, parámetros de alertas.
- **bitacora:** fecha, usuario, acción, tabla, registro.
- **alertas_sanitarias** *(fase 3)*: fuente, fecha, enlace, producto, registro sanitario, lotes, medida, estado de revisión.
- **alertas_coincidencias** *(fase 3)*: alerta, lote afectado, revisado por, acción tomada.
- **documentos** *(fase 4)*: nombre, tipo (PNO, formato), versión, fecha de vigencia, archivo.

## 4. Reglas de negocio

**Estados de lote:** cuarentena → disponible (al aprobar la recepción) → agotado. Un lote puede quedar bloqueado (vencido, alerta sanitaria) o rechazado.

**Recepción técnica:**
- Se registra proveedor, factura o remisión, y por cada línea el producto, lote, vencimiento, cantidad y estado del empaque, más la temperatura de llegada si aplica.
- Resultado: aceptada, cuarentena o rechazada. Solo lo aceptado genera lotes **disponibles**.
- Al cerrar se genera un **PDF inmutable** con fecha, hora y responsables.

**Venta:**
- Descuenta del lote con **vencimiento más próximo**.
- No permite vender lotes vencidos, bloqueados, en cuarentena o rechazados.
- Avisa si el producto está próximo a vencer (rangos configurables, por ejemplo 90/60/30 días).
- Avisa o bloquea si el precio supera el precio máximo de venta regulado.
- El comprobante dice: **"Comprobante interno, no válido como factura"**.

**Temperaturas:**
- Frecuencia y rangos **configurables por zona** (los valores por defecto se confirman con la Secretaría de Salud y el fabricante).
- Nivel 1: a la hora programada, ventana llamativa (colores que destellan) con sonido hasta que se registre.
- Nivel 2: si pasan X minutos sin registro, aviso al celular del Director Técnico o del dueño.
- Lectura fuera de rango: obliga a registrar acción correctiva antes de cerrar.

**Utilidades:**
- Costo por lote (consistente con el descuento por vencimiento).
- Utilidad bruta = ventas netas − costo de lo vendido.
- Utilidad neta = utilidad bruta − gastos − mermas (vencidos, dañados, ajustes).
- Períodos: día, semana, mes y rango libre.

**Facturación electrónica (futuro):** módulo "facturador" separado. Hoy funciona en modo interno; después se reemplaza por el adaptador del proveedor elegido sin tocar POS, inventario ni reportes.

## 5. Pantallas por puesto

- **Mostrador:** inicio de sesión, POS, alarma de temperaturas, consulta de inventario, devoluciones.
- **Bodega:** recepción técnica, consulta de inventario, vencimientos.
- **Administrador:** utilidades y reportes, productos, proveedores, usuarios, gastos, configuración, respaldos.

## 6. Plan por fases

### Fase 0: base
- Instalar Python y Flask, crear estructura y base de datos.
- Inicio de sesión con roles y bitácora.
- **Listo cuando:** ambos PCs abren el sistema, entran con usuario y el respaldo diario funciona.

### Fase 1: calidad e inventario
- 1.1 Productos y proveedores.
- 1.2 Temperaturas con alarma y bitácora.
- 1.3 Recepción técnica con PDF.
- 1.4 Inventario por lote y kardex.
- **Listo cuando:** una recepción real aprobada crea lotes disponibles, genera su PDF y las lecturas de temperatura quedan registradas con recordatorio.

### Fase 2: ventas y utilidades
- 2.1 POS interno con lector de código de barras.
- 2.2 Gastos (reutilizando la plantilla actual de control de gastos).
- 2.3 Reporte de utilidades por período.
- 2.4 Control de vencimientos.
- **Listo cuando:** una jornada de ventas descuenta inventario y el reporte de utilidades coincide con un cálculo manual.

### Fase 3: alertas y precios
- 3.1 Devoluciones.
- 3.2 Precios máximos de venta.
- 3.3 Alertas INVIMA con cruce automático de lotes.
- **Listo cuando:** una alerta de prueba bloquea el lote coincidente y queda registrada la verificación.

### Fase 4: gestión documental y cumplimiento
- Documentos (PNO) con versiones, plan de saneamiento, capacitaciones, calibraciones, farmacovigilancia, modo inspección.
- **Listo cuando:** se exportan los registros de un período en un solo paquete.

### Fase 5: facturación electrónica
- Escoger proveedor y conectar el adaptador.

### Fase 6: resumen de noticias con IA
- Circulares, resoluciones y alertas resumidas en el tablero, siempre con enlace a la fuente.

## 7. Pendientes por confirmar

- Confirmar la propuesta técnica (Flask + SQLite) o elegir Excel.
- Con la Secretaría de Salud: formatos exigidos, frecuencia de lecturas, tiempo de conservación de registros.
- Con el contador: si estás obligado a facturación electrónica y desde cuándo.
- Si la droguería dispensa medicamentos de control especial.
- Si aplica el reporte de precios (SISMED).
- Proveedor de facturación electrónica y de mensajería para avisos (por ejemplo Telegram o correo).

## 8. Estado del proyecto (actualizar al final de cada sesión)

- [~] Fase 0: código entregado y probado con 22 pruebas automáticas; falta instalarlo y probarlo en el local (ver LEEME.md)
- [ ] 1.1 Productos y proveedores
- [ ] 1.2 Temperaturas
- [ ] 1.3 Recepción técnica
- [ ] 1.4 Inventario por lote
- [ ] 2.1 POS interno
- [ ] 2.2 Gastos
- [ ] 2.3 Utilidades
- [ ] 2.4 Vencimientos
- [ ] 3.1 Devoluciones
- [ ] 3.2 Precios máximos
- [ ] 3.3 Alertas INVIMA
- [ ] Fase 4
- [ ] Fase 5
- [ ] Fase 6

**Última sesión:** 2026-09-19. Se confirmó Flask + SQLite y se entregó la Fase 0 (usuarios con 3 roles, bitácora inmutable, respaldos verificados, servidor con waitress). Sigue: instalar en el PC principal, crear el administrador, abrir desde el 2.º PC y luego pasar al paso 1.1 (productos y proveedores).
