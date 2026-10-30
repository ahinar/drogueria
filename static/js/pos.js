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

  // Versión 1.1.14: la abre el botón «Movimiento de plata» (pos_carrito.js), que ya
  // preguntó si entra o sale y para qué. modo:
  //   'dueno'    → sale: plata que se lleva el dueño (no se pregunta a dónde va)
  //   'traslado' → sale: se pasa a la caja menor o se consigna (se pregunta a dónde)
  //   'entra'    → entra efectivo que no es venta ni ingreso (base, cambio): de dónde viene
  const movLugar = document.getElementById('mov-lugar');
  const movLugarWrap = document.getElementById('mov-lugar-wrap');
  const TEXTOS = {
    dueno: ['💸 Plata que se lleva el dueño', 'Queda como «Retiro del dueño»: no es gasto de la droguería. Utilidades lo muestra aparte.'],
    traslado: ['🔁 Pasar plata a otro lado', 'Sale efectivo del cajón y llega a donde usted diga: allá queda registrado también.'],
    entra: ['💵 Entra efectivo a la caja', 'Para base, cambio de billetes o plata que se trae de otro lado. No es ganancia.'],
  };
  function abrirModalMovimiento(tipo, modo) {
    if (!modalMov) return;
    modo = modo || (tipo === 'ingreso' ? 'entra' : 'traslado');
    movTipo.value = tipo;
    movTitulo.textContent = TEXTOS[modo][0];
    document.getElementById('mov-explica').textContent = TEXTOS[modo][1];
    document.getElementById('mov-lugar-texto').textContent =
      tipo === 'ingreso' ? '¿De dónde viene la plata?' : '¿A dónde va la plata?';
    // «El dueño» solo se escoge con su propio botón; en 'entra' sí aparece (aporte del dueño)
    Array.from(movLugar.options).forEach((o) => { o.hidden = modo === 'traslado' && o.value === 'dueno'; });
    movLugarWrap.hidden = modo === 'dueno';
    movLugar.value = modo === 'dueno' ? 'dueno' : 'caja_menor';
    movFormaPago.value = 'efectivo';
    movMonto.value = '';
    movMotivo.value = '';
    movError.style.display = 'none';
    modalMov.classList.remove('modal-oculto');
    setTimeout(() => movMonto.focus(), 50);
  }
  window.abrirMovimiento = abrirModalMovimiento;

  function cerrarModalMovimiento() {
    if (modalMov) modalMov.classList.add('modal-oculto');
  }

  if (movCancelar) movCancelar.addEventListener('click', cerrarModalMovimiento);
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
      datos.append('lugar', movLugar ? movLugar.value : '');   // versión 1.1.14

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

  // ------------------------------------------------------------
  // Versión 1.1.8: EL CONTEO DE EFECTIVO NO SE BORRA
  // Lo contado para cerrar ESTA caja se guarda con el nombre "cierre-<id de la caja>"
  // (ver _modal_conteo.html). Si se cierra la ventana para revisar algo, al volver
  // sigue ahí. Se borra solo cuando la caja se cierra de verdad.
  // ------------------------------------------------------------
  const cajaIdActual = (document.getElementById('pos-caja-id') || {}).value || '';
  const claveCierre = 'cierre-' + cajaIdActual;
  let conteoGuardado = null;
  if (window.conteoEfectivo && cajaIdActual) {
    window.conteoEfectivo.limpiar('apertura');                  // la caja ya está abierta
    window.conteoEfectivo.limpiarViejos('cierre-', claveCierre); // cierres de cajas pasadas
    conteoGuardado = window.conteoEfectivo.usar(claveCierre);
  }

  async function abrirModalCierre() {
    if (!modalCierre) return;
    cierreError.style.display = 'none';
    // Antes aquí el contado volvía a $0. Ahora, si ya se había contado (o escrito) el
    // efectivo, se vuelve a poner: así se puede salir a revisar y volver sin perderlo.
    const previo = window.conteoEfectivo ? window.conteoEfectivo.cargar(claveCierre) : conteoGuardado;
    if (previo && previo.confirmado != null) {
      cierreContadoValor = Number(previo.confirmado) || 0;
      cierreContadoInput.value = formatoCOP(cierreContadoValor);
    } else {
      cierreContadoValor = 0;
      cierreContadoInput.value = '';
    }
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

      // Cuentas: Nequi, Davivienda, Daviplata... (versión 1.1.14). Una sección por cuenta,
      // armada con la lista que manda el servidor, así una cuenta nueva sale sola.
      document.getElementById('cierre-cuentas').innerHTML = (r.cuentas || []).map((c) => {
        const total = c.ventas + c.ingresos - c.salidas;
        return '<div class="cierre-seccion" data-cuenta="' + c.clave + '">' +
          '<div class="cierre-seccion-titulo"><span>' + c.nombre + '</span><strong>' + formatoCOP(total) + '</strong></div>' +
          '<div class="cierre-linea"><span>Ventas del turno</span><strong>' + formatoCOP(c.ventas) + '</strong></div>' +
          '<div class="cierre-linea"><span>Ingresos</span><strong>+ ' + formatoCOP(c.ingresos) + '</strong></div>' +
          '<div class="cierre-linea"><span>Salidas</span><strong>− ' + formatoCOP(c.salidas) + '</strong></div></div>';
      }).join('');

      // Tarjeta
      document.getElementById('cierre-tarjeta-ventas').textContent = formatoCOP(r.tarjeta.ventas);
      document.getElementById('cierre-tarjeta-total').textContent = formatoCOP(r.tarjeta.ventas);
      // Ventas a crédito: solo se muestran si hubo (no se cuentan en el arqueo)
      const credito = (r.credito && r.credito.ventas) || 0;
      const secCredito = document.getElementById('cierre-credito-seccion');
      if (secCredito) {
        secCredito.hidden = !credito;
        document.getElementById('cierre-credito-total').textContent = formatoCOP(credito);
      }

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

  // EFECTIVO CONTADO ESCRITO A MANO: si ya tienes la plata contada, escribes
  // el total de una vez (ej. 1.250.000). Se toman solo los dígitos: los puntos
  // de miles y el signo $ no importan. La diferencia se recalcula al escribir.
  function leerContado() {
    const digitos = (cierreContadoInput.value || '').replace(/[^0-9]/g, '');
    cierreContadoValor = digitos ? parseInt(digitos, 10) : 0;
    actualizarDiferencia();
    // Versión 1.1.8: lo escrito a mano también se guarda (null = no ha escrito nada)
    if (window.conteoEfectivo) window.conteoEfectivo.guardar({ confirmado: digitos ? cierreContadoValor : null });
  }
  if (cierreContadoInput) {
    cierreContadoInput.addEventListener('input', leerContado);
    // Al salir del campo se muestra bonito: $ 1.250.000
    cierreContadoInput.addEventListener('blur', () => {
      if (cierreContadoInput.value.trim()) cierreContadoInput.value = formatoCOP(cierreContadoValor);
    });
    // Al entrar, se deja solo el número para corregirlo fácil
    cierreContadoInput.addEventListener('focus', () => {
      if (cierreContadoValor) cierreContadoInput.value = String(cierreContadoValor);
    });
  }

  if (btnContarCierre) {
    btnContarCierre.addEventListener('click', () => {
      // Abrir modal de conteo. Versión 1.1.8: YA NO se ponen los billetes en 0:
      // se ve lo que se llevaba contado (para empezar de cero está "Limpiar").
      calcularTotalConteo();
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
        // Versión 1.1.8: la caja ya se cerró: ahora sí se borra su conteo guardado
        if (window.conteoEfectivo) window.conteoEfectivo.limpiar(claveCierre);
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
      // Versión 1.1.8: se recuerda el total confirmado (por si se sale y vuelve)
      if (window.conteoEfectivo) window.conteoEfectivo.guardar({ confirmado: cierreContadoValor });
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
        // Las demás acciones (últimas ventas, cliente, nota, reimprimir,
        // inventario y registrar gasto) las maneja pos_carrito.js.
        // Antes aquí salían avisos de "Próximamente" que estorbaban.
      }
    });
  });

  console.log('POS cargado.');
})();