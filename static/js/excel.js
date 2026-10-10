// =====================================================================
// REPORTES · BOTÓN "📥 Excel"
// =====================================================================
// Lee TODAS las tablas del reporte que se está viendo y las manda al
// servidor (/reportes/excel), que devuelve un archivo .xlsx con una hoja
// por tabla. Así cualquier reporte se puede abrir en Excel sin programar
// una descarga distinta para cada uno.
// =====================================================================
(function () {
  'use strict';
  const boton = document.getElementById('exportar-excel');
  if (!boton) return;
  const cuerpo = document.querySelector('.rep-cuerpo');
  const tablas = cuerpo ? cuerpo.querySelectorAll('table') : [];
  if (!tablas.length) { boton.parentElement.style.display = 'none'; return; }   // el índice de reportes no tiene tablas

  // Texto de una celda: si tiene una casilla (ej: cantidades del pedido), su valor
  function textoCelda(celda) {
    const input = celda.querySelector('input, select');
    if (input) return input.value;
    // Solo el texto principal (sin el texto pequeño de abajo)
    const copia = celda.cloneNode(true);
    copia.querySelectorAll('small, .rep-barra, details ul').forEach((x) => x.remove());
    return copia.textContent.replace(/\s+/g, ' ').trim();
  }

  // Título de cada tabla: el h2 de su recuadro, o el título de la página
  function tituloDe(tabla) {
    const caja = tabla.closest('.rep-caja, .sug-proveedor, .sug-panel, .eres-tabla-caja');
    const h2 = caja && caja.querySelector('h2');
    if (h2) return h2.textContent.trim();
    // Sugerido de compra: el nombre de la pestaña (ej: "Bajo stock mínimo"), sin el número
    const panel = tabla.closest('.sug-panel');
    const pestana = panel && document.querySelector('.sug-pestanas button[data-pestana="' + panel.dataset.panel + '"]');
    if (pestana) return pestana.childNodes[0].textContent.trim();
    return (document.querySelector('.rep-cuerpo h1') || {}).textContent || 'Reporte';
  }

  boton.addEventListener('click', async () => {
    const datos = {
      titulo: ((document.querySelector('.rep-cuerpo h1') || {}).textContent || 'reporte').replace(/[^\wÁÉÍÓÚáéíóúñÑ ]/g, '').trim(),
      tablas: Array.from(tablas).map((t) => ({
        titulo: tituloDe(t).replace(/[^\wÁÉÍÓÚáéíóúñÑ ()]/g, '').trim(),
        encabezados: Array.from(t.querySelectorAll('thead th')).map(textoCelda),
        filas: Array.from(t.querySelectorAll('tbody tr, tfoot tr')).map((fila) =>
          Array.from(fila.children).map(textoCelda)),
      })),
    };
    boton.disabled = true;
    try {
      const csrf = (document.querySelector('input[name="_csrf"]') || {}).value || '';
      // Se manda como formulario (con el _csrf de seguridad) y las tablas en un campo de texto JSON
      const formulario = new FormData();
      formulario.append('_csrf', csrf);
      formulario.append('datos', JSON.stringify(datos));
      const resp = await fetch(boton.dataset.url, { method: 'POST', credentials: 'same-origin', body: formulario });
      if (!resp.ok) throw new Error('el servidor respondió ' + resp.status);
      // Descargar el archivo que llegó
      const archivo = await resp.blob();
      const enlace = document.createElement('a');
      enlace.href = URL.createObjectURL(archivo);
      enlace.download = (datos.titulo || 'reporte').replace(/ /g, '_') + '.xlsx';
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();
    } catch (e) {
      alert('No se pudo crear el Excel: ' + e.message);
    } finally {
      boton.disabled = false;
    }
  });
})();
