// =====================================================================
// R6 · SUGERIDO DE COMPRA (pantalla /reportes/sugerido)
// =====================================================================
// 1. Pestañas: Pedido / Se agota / Bajo mínimo / Sin rotación.
// 2. Al cambiar una cantidad, recalcula el subtotal y el total del proveedor.
// 3. "WhatsApp": arma el texto del pedido y abre WhatsApp con ese mensaje.
// 4. "Imprimir": imprime SOLO la tarjeta de ese proveedor.
// Nada de esto guarda en la base de datos: el pedido se arma en la pantalla.
// =====================================================================
(function () {
  'use strict';

  const peso = (n) => '$' + Math.round(n).toLocaleString('es-CO');

  // ---------- 1. Pestañas ----------
  document.querySelectorAll('.sug-pestanas button').forEach((boton) => {
    boton.addEventListener('click', () => {
      document.querySelectorAll('.sug-pestanas button').forEach((b) => b.classList.remove('activa'));
      document.querySelectorAll('.sug-panel').forEach((p) => p.classList.remove('activo'));
      boton.classList.add('activa');
      document.querySelector('.sug-panel[data-panel="' + boton.dataset.pestana + '"]').classList.add('activo');
    });
  });

  // ---------- 2. Recalcular al cambiar una cantidad ----------
  function recalcular(tarjeta) {
    let total = 0;
    tarjeta.querySelectorAll('tbody tr').forEach((fila) => {
      const cantidad = Math.max(0, parseInt(fila.querySelector('.sug-cantidad').value, 10) || 0);
      const subtotal = cantidad * (parseFloat(fila.dataset.costo) || 0);
      fila.querySelector('.sug-subtotal').textContent = peso(subtotal);
      fila.classList.toggle('sug-quitado', cantidad === 0);   // en 0 = no se pide (se ve tachado)
      total += subtotal;
    });
    tarjeta.querySelector('.sug-total').textContent = peso(total);
  }

  document.querySelectorAll('.sug-proveedor').forEach((tarjeta) => {
    tarjeta.addEventListener('input', (e) => {
      if (e.target.classList.contains('sug-cantidad')) recalcular(tarjeta);
    });

    // ---------- 3. WhatsApp ----------
    // Mensaje de ejemplo:
    //   Buenos días, DISTRIBUIDORA EJEMPLO. Pedido de Fervifarma:
    //   • 35 Tableta - ACETAMINOFEN 500 MG TABLETA
    //   • 10 Unidad - SUERO ORAL X 500 ML
    //   Gracias.
    tarjeta.querySelector('.sug-whatsapp').addEventListener('click', () => {
      const lineas = [];
      tarjeta.querySelectorAll('tbody tr').forEach((fila) => {
        const cantidad = parseInt(fila.querySelector('.sug-cantidad').value, 10) || 0;
        if (cantidad > 0) lineas.push('• ' + cantidad + ' ' + fila.dataset.unidad + ' - ' + fila.dataset.nombre);
      });
      if (!lineas.length) { window.avisar('Todas las cantidades están en 0: no hay nada que pedir.', 'error'); return; }
      const texto = 'Buenos días, ' + tarjeta.dataset.proveedor + '. Pedido de ' + tarjeta.dataset.negocio + ':\n' +
        lineas.join('\n') + '\nGracias.';
      // wa.me/<número>?text=... abre el chat de ese número; sin número, WhatsApp deja elegir el contacto
      const numero = tarjeta.dataset.whatsapp || '';
      window.open('https://wa.me/' + numero + '?text=' + encodeURIComponent(texto), '_blank');
    });

    // ---------- 4. Imprimir solo este proveedor ----------
    // Se marca la tarjeta con una clase; el CSS de impresión oculta todo lo demás.
    tarjeta.querySelector('.sug-imprimir').addEventListener('click', () => {
      document.body.classList.add('imprimiendo-pedido');
      tarjeta.classList.add('a-imprimir');
      window.print();
      tarjeta.classList.remove('a-imprimir');
      document.body.classList.remove('imprimiendo-pedido');
    });
  });
})();
