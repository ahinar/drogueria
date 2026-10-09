// POS - Bloque 1 + Menú lateral + Ingresos/Salidas + Cierre modal
(function () {
  'use strict';

  // ============================================================
  // MENÚ LATERAL DERECHO
  // ============================================================
    const drawer = document.getElementById('pos-drawer');
  const btnMenu = document.getElementById('btn-menu-pos');
  const btnMenuCerrar = document.getElementById('btn-menu-cerrar');

  function abrirDrawer() { if (drawer) drawer.removeAttribute('hidden'); }
  function cerrarDrawer() { if (drawer) drawer.setAttribute('hidden', ''); }

  if (btnMenu) btnMenu.addEventListener('click', abrirDrawer);
  if (btnMenuCerrar) btnMenuCerrar.addEventListener('click', cerrarDrawer);
  if (drawer) {
    drawer.addEventListener('click', (e) => {
      if (e.target === drawer) cerrarDrawer();
    });
  }

  // ============================================================
  // MODAL CONFIRMACIÓN (reutilizar el global)
  // ============================================================

  // ============================================================
  // MODAL DE MOVIMIENTO (ingreso / salida)
  // ============================================================
  const modalMov = document.getElementById('modal-movimiento');
  const movTitulo = document.getElementById('mov-titulo');
  const movTipo = document.getElementById('mov-tipo');
  const movFormaPago = document.getElementById('mov-forma-pago');
  const movMonto = document.getElementById('mov-monto');
  const movMotivo = document.getElementById('mov-motivo');
  const movError = document.getElementById('mov-error');
  const movCancelar = document.getElementById('mov-cancelar');
  const movGuardar = document.getElementById('mov-guardar');

  function abrirModalMovimiento(tipo) {
    if (!modalMov) return;
    movTipo.value = tipo;
    movTitulo.textContent = tipo === 'ingreso' ? '💵 Ingreso de efectivo' : '💸 Salida de efectivo';
    // La salida es para MOVER plata, no para pagar cosas (eso es un gasto).
    // Mostramos la aclaración y ejemplos distintos según el tipo.
    const ayuda = document.getElementById('mov-ayuda');
    if (ayuda) ayuda.hidden = tipo !== 'salida';
    movMotivo.placeholder = tipo === 'ingreso'
      ? 'Ej: base adicional, cambio de billetes, devolución de un préstamo…'
      : 'Ej: consignación en el banco, paso a caja menor, cambio de billetes…';
    movFormaPago.value = 'efectivo';
    movMonto.value = '';
    movMotivo.value = '';
    movError.style.display = 'none';
    modalMov.classList.remove('modal-oculto');
    setTimeout(() => movMonto.focus(), 50);
  }

  function cerrarModalMovimiento() {
    if (modalMov) modalMov.classList.add('modal-oculto');
  }

  if (movCancelar) movCancelar.addEventListener('click', cerrarModalMovimiento);
  // Botón "Es un pago → registrar gasto": cierra esta ventana y abre la de gasto
  const irGasto = document.getElementById('mov-ir-gasto');
  if (irGasto) {
    irGasto.addEventListener('click', () => {
      cerrarModalMovimiento();
      const item = document.querySelector('.pos-drawer-item[data-accion="registrar-gasto"]');
      if (item) item.click();
    });
  }
  if (modalMov) {
    modalMov.addEventListener('click', (e) => {
      if (e.target === modalMov) cerrarModalMovimiento();
    });
  }

  if (movGuardar) {
    movGuardar.addEventListener('click', async () => {
      const monto = parseFloat(movMonto.value) || 0;
      if (monto <= 0) {
        movError.textContent = 'El monto debe ser mayor a cero.';
        movError.style.display = 'block';
        return;
      }
      const datos = new FormData();
      datos.append('_csrf', document.querySelector('input[name="_csrf"]')?.value || '');
      datos.append('tipo', movTipo.value);
      datos.append('forma_pago', movFormaPago.value);
      datos.append('monto', monto);
      datos.append('motivo', movMotivo.value);

      const url = document.getElementById('url-api-movimiento').value;
      movGuardar.disabled = true;
      movGuardar.textContent = 'Guardando…';
      try {
        const resp = await fetch(url, { method: 'POST', body: datos, credentials: 'same-origin' });
        const json = await resp.json();
        if (!json.ok) {
          movError.textContent = json.error || 'No se pudo guardar.';
          movError.style.display = 'block';
          return;
        }
        cerrarModalMovimiento();
        // Recargar para reflejar en el cierre
        window.location.reload();
      } catch (e) {
        movError.textContent = 'Error de conexión: ' + e.message;
        movError.style.display = 'block';
      } finally {
        movGuardar.disabled = false;
        movGuardar.textContent = 'Guardar';
      }
    });
  }

  // ============================================================
  // MODAL DE CIERRE DE CAJA
  // ============================================================
  const modalCierre = document.getElementById('modal-cierre-caja');
  const cierreDescartar = document.getElementById('cierre-descartar');
  const cierreConfirmar = document.getElementById('cierre-confirmar');
  const cierreError = document.getElementById('cierre-error');
  const cierreContadoInput = document.getElementById('cierre-efectivo-contado');
  const btnContarCierre = document.getElementById('btn-contar-cierre-modal');
  const cierreObservaciones = document.getElementById('cierre-observaciones');

  let cierreContadoValor = 0; // valor numérico del conteo
  let cierreEsperado = 0;

  const formatoCOP = (n) => '$ ' + Number(n || 0).toLocaleString('es-CO', { maximumFractionDigits: 0 });

  async function abrirModalCierre() {
    if (!modalCierre) return;
    cierreError.style.display = 'none';
    cierreContadoValor = 0;
    cierreContadoInput.value = '$ 0';
    cierreObservaciones.value = '';

    // Cargar resumen desde el servidor
    const urlResumen = document.getElementById('url-api-resumen').value;
    try {
      const resp = await fetch(urlResumen, { credentials: 'same-origin' });
      const json = await resp.json();
      if (!json.ok) {
        cierreError.textContent = json.error || 'No se pudo cargar el resumen.';
        cierreError.style.display = 'block';
        return;
      }
      const r = json.resumen;
      // Totales
      document.getElementById('cierre-n-ordenes').textContent = r.n_ventas + ' órdenes · ' + formatoCOP(r.total_ventas);

      // Efectivo
      document.getElementById('cierre-efectivo-apertura').textContent = formatoCOP(r.efectivo.inicial);
      document.getElementById('cierre-efectivo-ventas').textContent = formatoCOP(r.efectivo.ventas);
      document.getElementById('cierre-efectivo-ingresos').textContent = '+ ' + formatoCOP(r.efectivo.ingresos);
      document.getElementById('cierre-efectivo-salidas').textContent = '− ' + formatoCOP(r.efectivo.salidas);
      document.getElementById('cierre-efectivo-esperado').textContent = formatoCOP(r.efectivo.esperado);
      document.getElementById('cierre-efectivo-total').textContent = formatoCOP(r.efectivo.esperado);
      cierreEsperado = r.efectivo.esperado;

      // Nequi
      const totalNequi = r.nequi.ventas + r.nequi.ingresos - r.nequi.salidas;
      document.getElementById('cierre-nequi-ventas').textContent = formatoCOP(r.nequi.ventas);
      document.getElementById('cierre-nequi-ingresos').textContent = '+ ' + formatoCOP(r.nequi.ingresos);
      document.getElementById('cierre-nequi-salidas').textContent = '− ' + formatoCOP(r.nequi.salidas);
      document.getElementById('cierre-nequi-total').textContent = formatoCOP(totalNequi);

      // Davivienda
      const totalDavi = r.davivienda.ventas + r.davivienda.ingresos - r.davivienda.salidas;
      document.getElementById('cierre-davivienda-ventas').textContent = formatoCOP(r.davivienda.ventas);
      document.getElementById('cierre-davivienda-ingresos').textContent = '+ ' + formatoCOP(r.davivienda.ingresos);
      document.getElementById('cierre-davivienda-salidas').textContent = '− ' + formatoCOP(r.davivienda.salidas);
      document.getElementById('cierre-davivienda-total').textContent = formatoCOP(totalDavi);

      // Tarjeta
      document.getElementById('cierre-tarjeta-ventas').textContent = formatoCOP(r.tarjeta.ventas);
      document.getElementById('cierre-tarjeta-total').textContent = formatoCOP(r.tarjeta.ventas);

      actualizarDiferencia();

      modalCierre.classList.remove('modal-oculto');
    } catch (e) {
      cierreError.textContent = 'Error de conexión: ' + e.message;
      cierreError.style.display = 'block';
    }
  }

  function actualizarDiferencia() {
    const dif = cierreContadoValor - cierreEsperado;
    const el = document.getElementById('cierre-efectivo-diferencia');
    el.textContent = formatoCOP(dif);
    el.style.color = Math.abs(dif) < 0.01 ? '#0d6b3d' : '#b3261e';
  }

  function cerrarModalCierre() {
    if (modalCierre) modalCierre.classList.add('modal-oculto');
  }

  if (cierreDescartar) cierreDescartar.addEventListener('click', cerrarModalCierre);
  if (modalCierre) {
    modalCierre.addEventListener('click', (e) => {
      if (e.target === modalCierre) cerrarModalCierre();
    });
  }

  if (btnContarCierre) {
    btnContarCierre.addEventListener('click', () => {
      // Abrir modal de conteo
      document.querySelectorAll('#modal-conteo .conteo-input').forEach(i => i.value = 0);
      document.getElementById('conteo-total-valor').textContent = '$ 0';
      document.getElementById('modal-conteo').classList.remove('modal-oculto');
    });
  }

  // Botón cerrar caja definitivo
  if (cierreConfirmar) {
    cierreConfirmar.addEventListener('click', async () => {
      if (!cierreContadoValor && cierreEsperado > 0) {
        const ok = await window.confirmar(
          'El efectivo contado es $0 y el esperado es ' + formatoCOP(cierreEsperado) + '. ¿Continuar de todas formas?',
          { titulo: 'Cierre con diferencia', icono: '⚠️', textoAceptar: 'Sí, cerrar', tipo: 'peligro' }
        );
        if (!ok) return;
      }

      const datos = new FormData();
      datos.append('_csrf', document.querySelector('input[name="_csrf"]')?.value || '');
      datos.append('efectivo_contado', cierreContadoValor);
      datos.append('observaciones_cierre', cierreObservaciones.value);

      const url = document.getElementById('url-api-cerrar').value;
      cierreConfirmar.disabled = true;
      cierreConfirmar.textContent = 'Cerrando…';
      try {
        const resp = await fetch(url, { method: 'POST', body: datos, credentials: 'same-origin' });
        const json = await resp.json();
        if (!json.ok) {
          cierreError.textContent = json.error || 'No se pudo cerrar.';
          cierreError.style.display = 'block';
          return;
        }
        // Redirigir a la confirmación
        const urlConfirm = document.getElementById('url-cierre-confirmacion').value.replace('/0', '/' + json.caja_id);
        window.location.href = urlConfirm;
      } catch (e) {
        cierreError.textContent = 'Error de conexión: ' + e.message;
        cierreError.style.display = 'block';
      } finally {
        cierreConfirmar.disabled = false;
        cierreConfirmar.textContent = '🔒 Cerrar caja registradora';
      }
    });
  }

  // ============================================================
  // MODAL DE CONTEO (reutilizado)
  // ============================================================
  const modalConteo = document.getElementById('modal-conteo');
  const conteoTotalSpan = document.getElementById('conteo-total-valor');
  const conteoConfirmar = document.getElementById('conteo-confirmar');
  const conteoCancelar = document.getElementById('conteo-cancelar');

  function calcularTotalConteo() {
    let total = 0;
    document.querySelectorAll('#modal-conteo .conteo-fila').forEach((fila) => {
      const valor = parseInt(fila.dataset.valor, 10);
      const cant = parseInt(fila.querySelector('.conteo-input').value, 10) || 0;
      if (cant > 0) total += valor * cant;
    });
    conteoTotalSpan.textContent = '$ ' + total.toLocaleString('es-CO');
    return total;
  }

  if (modalConteo) {
    modalConteo.addEventListener('click', (e) => {
      if (e.target.classList.contains('conteo-btn')) {
        const fila = e.target.closest('.conteo-fila');
        const input = fila.querySelector('.conteo-input');
        let v = parseInt(input.value, 10) || 0;
        if (e.target.textContent === '+') v += 1;
        else v = Math.max(0, v - 1);
        input.value = v;
        calcularTotalConteo();
      }
    });

    modalConteo.addEventListener('input', (e) => {
      if (e.target.classList.contains('conteo-input')) calcularTotalConteo();
    });
  }

  if (conteoConfirmar) {
    conteoConfirmar.addEventListener('click', () => {
      cierreContadoValor = calcularTotalConteo();
      cierreContadoInput.value = formatoCOP(cierreContadoValor);
      actualizarDiferencia();
      modalConteo.classList.add('modal-oculto');
    });
  }
  if (conteoCancelar) {
    conteoCancelar.addEventListener('click', () => modalConteo.classList.add('modal-oculto'));
  }

  // ============================================================
  // ACCIONES DEL MENÚ LATERAL
  // ============================================================
  document.querySelectorAll('.pos-drawer-item').forEach((btn) => {
    btn.addEventListener('click', () => {
      const accion = btn.dataset.accion;
      cerrarDrawer();

      switch (accion) {
        case 'cerrar-caja':
          abrirModalCierre();
          break;
        case 'ingreso-efectivo':
          abrirModalMovimiento('ingreso');
          break;
        case 'salida-efectivo':
          abrirModalMovimiento('salida');
          break;
        // Las demás acciones (últimas ventas, cliente, nota, reimprimir,
        // inventario y registrar gasto) las maneja pos_carrito.js.
        // Antes aquí salían avisos de "Próximamente" que estorbaban.
      }
    });
  });

  console.log('POS cargado.');
})();