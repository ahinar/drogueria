// =====================================================================
// CAMBIAR LA UNIDAD DEL INVENTARIO DE UN PRODUCTO — productos/cambiar_unidad.html
// Versión 1.1.15: antes estaba escrito dentro de la página; ahora tiene su archivo.
// Los datos del servidor llegan en un bloque <script type="application/json">.
// =====================================================================
// Muestra la parte de "Convertir" solo si se escoge esa opción, y calcula
// el resumen: "300 Caja x 100 → 30.000 Tableta; precio $250 → $3".
(function () {
  const form = document.getElementById('form-unidad');
  const bloque = document.getElementById('bloque-convertir');
  const selNueva = document.getElementById('unidad-nueva');
  const factor = document.getElementById('factor');
  const precio = document.getElementById('precio');
  const resumen = document.getElementById('resumen-conversion');
  const DATOS = JSON.parse(document.getElementById('cambiar-unidad-datos').textContent);
  const existencias = DATOS.existencias;
  const precioViejo = DATOS.precio_viejo;
  const actual = DATOS.actual;

  function nombreNueva() {
    const o = selNueva.options[selNueva.selectedIndex];
    return o && o.value ? o.textContent.trim() : 'unidad nueva';
  }
  function pintar() {
    const convertir = form.modo.value === 'convertir';
    bloque.hidden = !convertir;
    factor.required = convertir;
    document.querySelectorAll('.nombre-nueva').forEach((s) => { s.textContent = nombreNueva(); });
    const n = parseFloat((factor.value || '').replace(',', '.'));
    if (convertir && n >= 1) {
      precio.placeholder = 'Sugerido: $' + Math.round(precioViejo / n).toLocaleString('es-CO');
      resumen.textContent = existencias.toLocaleString('es-CO') + ' ' + actual + ' → ' +
        (existencias * n).toLocaleString('es-CO') + ' ' + nombreNueva() + '.';
      resumen.hidden = false;
    } else {
      resumen.textContent = '';
      resumen.hidden = true;
    }
  }
  form.addEventListener('change', pintar);
  form.addEventListener('input', pintar);
  pintar();
})();
