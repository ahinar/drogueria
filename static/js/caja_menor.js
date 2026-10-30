// =====================================================================
// CAJA MENOR — caja_menor/index.html
// Versión 1.1.15: antes estaba escrito dentro de la página; ahora tiene su archivo.
// =====================================================================
(function () {
  // Abrir modales
  document.querySelectorAll('[data-modal]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const modal = document.getElementById('modal-cm-' + btn.dataset.modal);
      if (modal) {
        modal.classList.remove('modal-oculto');
        // El cursor queda listo en "Monto" para escribir de una vez
        const monto = modal.querySelector('input[name="monto"]');
        if (monto) setTimeout(function () { monto.focus(); }, 50);
      }
    });
  });

  // Cerrar modales con el botón Cancelar
  document.querySelectorAll('[data-cerrar-modal]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const modal = btn.closest('[id^="modal-cm-"]');
      if (modal) modal.classList.add('modal-oculto');
    });
  });

  // Cerrar modal al hacer clic fuera de la caja
  ['modal-cm-aporte', 'modal-cm-retiro'].forEach(function (id) {
    const m = document.getElementById(id);
    if (!m) return;
    m.addEventListener('click', function (e) {
      if (e.target === m) m.classList.add('modal-oculto');
    });
  });
})();
