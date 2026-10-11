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

/* ---------------------------------------------------------------------
   BOTÓN "VOLVER" DE LA TIRILLA
   El POS abre el comprobante en una ventana (pestaña) NUEVA. Si "Volver"
   abriera el POS otra vez, quedarían dos POS abiertos. Por eso:
     - si esta ventana la abrió el POS -> se CIERRA y queda el POS de antes
     - si se llegó aquí de otra forma (ej. desde Ventas) -> se va a la dirección del enlace
   Uso en el HTML: <a href="/pos/" onclick="return volverDeTirilla(event)">
   --------------------------------------------------------------------- */
function volverDeTirilla(e) {
  if (window.opener && !window.opener.closed) {
    e.preventDefault();
    try { window.opener.focus(); } catch (err) { /* otro origen: no importa */ }
    window.close();
    return false;
  }
  // No se sabe qué ventana la abrió, pero si es una pestaña recién abierta
  // (sin páginas anteriores) se intenta cerrar igual: el POS sigue en la otra.
  // Si el navegador no deja cerrarla, a los 300 ms se sigue el enlace normal.
  if (window.history.length <= 1) {
    e.preventDefault();
    const destino = e.currentTarget.href;
    window.close();
    setTimeout(function () { window.location.href = destino; }, 300);
    return false;
  }
  return true;          // se llegó desde otra página (ej. Ventas): el enlace funciona normal
}

/* Abrir algo en la ventana del programa (la que abrió esta tirilla) y cerrar
   esta. Así "Vender" de una cotización no deja dos POS abiertos.
   Uso: <a href="/pos/?cotizacion=3" onclick="return irALaVentanaPrincipal(event, this.href)"> */
function irALaVentanaPrincipal(e, url) {
  if (window.opener && !window.opener.closed) {
    e.preventDefault();
    try { window.opener.location.href = url; window.opener.focus(); } catch (err) { window.location.href = url; return false; }
    window.close();
    return false;
  }
  return true;
}
