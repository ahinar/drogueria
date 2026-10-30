// =====================================================================
// ABRIR LA CAJA DEL POS — pos/abrir_caja.html
// Versión 1.1.15: antes estaba escrito dentro de la página; ahora tiene su archivo.
// Los datos del servidor llegan en un bloque <script type="application/json">.
// =====================================================================
(function () {
  const SALDO_CM = Number(JSON.parse(document.getElementById('abrir-caja-datos').textContent).saldo_caja_menor);
  const modal = document.getElementById('modal-conteo');
  const totalSpan = document.getElementById('conteo-total-valor');
  const jsonInput = document.getElementById('denominaciones-json');
  const inputEfectivo = document.getElementById('efectivo_inicial');
  const btnAbrir = document.getElementById('btn-contar-apertura');
  const btnSubmit = document.getElementById('btn-abrir');
  const chkSobregiro = document.getElementById('chk-sobregiro');
  const confirmarInput = document.getElementById('confirmar-sobregiro');
  const avisoSobregiro = document.getElementById('aviso-sobregiro');

  function calcularTotal() {
    let total = 0;
    const detalle = {};
    document.querySelectorAll('#modal-conteo .conteo-fila').forEach(function (fila) {
      const valor = parseInt(fila.dataset.valor, 10);
      const cant = parseInt(fila.querySelector('.conteo-input').value, 10) || 0;
      if (cant > 0) {
        total += valor * cant;
        detalle[valor] = cant;
      }
    });
    totalSpan.textContent = '$ ' + total.toLocaleString('es-CO');
    return { total, detalle };
  }

  function actualizarAviso() {
    const total = parseFloat(inputEfectivo.value) || 0;
    const excede = total > SALDO_CM + 0.01;
    if (excede) {
      avisoSobregiro.style.display = 'block';
    } else {
      avisoSobregiro.style.display = 'none';
      chkSobregiro.checked = false;
      confirmarInput.value = '0';
    }
    btnSubmit.disabled = excede && !chkSobregiro.checked;
    if (excede) {
      btnSubmit.textContent = chkSobregiro.checked ? 'Abrir caja (con sobregiro)' : 'Saldo insuficiente';
    } else {
      btnSubmit.textContent = 'Abrir caja';
    }
  }

  modal.addEventListener('click', function (e) {
    if (!e.target.classList.contains('conteo-btn')) return;
    const fila = e.target.closest('.conteo-fila');
    const input = fila.querySelector('.conteo-input');
    let v = parseInt(input.value, 10) || 0;
    if (e.target.textContent === '+') v += 1;
    else v = Math.max(0, v - 1);
    input.value = v;
    calcularTotal();
  });

  modal.addEventListener('input', function (e) {
    if (e.target.classList.contains('conteo-input')) calcularTotal();
  });

  // Versión 1.1.8: lo contado NO se borra al volver a abrir la ventana (antes
  // todo volvía a 0). Se guarda con el nombre "apertura" (ver _modal_conteo.html)
  // y se borra solo cuando la caja ya quedó abierta (pos.js).
  const guardado = window.conteoEfectivo.usar('apertura');
  if (guardado && guardado.confirmado != null) {
    // Ya se había confirmado un conteo (y se recargó la página): se vuelve a poner
    inputEfectivo.value = guardado.confirmado;
    jsonInput.value = JSON.stringify(guardado.detalle || {});
  }
  calcularTotal();

  // ---- Versión 1.1.8: botón "Abrir cajón" (la caja todavía está cerrada) ----
  // Le pide al programa que mande la orden de abrir a la impresora de tirillas.
  // El programa no puede saber si el cajón se abrió de verdad: solo que la orden
  // llegó a la impresora; por eso el aviso dice a cuál impresora le llegó.
  document.getElementById('btn-abrir-cajon-apertura').addEventListener('click', async function () {
    const boton = this;
    const datos = new FormData();
    datos.append('_csrf', document.querySelector('input[name="_csrf"]').value);
    boton.disabled = true;
    try {
      const resp = await fetch(document.getElementById('url-abrir-cajon-apertura').value,
                               { method: 'POST', body: datos, credentials: 'same-origin' });
      const json = await resp.json();
      if (json.ok) window.avisar('Orden de abrir el cajón enviada a «' + (json.impresora || 'la impresora') + '».', 'ok');
      else window.avisar('Cajón: ' + (json.error || 'no se pudo abrir.'), 'error');
    } catch (e) {
      window.avisar('Cajón: error de conexión.', 'error');
    } finally {
      boton.disabled = false;
    }
  });

  btnAbrir.addEventListener('click', function () {
    calcularTotal();                      // muestra el total de lo que ya se llevaba contado
    modal.classList.remove('modal-oculto');
  });

  document.getElementById('conteo-confirmar').addEventListener('click', function () {
    const { total, detalle } = calcularTotal();
    inputEfectivo.value = total;
    jsonInput.value = JSON.stringify(detalle);
    window.conteoEfectivo.guardar({ confirmado: total });
    modal.classList.add('modal-oculto');
    actualizarAviso();
  });

  document.getElementById('conteo-cancelar').addEventListener('click', function () {
    modal.classList.add('modal-oculto');
  });
  modal.addEventListener('click', function (e) {
    if (e.target === modal) modal.classList.add('modal-oculto');
  });

  inputEfectivo.addEventListener('input', actualizarAviso);
  chkSobregiro.addEventListener('change', function () {
    confirmarInput.value = chkSobregiro.checked ? '1' : '0';
    actualizarAviso();
  });

  actualizarAviso();
})();
