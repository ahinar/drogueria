// =====================================================================
// BUSCAR EL KARDEX DE UN PRODUCTO — inventario/kardex_buscar.html
// Versión 1.1.15: antes estaba escrito dentro de la página; ahora tiene su archivo.
// =====================================================================
(function () {
  const input = document.getElementById('buscar-kardex');
  const panel = document.getElementById('resultados-kardex');
  let timeout = null;

  function ocultar() {
    panel.classList.add('panel-resultados-oculto');
    panel.innerHTML = '';
  }

  function mostrar(resultados) {
    if (!resultados.length) { ocultar(); return; }
    panel.innerHTML = resultados.map(function (p) {
      return '<div class="resultado-item" data-id="' + p.id + '">'
        + '<div class="resultado-codigo">' + p.codigo + '</div>'
        + '<div class="resultado-info"><div class="resultado-nombre">' + p.nombre
        + (p.concentracion ? ' ' + p.concentracion : '') + '</div>'
        + '<div class="resultado-detalle">' + (p.unidad || '') + '</div></div>'
        + window.chipLaboratorio(p.laboratorio) + '</div>';
    }).join('');
    const r = input.getBoundingClientRect();
    panel.style.position = 'absolute';
    panel.style.top = (r.bottom + window.scrollY + 2) + 'px';
    panel.style.left = (r.left + window.scrollX) + 'px';
    panel.style.width = Math.max(r.width, 500) + 'px';
    panel.classList.remove('panel-resultados-oculto');
    panel.classList.add('panel-resultados');
  }

  input.addEventListener('input', function () {
    const q = input.value.trim();
    if (q.length < 3) { ocultar(); return; }
    clearTimeout(timeout);
    timeout = setTimeout(async function () {
      try {
        const resp = await fetch('/recepciones/api/buscar-productos?q=' + encodeURIComponent(q));
        const json = await resp.json();
        if (json.ok) mostrar(json.resultados);
      } catch (e) {}
    }, 220);
  });

  panel.addEventListener('click', function (e) {
    const item = e.target.closest('.resultado-item');
    if (!item) return;
    window.location.href = '/inventario/kardex/' + item.dataset.id;
  });

  document.addEventListener('click', function (e) {
    if (!panel.contains(e.target) && e.target !== input) ocultar();
  });
})();
