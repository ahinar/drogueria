// =====================================================================
// VENTANA «¿ESTÁS SEGURO?» DEL PROGRAMA (window.confirmar) y data-confirmar
// ---------------------------------------------------------------------
// Versión 1.1.15: antes estaba escrito dentro de base.html. La ventana (HTML) sigue en
// base.html (#modal-confirmar); aquí está lo que la abre y la cierra, y el aviso antes
// de enviar cualquier formulario con data-confirmar="¿…?".
// =====================================================================
window.confirmar = function (mensaje, opciones) {
  opciones = opciones || {};
  return new Promise(function (resolve) {
    const modal = document.getElementById('modal-confirmar');
    const titulo = document.getElementById('confirmar-titulo');
    const mensajeEl = document.getElementById('confirmar-mensaje');
    const icono = document.getElementById('confirmar-icono');
    const btnAceptar = document.getElementById('confirmar-aceptar');
    const btnCancelar = document.getElementById('confirmar-cancelar');

    titulo.textContent = opciones.titulo || '¿Estás seguro?';
    mensajeEl.textContent = mensaje;
    icono.textContent = opciones.icono || '⚠️';
    btnAceptar.textContent = opciones.textoAceptar || 'Aceptar';
    btnCancelar.textContent = opciones.textoCancelar || 'Cancelar';
    btnAceptar.className = 'boton ' + (opciones.tipo === 'info' ? '' : 'peligro');

    function cerrar(resultado) {
      modal.classList.add('modal-oculto');
      document.removeEventListener('keydown', manejarTeclas);
      resolve(resultado);
    }
    function manejarTeclas(e) {
      if (e.key === 'Escape') cerrar(false);
      if (e.key === 'Enter') cerrar(true);
    }

    btnAceptar.onclick = () => cerrar(true);
    btnCancelar.onclick = () => cerrar(false);
    modal.onclick = (e) => { if (e.target === modal) cerrar(false); };

    document.addEventListener('keydown', manejarTeclas);
    modal.classList.remove('modal-oculto');
    setTimeout(() => btnAceptar.focus(), 50);
  });
};


// ------------------------------------------------------------------
// CONFIRMAR ANTES DE ENVIAR UN FORMULARIO, con la ventana del programa
// (no con la ventana gris del navegador). Uso en cualquier plantilla:
//    <form data-confirmar="¿Anular el conteo?"> ... </form>
//    <button type="submit" data-confirmar="¿Eliminar el logo?">
// Si la persona acepta, el formulario se envía normalmente.
// ------------------------------------------------------------------
document.addEventListener('submit', async function (e) {
  const form = e.target;
  const boton = e.submitter;            // el botón con el que se envió
  const mensaje = (boton && boton.dataset.confirmar) || form.dataset.confirmar;
  if (!mensaje) return;
  if (form.dataset.confirmado === '1') {  // ya se confirmó: dejar pasar
    delete form.dataset.confirmado;
    return;
  }
  e.preventDefault();
  const ok = await window.confirmar(mensaje, { textoAceptar: 'Sí, continuar' });
  if (!ok) return;
  form.dataset.confirmado = '1';
  // requestSubmit(boton) envía también el nombre/valor del botón (ej: _accion=eliminar_logo)
  if (boton) form.requestSubmit(boton); else form.requestSubmit();
}, true);
