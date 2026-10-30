// =====================================================================
// MENÚ LATERAL (base.html) — versión 1.1.15: antes estaba escrito dentro de base.html
// ---------------------------------------------------------------------
// Recoger/abrir el menú (☰), menú del celular encima de la página, recogido solo en
// las pantallas anchas (data-pantalla-ancha) y grupos en acordeón (versión 1.1.14).
// =====================================================================
(function () {
  const body = document.body;
  const btn = document.getElementById('toggleSidebar');
  const sidebar = document.getElementById('sidebar');

  // Versión 1.1.14: en las pantallas que más espacio necesitan (el POS y la recepción, que
  // se marcan con data-pantalla-ancha) el menú lateral empieza RECOGIDO (solo íconos).
  // Si allá lo abren con ☰, se recuerda aparte ('sidebar-pos'), sin cambiar lo que se
  // escogió para las demás páginas.
  const enPos = !!document.querySelector('[data-pantalla-ancha]');
  const clave = enPos ? 'sidebar-pos' : 'sidebar-colapsado';
  let guardado = null;
  try { guardado = localStorage.getItem(clave); } catch (e) { /* sin memoria del navegador */ }
  if (enPos ? guardado !== '0' : guardado === '1') body.classList.add('sidebar-colapsado');

  // En el celular (pantalla angosta) el menú siempre es de íconos; ☰ lo abre ENCIMA
  // de la página (clase menu-movil-abierto) y tocar fuera lo cierra.
  const esCelular = () => window.matchMedia('(max-width: 900px)').matches;
  if (btn && sidebar) {
    btn.addEventListener('click', function () {
      if (esCelular()) { body.classList.toggle('menu-movil-abierto'); return; }
      body.classList.toggle('sidebar-colapsado');
      const colapsado = body.classList.contains('sidebar-colapsado');
      try { localStorage.setItem(clave, colapsado ? '1' : '0'); } catch (e) { /* no importa */ }
    });
  }
  document.addEventListener('click', function (e) {
    if (body.classList.contains('menu-movil-abierto') && !e.target.closest('#sidebar') && !e.target.closest('#toggleSidebar')) {
      body.classList.remove('menu-movil-abierto');
    }
  });

  document.querySelectorAll('.sidebar-group').forEach(function (grupo) {
    const contenido = document.querySelector('[data-group-content="' + grupo.dataset.group + '"]');
    if (!contenido) return;

    // Versión 1.1.14 (menú por tareas): un grupo se abre solo si uno está en una de sus
    // páginas (la plantilla le pone "abierto") o si lo tocan. Al abrir uno se cierran los
    // demás ("acordeón"), así el menú nunca queda larguísimo.
    if (grupo.classList.contains('abierto')) contenido.classList.add('abierto');

    grupo.addEventListener('click', function () {
      // Menú recogido (solo íconos) o celular: tocar el ícono del grupo abre el menú
      // completo con ese grupo desplegado.
      if (body.classList.contains('sidebar-colapsado')) {
        body.classList.remove('sidebar-colapsado');
        try { localStorage.setItem(clave, '0'); } catch (e) { /* no importa */ }
      } else if (esCelular() && !body.classList.contains('menu-movil-abierto')) {
        body.classList.add('menu-movil-abierto');
      }
      const abrir = !contenido.classList.contains('abierto') || !grupo.classList.contains('abierto');
      document.querySelectorAll('.sidebar-group').forEach(function (otro) {
        const suyo = document.querySelector('[data-group-content="' + otro.dataset.group + '"]');
        const este = otro === grupo;
        otro.classList.toggle('abierto', este && abrir);
        if (suyo) suyo.classList.toggle('abierto', este && abrir);
      });
    });
  });
})();
