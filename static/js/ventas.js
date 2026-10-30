// =====================================================================
// PANTALLA VENTAS (versión 1.1.14) — app/ventas.py, app/templates/ventas/
// ---------------------------------------------------------------------
// Al tocar una venta de la lista (izquierda), se trae su panel (derecha) desde
// /ventas/<id>/panel y se pone ahí, SIN cambiar de pantalla. La dirección del
// navegador se actualiza (?venta=<id>) para que F5 muestre la misma venta.
// Si algo falla, el enlace de la fila abre la venta de la forma normal.
// =====================================================================
(function () {
  'use strict';
  const panel = document.getElementById('vtas-panel');
  const lista = document.querySelector('.vtas-tabla');
  if (!panel || !lista) return;
  const URL_PANEL = panel.dataset.url;                 // /ventas/0/panel → se cambia el 0

  async function mostrar(id, fila) {
    lista.querySelectorAll('.vtas-fila.activa').forEach((f) => f.classList.remove('activa'));
    if (fila) fila.classList.add('activa');
    panel.classList.add('cargando');
    try {
      // Los filtros viajan también, para que los formularios del panel vuelvan a esta búsqueda
      const resp = await fetch(URL_PANEL.replace('/0/', '/' + id + '/') + window.location.search,
                               { credentials: 'same-origin' });
      if (!resp.ok) throw new Error('el servidor respondió ' + resp.status);
      panel.innerHTML = await resp.text();
      const params = new URLSearchParams(window.location.search);
      params.set('venta', id);
      window.history.replaceState(null, '', '?' + params.toString());
      // En el celular el panel queda debajo de la lista: se baja hasta él
      if (window.innerWidth < 900) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
      const enlace = fila && fila.querySelector('a.vtas-enlace');
      if (enlace) window.location.href = enlace.href;     // plan B: abrir de la forma normal
    } finally {
      panel.classList.remove('cargando');
    }
  }

  // Clic en cualquier parte de la fila (no solo en el número)
  lista.addEventListener('click', (e) => {
    const fila = e.target.closest('.vtas-fila');
    if (!fila) return;
    e.preventDefault();
    mostrar(fila.dataset.id, fila);
  });

  // «Corregir el pago»: las casillas de cada forma solo se ven si escoge «Mixto».
  // Se escucha en el panel entero porque su contenido cambia con cada venta.
  panel.addEventListener('change', (e) => {
    if (!e.target.classList.contains('vtas-forma')) return;
    const mixto = e.target.closest('form').querySelector('.vtas-mixto');
    if (mixto) mixto.hidden = e.target.value !== 'mixto';
  });
})();
