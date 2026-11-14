// =====================================================================
// TABLAS COMPACTAS EN TODO EL PROGRAMA (versión 1.1.19, pedido de Fernando)
// ---------------------------------------------------------------------
// Lo que pidió: «que las líneas no estén tan separadas (letra 12, celda 15), todo en
// un solo renglón, filas de dos colores, y poder cambiar el ancho de las columnas
// porque algunas son muy grandes para lo que tienen (ej. la temperatura)».
//
// QUÉ HACE ESTE ARCHIVO con cada tabla de listas y reportes:
//   1. Le pone la clase "compacta" → los estilos están en app.css («TABLAS COMPACTAS»):
//      letra 12, celda de 15, un solo renglón, cebra (una fila blanca y una verde clarito).
//   2. Lo que iba en un segundo renglón (con <br>) queda en el mismo, separado por « · ».
//      Ej.: «P00001» <br> «ACETAMINOFEN» → «P00001 · ACETAMINOFEN».
//   3. La columna principal (Producto, Nombre, Cliente...) se queda con el espacio que
//      sobra; las demás (Temp., Lote, Vence...) miden solo lo que necesitan.
//   4. CAMBIAR EL ANCHO A MANO: arrastrar el borde derecho del título de una columna.
//      El programa lo recuerda EN ESTE COMPUTADOR para esa pantalla (localStorage).
//      Doble clic en ese borde → la columna vuelve a su tamaño automático.
//   5. Si la tabla no cabe a lo ancho (celular), se desliza de lado dentro de su caja.
//
// QUÉ NO TOCA: la tabla donde se RECIBE la mercancía (ahí van el registro sanitario y
// demás debajo del producto), las tablas con casillas para escribir de la ventana de
// editar producto, y cualquier tabla con la clase "no-compactar".
// =====================================================================
(function () {
  'use strict';
  const TABLAS = 'table.tabla, table.rep-tabla, table.sug-tabla, table.eres-tabla, table.tabla-compacta, table.dash-tabla';
  // (la planilla de limpieza es una cuadrícula de días: tiene su propio diseño)
  const EXCLUIDAS = '.tabla-recepcion, .editar-pres-tabla, .san-planilla, .no-compactar';
  // Títulos de columna que suelen ser la «principal» (la que se queda con el espacio)
  const PRINCIPAL = /^(producto|nombre|descripci|concepto|cliente|proveedor|detalle|art[ií]culo|tarea|documento|equipo|motivo)/i;

  // ---------- 2. Un solo renglón: <br> → « · » ----------
  function unRenglon(raiz) {
    raiz.querySelectorAll('td br, th br').forEach((br) => {
      // Si después del <br> no hay nada (o solo espacios), se quita sin poner « · »
      let sig = br.nextSibling;
      while (sig && sig.nodeType === 3 && !sig.textContent.trim()) sig = sig.nextSibling;
      let ant = br.previousSibling;
      while (ant && ant.nodeType === 3 && !ant.textContent.trim()) ant = ant.previousSibling;
      // (si sigue un <small>, el CSS ya le pone su « · » adelante: no se repite)
      if (!sig || !ant || sig.nodeName === 'BR' || sig.nodeName === 'SMALL') br.remove();
      else br.replaceWith(document.createTextNode(' · '));
    });
  }

  // Celdas de la columna número «i» (sin contar filas con celdas unidas, que no cuadran)
  function celdasDeColumna(tabla, i) {
    const cols = tabla.tHead && tabla.tHead.rows[0] ? tabla.tHead.rows[0].cells.length : 0;
    return Array.from(tabla.rows).map((fila) => (fila.cells.length === cols ? fila.cells[i] : null)).filter(Boolean);
  }

  // ---------- 3. La columna principal ----------
  function marcarPrincipal(tabla) {
    if (tabla.querySelector('.col-principal') || !tabla.tHead || !tabla.tHead.rows[0]) return;
    const titulos = Array.from(tabla.tHead.rows[0].cells);
    const i = titulos.findIndex((th) => PRINCIPAL.test(th.textContent.trim()));
    if (i < 0) return;
    celdasDeColumna(tabla, i).forEach((c) => c.classList.add('col-principal'));
  }

  // ---------- 4. Ancho de columnas a mano (recordado en este computador) ----------
  function claveDe(tabla) {
    const todas = Array.from(document.querySelectorAll('table.compacta'));
    return 'anchos:' + location.pathname + ':' + todas.indexOf(tabla);
  }
  function leerAnchos(tabla) {
    try { return JSON.parse(localStorage.getItem(claveDe(tabla)) || '{}'); } catch (e) { return {}; }
  }
  function guardarAnchos(tabla, anchos) {
    try {
      if (Object.keys(anchos).length) localStorage.setItem(claveDe(tabla), JSON.stringify(anchos));
      else localStorage.removeItem(claveDe(tabla));
    } catch (e) { /* navegador sin espacio o en modo privado: solo no se recuerda */ }
  }
  // Ponerle un ancho fijo a la columna «i» (o quitárselo con ancho = null)
  function anchoColumna(tabla, i, ancho) {
    celdasDeColumna(tabla, i).forEach((c) => {
      c.classList.toggle('col-fija', ancho != null);
      c.style.width = c.style.minWidth = c.style.maxWidth = ancho != null ? ancho + 'px' : '';
    });
  }
  function prepararAsas(tabla) {
    if (!tabla.tHead || !tabla.tHead.rows[0]) return;
    const titulos = Array.from(tabla.tHead.rows[0].cells);
    const anchos = leerAnchos(tabla);
    Object.keys(anchos).forEach((i) => anchoColumna(tabla, +i, anchos[i]));
    titulos.forEach((th, i) => {
      if (i === titulos.length - 1 || th.querySelector('.col-asa')) return;   // (la última no hace falta)
      const asa = document.createElement('span');
      asa.className = 'col-asa';
      asa.title = 'Arrastre para cambiar el ancho · doble clic: automático';
      th.appendChild(asa);
      asa.addEventListener('mousedown', (e) => {
        e.preventDefault();
        const inicioX = e.clientX;
        const inicioAncho = th.getBoundingClientRect().width;
        document.body.classList.add('arrastrando-columna');
        function mover(ev) {
          const ancho = Math.max(30, Math.round(inicioAncho + ev.clientX - inicioX));
          anchoColumna(tabla, i, ancho);
        }
        function soltar() {
          document.removeEventListener('mousemove', mover);
          document.removeEventListener('mouseup', soltar);
          document.body.classList.remove('arrastrando-columna');
          const guardados = leerAnchos(tabla);
          guardados[i] = Math.round(th.getBoundingClientRect().width);
          guardarAnchos(tabla, guardados);
        }
        document.addEventListener('mousemove', mover);
        document.addEventListener('mouseup', soltar);
      });
      asa.addEventListener('dblclick', (e) => {
        e.preventDefault();
        e.stopPropagation();
        anchoColumna(tabla, i, null);
        const guardados = leerAnchos(tabla);
        delete guardados[i];
        guardarAnchos(tabla, guardados);
      });
      asa.addEventListener('click', (e) => e.stopPropagation());   // (no ordenar la tabla al soltar)
    });
  }

  // ---------- 5. Que se deslice de lado si no cabe ----------
  function envolver(tabla) {
    const padre = tabla.parentElement;
    if (!padre || padre.classList.contains('tabla-desliza')) return;
    const estilo = getComputedStyle(padre);
    if (estilo.overflowX === 'auto' || estilo.overflowX === 'scroll') return;   // ya se desliza
    const caja = document.createElement('div');
    caja.className = 'tabla-desliza';
    padre.insertBefore(caja, tabla);
    caja.appendChild(tabla);
  }

  function compactar(tabla) {
    if (tabla.classList.contains('compacta') || tabla.matches(EXCLUIDAS)) return;
    tabla.classList.add('compacta');
    unRenglon(tabla);
    marcarPrincipal(tabla);
    envolver(tabla);
    prepararAsas(tabla);
  }

  function compactarTodo(raiz) {
    (raiz || document).querySelectorAll(TABLAS).forEach(compactar);
  }

  // Al cargar la página, y cuando el programa agrega filas o tablas después (ej. listas
  // que se llenan solas): las filas nuevas también quedan en un renglón.
  function iniciar() {
    compactarTodo(document);
    if (!window.MutationObserver) return;
    let pendiente = null;
    new MutationObserver(() => {
      clearTimeout(pendiente);
      pendiente = setTimeout(() => {
        compactarTodo(document);
        document.querySelectorAll('table.compacta').forEach(unRenglon);
      }, 60);
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();

  window.compactarTablas = compactarTodo;          // por si otra pantalla lo necesita
})();
