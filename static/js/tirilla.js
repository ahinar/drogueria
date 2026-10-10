/* =====================================================================
   TIRILLA (comprobante y recibo): le dice a la impresora el tamaño
   exacto del papel = ancho del rollo (58 u 80 mm) x largo de lo impreso.

   ¿Por qué con JavaScript? En CSS, "@page { size: ... }" necesita el
   ancho Y el largo en milímetros, y el largo depende de cuántos productos
   tenga la venta. Aquí medimos lo que ocupa la tirilla y lo calculamos.
   ===================================================================== */
(function () {
  'use strict';
  const MM_POR_PX = 25.4 / 96;           // en pantalla 1 pulgada = 96 px = 25,4 mm

  function ajustarPapel() {
    const html = document.documentElement;
    const ancho = html.classList.contains('papel-58') ? 58 : 80;
    // Alto de lo que se imprime (sin la barra de botones, que no sale en papel)
    const barra = document.querySelector('.barra');
    const altoPx = document.body.scrollHeight - (barra ? barra.offsetHeight : 0);
    const altoMm = Math.ceil(altoPx * MM_POR_PX) + 8;   // + 8 mm de margen para cortar
    let estilo = document.getElementById('tamano-papel');
    if (!estilo) {
      estilo = document.createElement('style');
      estilo.id = 'tamano-papel';
      document.head.appendChild(estilo);
    }
    estilo.textContent = '@page { size: ' + ancho + 'mm ' + altoMm + 'mm; margin: 0; }';
  }

  // Al cargar (cuando ya están el logo y las letras) y justo antes de imprimir
  window.addEventListener('load', ajustarPapel);
  window.addEventListener('beforeprint', ajustarPapel);
})();
