/* =====================================================================
   VENTANA "EDITAR PRODUCTO" (versión 1.1.12: archivo propio)
   ---------------------------------------------------------------------
   PARA QUÉ (para aprender):
     Antes este código vivía dentro de pos_carrito.js y solo servía en el POS.
     Ahora está aquí aparte para usar la MISMA ventana en dos lugares:
       - el POS (botón "Editar" de la ventana "i"), y
       - la TOMA DE INVENTARIO (botón ✏️ de cada producto).

   CÓMO SE USA desde otra pantalla:
       window.EditarProducto.abrir(producto_o_id, { alGuardar: function (id) { ... } })
         - producto_o_id: los datos del producto (si ya se tienen) o solo su número.
         - alGuardar: lo que hay que hacer después de guardar (refrescar la lista...).
       window.EditarProducto.abierto()  -> true si la ventana está abierta
       window.EditarProducto.cerrar()

   LA VENTANA (app/templates/pos/_modal_editar_producto.html) trae:
     nombre, código de barras, lotes, IVA, categorías, control, foto y
     "CÓMO SE VENDE": la unidad (su precio, si se vende suelta) y las otras
     presentaciones (Sello x 10, Caja x 100...) con lo que traen, precio,
     precio máximo y código de barras; "Por defecto" = lo que vende el POS.
     Se guarda en /pos/api/producto/<id>/editar (pos.api_producto_editar).
   ===================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const modal = $('modal-editar-producto');
  // Solo administrador y director técnico tienen la ventana en la página
  if (!modal) {
    window.EditarProducto = { abrir: function () {}, abierto: () => false, cerrar: function () {} };
    return;
  }
  const form = $('form-editar-producto');
  const filas = $('editar-pres-filas');
  const molde = $('editar-pres-molde');
  const URL_INFO = modal.dataset.urlInfo;              // /pos/api/producto/0
  const URL_EDITAR = modal.dataset.urlEditar;          // /pos/api/producto/0/editar
  const ESTATICOS = modal.dataset.estaticos || '/static/';
  let editandoId = null;
  let alGuardar = null;

  const csrf = () => (document.querySelector('input[name="_csrf"]') || {}).value || '';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // 9800 -> "9800"; null -> "" (para poner números en las cajas de texto)
  const textoNumero = (n) => (n === null || n === undefined || n === '' ? '' : String(+n));
  function avisar(texto, tipo) { if (window.avisar) window.avisar(texto, tipo || 'ok'); }

  // ---------- Foto ----------
  function mostrarFoto(src) {
    const img = $('editar-foto-img');
    img.hidden = !src;
    $('editar-foto-vacia').hidden = !!src;
    if (src) img.src = src;
  }

  // ---------- IVA: la tarifa solo se ve si es "gravado" ----------
  function actualizarTarifa() {
    const gravado = $('editar-iva-tipo').value === 'gravado';
    $('editar-iva-tarifa').hidden = !gravado;
    $('editar-iva-porcentaje').hidden = !gravado;
  }

  // ---------- CÓMO SE VENDE: filas de presentaciones ----------
  // El botón "Por defecto" de cada fila lleva el número de SU unidad (Sello x 10 = 7...).
  // Cuando se cambia la unidad de la fila, se cambia también ese número.
  function prepararFila(tr) {
    const sel = tr.querySelector('select[name="pres_unidad_id"]');
    const radio = tr.querySelector('input[name="venta_defecto"]');
    sel.addEventListener('change', () => { radio.value = sel.value; });
    tr.querySelector('.editar-pres-quitar').addEventListener('click', () => {
      const eraDefecto = radio.checked;
      tr.remove();
      if (eraDefecto) $('editar-defecto-base').checked = true;
      revisarSuelto();
    });
    return tr;
  }
  function agregarFila(x) {
    const tr = prepararFila(molde.content.firstElementChild.cloneNode(true));
    if (x) {
      tr.querySelector('select[name="pres_unidad_id"]').value = String(x.unidad_id);
      tr.querySelector('input[name="venta_defecto"]').value = String(x.unidad_id);
      tr.querySelector('input[name="pres_factor"]').value = textoNumero(x.factor);
      tr.querySelector('input[name="pres_precio"]').value = textoNumero(x.precio);
      tr.querySelector('input[name="pres_maximo"]').value = textoNumero(x.precio_maximo || '');
      tr.querySelector('input[name="pres_barras"]').value = x.codigo_barras || '';
    }
    filas.appendChild(tr);
    return tr;
  }
  // Si la unidad NO se vende suelta, su precio sale de la presentación por defecto:
  // la casilla de precio de la unidad se apaga para que no confunda.
  function revisarSuelto() {
    const suelto = $('editar-suelto').checked;
    $('editar-precio').disabled = !suelto;
    $('editar-precio-maximo').disabled = !suelto;
    $('editar-defecto-base').disabled = !suelto;
    if (!suelto && $('editar-defecto-base').checked) {
      const otro = filas.querySelector('.editar-pres-fila input[name="venta_defecto"]');
      if (otro) otro.checked = true;
    }
  }

  // ---------- Abrir, llenar y cerrar ----------
  async function abrir(productoOId, opciones) {
    alGuardar = (opciones && opciones.alGuardar) || null;
    let p = productoOId;
    if (typeof productoOId !== 'object') {           // llegó solo el número: se piden los datos
      try {
        const r = await fetch(URL_INFO.replace(/0$/, String(productoOId)), { credentials: 'same-origin' });
        const j = await r.json();
        if (!j.ok) { avisar(j.error || 'No se pudo abrir el producto.', 'error'); return; }
        p = j.producto;
      } catch (e) {
        avisar('Error de conexión: ' + e.message, 'error');
        return;
      }
    }
    llenar(p);
  }

  function llenar(p) {
    editandoId = p.id;
    form.reset();
    $('editar-error').hidden = true;
    $('editar-titulo').textContent = 'Editar producto';
    $('editar-nombre').value = p.nombre;
    $('editar-codigo-barras').value = p.codigo_barras || '';
    $('editar-maneja-lotes').checked = p.maneja_vencimiento;
    $('editar-iva-tipo').value = p.iva_tipo || 'excluido';
    $('editar-iva-tarifa').value = p.iva_tipo === 'gravado' ? textoNumero(p.iva_tarifa) : '';
    $('editar-formula').checked = p.requiere_formula;
    $('editar-control').checked = p.control_especial;
    form.querySelectorAll('input[name="categorias"]').forEach((c) => {
      c.checked = (p.categorias || []).includes(+c.value);
    });
    $('editar-foto-accion').value = '';
    mostrarFoto(p.imagen ? ESTATICOS + p.imagen : '');
    actualizarTarifa();

    // Cómo se vende. presentaciones[0] = la unidad (id 0); las demás, sobre, caja...
    const lista = p.presentaciones || [];
    const base = lista.find((x) => x.id === 0) || { nombre: 'Unidad', precio: p.precio, precio_maximo: p.precio_maximo };
    $('editar-base-nombre').textContent = base.nombre || 'Unidad';
    $('editar-se-cuenta').textContent = '· el inventario se cuenta en ' + (base.nombre || 'unidades').toLowerCase();
    $('editar-precio').value = textoNumero(base.precio || p.precio);
    $('editar-precio-maximo').value = textoNumero(p.precio_maximo || '');
    $('editar-suelto').checked = p.vende_suelto !== false;
    filas.querySelectorAll('.editar-pres-fila').forEach((tr) => tr.remove());
    lista.filter((x) => x.id !== 0).forEach((x) => agregarFila(x));
    // Marcar "Por defecto" (lo que vende el POS al tocar la tarjeta)
    const def = lista.find((x) => x.id === p.presentacion_defecto);
    const radioDef = def && def.id !== 0
      ? filas.querySelector('input[name="venta_defecto"][value="' + def.unidad_id + '"]') : null;
    (radioDef || $('editar-defecto-base')).checked = true;
    revisarSuelto();

    modal.classList.remove('modal-oculto');
    $('editar-nombre').focus();
  }

  function cerrar() {
    modal.classList.add('modal-oculto');
    editandoId = null;
  }

  // ---------- Guardar ----------
  async function guardar() {
    const errorBox = $('editar-error');
    errorBox.hidden = true;
    const datos = new FormData(form);              // todos los campos, incluida la foto
    datos.append('_csrf', csrf());
    // Las casillas apagadas no se envían: si la unidad no se vende suelta, su precio
    // lo calcula el programa con la presentación por defecto.
    $('editar-guardar').disabled = true;
    try {
      const resp = await fetch(URL_EDITAR.replace('/0/', '/' + editandoId + '/'),
                               { method: 'POST', body: datos, credentials: 'same-origin' });
      const json = await resp.json().catch(() => ({ ok: false, error: 'No tienes permiso para editar.' }));
      if (!json.ok) {
        errorBox.textContent = json.error || 'No se pudo guardar.';
        errorBox.hidden = false;
        return;
      }
      const id = editandoId;
      cerrar();
      avisar('Producto actualizado.');
      if (alGuardar) await alGuardar(id);
    } catch (e) {
      errorBox.textContent = 'Error de conexión: ' + e.message;
      errorBox.hidden = false;
    } finally {
      $('editar-guardar').disabled = false;
    }
  }

  // ---------- Botones ----------
  $('editar-cerrar').addEventListener('click', cerrar);
  $('editar-descartar').addEventListener('click', cerrar);
  $('editar-guardar').addEventListener('click', guardar);
  $('editar-iva-tipo').addEventListener('change', actualizarTarifa);
  $('editar-suelto').addEventListener('change', revisarSuelto);
  $('editar-pres-agregar').addEventListener('click', () => {
    agregarFila(null).querySelector('select').focus();
  });
  modal.addEventListener('click', (e) => { if (e.target === modal) cerrar(); });
  // Enter dentro del formulario = Guardar (en vez de recargar la página)
  form.addEventListener('submit', (e) => { e.preventDefault(); guardar(); });
  // Foto nueva: se muestra de una vez, antes de guardar
  $('editar-foto-archivo').addEventListener('change', (e) => {
    const archivo = e.target.files[0];
    if (!archivo) return;
    $('editar-foto-accion').value = '';
    mostrarFoto(window.URL.createObjectURL(archivo));
  });
  $('editar-foto-borrar').addEventListener('click', () => {
    $('editar-foto-archivo').value = '';
    $('editar-foto-accion').value = 'eliminar';
    mostrarFoto('');
  });
  // Escape cierra esta ventana (si está abierta) antes que cualquier otra
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.classList.contains('modal-oculto')) {
      cerrar();
      e.stopImmediatePropagation();
    }
  }, true);

  window.EditarProducto = {
    abrir: abrir,
    abierto: () => !modal.classList.contains('modal-oculto'),
    cerrar: cerrar,
  };
})();
