// =====================================================================
// DEVOLUCIÓN DE UN CLIENTE: suma en vivo lo que se le devuelve
// (versión 1.1.14: archivo propio; antes estaba escrito dentro de la página)
// ---------------------------------------------------------------------
// Sirve para el formulario de Devoluciones → Cliente y para el que sale en el
// panel de la pantalla Ventas. Como ese panel llega DESPUÉS (lo trae ventas.js),
// se escucha en todo el documento ("delegación"): cualquier .dev-form que exista.
// Valor de cada fila = cantidad que devuelve × lo que pagó por unidad (data-valor).
// =====================================================================
(function () {
  'use strict';
  const peso = (n) => '$' + Math.round(n).toLocaleString('es-CO');

  function sumar(form) {
    let total = 0;
    form.querySelectorAll('tbody tr').forEach((fila) => {
      const input = fila.querySelector('.dev-cant');
      const valor = input ? (parseFloat(input.value) || 0) * parseFloat(fila.dataset.valor) : 0;
      const celda = fila.querySelector('.dev-valor');
      if (celda) celda.textContent = peso(valor);
      total += valor;
    });
    const celdaTotal = form.querySelector('.dev-total');
    if (celdaTotal) celdaTotal.textContent = peso(total);
  }

  document.addEventListener('input', (e) => {
    const form = e.target.closest && e.target.closest('.dev-form');
    if (form) sumar(form);
  });
})();
