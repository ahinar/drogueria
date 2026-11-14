// =====================================================================
// LISTA DE PRODUCTOS (vista Lista) — productos/lista.html
// Versión 1.1.15: antes estaba escrito dentro de la página; ahora tiene su archivo.
// Versión 1.1.19 (pedido de Fernando): ya no hay botones «Editar» y «Desactivar» en
// cada fila. Ahora:
//   - El NOMBRE del producto es un enlace a su ficha, y el DOBLE CLIC en cualquier
//     parte de la fila también la abre.
//   - Se marcan productos con las casillas y arriba, el botón «Acciones (N) ▾»
//     abre un menú con lo que se les puede hacer (lo hace productos.masivo en
//     app/productos.py). «Editar» solo sale cuando hay UN producto marcado.
//   - Categoría, laboratorio e IVA piden un segundo paso: escoger cuál y «Aplicar».
//   - Eliminar y Desactivar piden confirmación.
// =====================================================================
(function () {
  'use strict';
  const form = document.getElementById('form-masivo');
  if (!form) return;                                  // (solo administrador y director técnico)
  const boton = document.getElementById('acciones-boton');
  const menu = document.getElementById('acciones-menu');
  const lista = document.getElementById('acciones-lista');
  const paso2 = document.getElementById('acciones-paso2');
  const accion = document.getElementById('masivo-accion');
  const todos = document.getElementById('marcar-todos');
  const casillas = () => [...document.querySelectorAll('.marca-producto')];
  const marcadas = () => casillas().filter((c) => c.checked);
  const NECESITAN_VALOR = { categoria: 'Agregar a la categoría:', laboratorio: 'Poner el laboratorio:', iva: 'Cambiar el IVA a:' };

  // ---------- Contar los marcados y prender/apagar el botón ----------
  function contar() {
    const n = marcadas().length;
    boton.disabled = n === 0;
    document.getElementById('acciones-n').textContent = n ? '(' + n + ')' : '';
    document.getElementById('masivo-cuantos').textContent = n === 0
      ? 'Marque productos con las casillas para hacerles algo.'
      : n + (n === 1 ? ' producto marcado' : ' productos marcados');
    document.getElementById('masivo-limpiar').hidden = n === 0;
    // «Editar» solo con UNO marcado (con varios no sale, para no recargar el menú)
    menu.querySelectorAll('.solo-uno').forEach((el) => { el.hidden = n !== 1; });
    // La fila marcada se pinta de otro color
    casillas().forEach((c) => c.closest('tr').classList.toggle('marcada', c.checked));
    if (todos) {
      todos.checked = n > 0 && n === casillas().length;
      todos.indeterminate = n > 0 && n < casillas().length;
    }
    if (n === 0) cerrarMenu();
  }
  document.addEventListener('change', (e) => { if (e.target.classList.contains('marca-producto')) contar(); });
  if (todos) todos.addEventListener('change', () => { casillas().forEach((c) => { c.checked = todos.checked; }); contar(); });
  document.getElementById('masivo-limpiar').addEventListener('click', () => {
    casillas().forEach((c) => { c.checked = false; });
    contar();
  });

  // ---------- Abrir y cerrar el menú ----------
  function abrirMenu() {
    menu.hidden = false;
    lista.hidden = false;
    paso2.hidden = true;
    boton.setAttribute('aria-expanded', 'true');
  }
  function cerrarMenu() {
    menu.hidden = true;
    boton.setAttribute('aria-expanded', 'false');
    accion.value = '';
  }
  boton.addEventListener('click', () => { if (menu.hidden) abrirMenu(); else cerrarMenu(); });
  // Clic por fuera del menú, o Esc: se cierra
  document.addEventListener('click', (e) => { if (!menu.hidden && !e.target.closest('.acciones-caja')) cerrarMenu(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) cerrarMenu(); });

  // ---------- Escoger una acción ----------
  lista.addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-accion]');
    if (!b) return;
    const que = b.dataset.accion;
    const n = marcadas().length;
    if (que === 'editar') {                          // ir a la ficha del único marcado
      window.location.href = form.dataset.urlEditar.replace('/0/', '/' + marcadas()[0].value + '/');
      return;
    }
    accion.value = que;
    if (NECESITAN_VALOR[que]) {                      // segundo paso: escoger cuál
      document.getElementById('acciones-paso2-titulo').textContent = NECESITAN_VALOR[que];
      document.querySelectorAll('.masivo-valor').forEach((s) => {
        const usar = s.dataset.para === que;
        s.hidden = !usar;
        s.disabled = !usar;
      });
      lista.hidden = true;
      paso2.hidden = false;
      paso2.querySelector('.masivo-valor:not([hidden])').focus();
      return;
    }
    if (que === 'eliminar' || que === 'desactivar') {
      const texto = que === 'eliminar'
        ? '¿Eliminar ' + n + ' producto(s)? Los que ya tienen ventas, lotes o recepciones no se borran (a esos use Desactivar).'
        : '¿Desactivar ' + n + ' producto(s)? No saldrán en el POS.';
      if (!(await window.confirmar(texto))) { accion.value = ''; return; }
    }
    form.submit();                                   // (exportar descarga el Excel y la página se queda)
    if (que === 'exportar') cerrarMenu();
  });
  document.getElementById('acciones-volver').addEventListener('click', () => {
    accion.value = '';
    paso2.hidden = true;
    lista.hidden = false;
  });

  // ---------- Doble clic en la fila = abrir la ficha ----------
  document.querySelectorAll('.tabla-productos tbody tr[data-url]').forEach((tr) => {
    tr.addEventListener('dblclick', (e) => {
      if (e.target.closest('input, a, button')) return;      // (la casilla no abre nada)
      window.location.href = tr.dataset.url;
    });
  });

  contar();
})();
