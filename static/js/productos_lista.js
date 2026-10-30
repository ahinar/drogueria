// =====================================================================
// LISTA DE PRODUCTOS: mosaico/lista, selección y acciones en grupo — productos/lista.html
// Versión 1.1.15: antes estaba escrito dentro de la página; ahora tiene su archivo.
// =====================================================================
// Barra de acciones sobre varios productos (ver productos.masivo en app/productos.py)
(function () {
  const barra = document.getElementById('form-masivo');
  const casillas = () => [...document.querySelectorAll('.marca-producto')];
  const todos = document.getElementById('marcar-todos');
  const accion = document.getElementById('masivo-accion');
  function contar() {
    const n = casillas().filter((c) => c.checked).length;
    barra.hidden = n === 0;
    document.getElementById('masivo-cuantos').textContent = n + (n === 1 ? ' marcado' : ' marcados');
    todos.checked = n > 0 && n === casillas().length;
    todos.indeterminate = n > 0 && n < casillas().length;
  }
  document.addEventListener('change', (e) => { if (e.target.classList.contains('marca-producto')) contar(); });
  todos.addEventListener('change', () => { casillas().forEach((c) => { c.checked = todos.checked; }); contar(); });
  document.getElementById('masivo-limpiar').addEventListener('click', () => {
    casillas().forEach((c) => { c.checked = false; }); contar();
  });
  // Mostrar solo el segundo menú que corresponde (categoría, laboratorio o IVA)
  accion.addEventListener('change', () => {
    document.querySelectorAll('.masivo-valor').forEach((s) => {
      const usar = s.dataset.para === accion.value;
      s.hidden = !usar; s.disabled = !usar;
    });
  });
  // Si el encabezado ya no se ve (bajaste por la lista), la barra flota arriba
  const encabezado = document.querySelector('.lista-header');
  if (window.IntersectionObserver && encabezado) {
    new IntersectionObserver((entradas) => {
      barra.classList.toggle('flotante', !entradas[0].isIntersecting);
    }).observe(encabezado);
  }
  // Eliminar y desactivar piden confirmación
  barra.addEventListener('submit', async (e) => {
    if (!accion.value) { e.preventDefault(); window.avisar('Escoge qué hacer con los productos marcados.', 'error'); return; }
    if (accion.value === 'exportar') return;                 // descarga el Excel
    const n = casillas().filter((c) => c.checked).length;
    if (accion.value === 'eliminar' || accion.value === 'desactivar') {
      e.preventDefault();
      const texto = accion.value === 'eliminar'
        ? '¿Eliminar ' + n + ' producto(s)? Los que ya tienen ventas, lotes o recepciones no se borran.'
        : '¿Desactivar ' + n + ' producto(s)? No saldrán en el POS.';
      if (await window.confirmar(texto)) barra.submit();
    }
  });
})();
