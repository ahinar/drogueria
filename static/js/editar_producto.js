/* =====================================================================
   VENTANA "EDITAR PRODUCTO" — una sola para todo el programa
   ---------------------------------------------------------------------
   PARA QUÉ (para aprender):
     Versión 1.1.12: este código salió de pos_carrito.js para usar la MISMA
     ventana en el POS y en la TOMA DE INVENTARIO.
     Versión 1.1.17 (pedido de Fernando): ahora también en la RECEPCIÓN, y se
     juntó con la ventana "Completar datos". Tiene DOS PESTAÑAS:
       🏷️ Venta          → precios, presentaciones, código de barras, IVA...
                            (solo administrador y director técnico)
       🧪 Datos técnicos → registro INVIMA, laboratorio, concentración,
                            principio activo y forma farmacéutica (todos)

   CÓMO SE USA desde otra pantalla:
       window.EditarProducto.abrir(producto_o_id, opciones)
         - producto_o_id: los datos del producto (si ya se tienen) o solo su número.
         - opciones.alGuardar(id, producto): lo que hay que hacer después de guardar.
         - opciones.pestana: 'venta' o 'tecnicos' (cuál se ve primero).
         - opciones.recepcion: si se abre desde una línea de la Recepción, el costo
             que llegó, para el recuadro amarillo de arriba:
               { numero: 'REC-0100', costo: 8000, anterior: 6500 }
             (costo y anterior = lo que cuesta UNA unidad de inventario)
         - opciones.textoGuardar: el texto del botón Guardar.
       window.EditarProducto.abierto()  -> true si la ventana está abierta
       window.EditarProducto.cerrar()

   LA VENTANA está en app/templates/pos/_modal_editar_producto.html.
   Se guarda en DOS partes (cada una ya existía y tiene sus propias reglas):
     1) Datos técnicos → /recepciones/api/producto/<id>/tecnicos
     2) Venta          → /pos/api/producto/<id>/editar
   Primero los técnicos: así, si se escribe el registro INVIMA y a la vez se marca
   "Control especial" (que exige registro), la segunda parte ya lo encuentra.
   Versión 1.1.18 (lo encontró Fernando): ANTES de guardar nada, se le pregunta a la
   parte de venta si todo está bien (_solo_revisar=1). Si algo falla (ej. una
   presentación con precio $0), NO se guarda ninguna de las dos partes y se muestra
   el error con la fila marcada en rojo. Así nunca queda guardada una mitad.
   ===================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const modal = $('modal-editar-producto');
  if (!modal) {
    window.EditarProducto = { abrir: function () {}, abierto: () => false, cerrar: function () {} };
    return;
  }
  const form = $('form-editar-producto');
  const filas = $('editar-pres-filas');              // (no existe si no puede ver la pestaña Venta)
  const molde = $('editar-pres-molde');
  const URL_INFO = modal.dataset.urlInfo;              // /pos/api/producto/0
  const URL_EDITAR = modal.dataset.urlEditar;          // /pos/api/producto/0/editar
  const URL_TECNICOS = modal.dataset.urlTecnicos;      // /recepciones/api/producto/0/tecnicos
  const PUEDE_VENTA = modal.dataset.puedeVenta === '1';
  const MARGEN = parseFloat(modal.dataset.margen) || 30;   // % de Configuración
  const ESTATICOS = modal.dataset.estaticos || '/static/';
  let editandoId = null;
  let alGuardar = null;
  let producto = null;            // los datos con que se abrió (para el recuadro de costo)

  const csrf = () => (document.querySelector('input[name="_csrf"]') || {}).value || '';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // 9800 -> "9800"; null -> "" (para poner números en las cajas de texto)
  const textoNumero = (n) => (n === null || n === undefined || n === '' ? '' : String(+n));
  const pesos = (n) => '$' + Math.round(n).toLocaleString('es-CO');
  function avisar(texto, tipo) { if (window.avisar) window.avisar(texto, tipo || 'ok'); }

  // ---------- Pestañas ----------
  function verPestana(cual) {
    if (cual === 'venta' && !PUEDE_VENTA) cual = 'tecnicos';
    modal.querySelectorAll('.editar-pestana').forEach((b) => {
      b.classList.toggle('activa', b.dataset.pestana === cual);
      b.setAttribute('aria-selected', b.dataset.pestana === cual ? 'true' : 'false');
    });
    modal.querySelectorAll('.editar-panel').forEach((p) => { p.hidden = p.dataset.panel !== cual; });
  }
  modal.querySelectorAll('.editar-pestana').forEach((b) => {
    b.addEventListener('click', () => verPestana(b.dataset.pestana));
  });

  // ---------- Foto ----------
  function mostrarFoto(src) {
    const img = $('editar-foto-img');
    img.hidden = !src;
    $('editar-foto-vacia').hidden = !!src;
    if (src) img.src = src;
  }

  // ---------- IVA: la tarifa solo se ve si es "gravado" ----------
  function actualizarTarifa() {
    if (!PUEDE_VENTA) return;
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

  // ---------- RECUADRO DE COSTO (solo desde la Recepción, versión 1.1.17) ----------
  // Ejemplo de lo que dice:
  //   📦 En esta recepción llegó a $8.000 la unidad (la vez anterior: $6.500 · subió 23 %).
  //   Con el precio actual de $9.800 usted gana 18 %.
  //   💡 Para ganar 30 % véndalo a $11.500   [Usar este precio]
  // La ganancia se calcula como en la ventana "i": sobre el precio SIN IVA (el IVA es de la DIAN).
  //   ganancia % = (precio sin IVA − costo) ÷ precio sin IVA × 100
  // El precio sugerido es el que deja el margen de Configuración:
  //   precio sin IVA = costo ÷ (1 − margen)   y luego se le suma el IVA, si tiene.
  // Se redondea HACIA ARRIBA a $50 (si vale menos de $1.000) o a $100, para no quedar por debajo.
  function redondearPrecio(x) {
    const paso = x < 1000 ? 50 : 100;
    return Math.ceil(x / paso) * paso;
  }
  // Lo que vende el POS normalmente (la unidad, o el Sello x 10 si no se vende suelta)
  function presentacionDefecto(p) {
    const lista = p.presentaciones || [];
    return lista.find((x) => x.id === p.presentacion_defecto) || lista.find((x) => x.id === 0) ||
      { id: 0, nombre: 'Unidad', factor: 1, precio: p.precio, precio_maximo: p.precio_maximo };
  }
  function pintarCosto(p, rec) {
    const caja = $('editar-costo');
    if (!rec || !(rec.costo > 0)) { caja.hidden = true; caja.innerHTML = ''; return; }
    const tasa = p.iva_tipo === 'gravado' ? (+p.iva_tarifa || 0) / 100 : 0;
    const def = presentacionDefecto(p);
    const factor = +def.factor || 1;
    const nombreDef = (def.nombre || 'Unidad').toLowerCase();
    const costoDef = rec.costo * factor;                        // costo de lo que se vende (el sello...)
    const precioDef = +def.precio || 0;
    const sinIva = precioDef / (1 + tasa);
    const partes = [];
    // 1) Cuánto llegó y cuánto costaba antes
    let linea = '📦 En ' + (rec.numero ? 'la recepción ' + esc(rec.numero) : 'esta recepción') +
      ' llegó a <b>' + pesos(costoDef) + '</b> ' + (factor > 1 ? 'el ' + esc(nombreDef) : 'la unidad');
    if (rec.anterior > 0) {
      const cambio = (rec.costo - rec.anterior) / rec.anterior * 100;
      const txt = Math.abs(cambio) < 1 ? 'igual' :
        (cambio > 0 ? '<b class="editar-costo-sube">subió ' : '<b class="editar-costo-baja">bajó ') +
        Math.abs(cambio).toFixed(0) + ' %</b>';
      linea += ' (la vez anterior: ' + pesos(rec.anterior * factor) + ' · ' + txt + ')';
    } else {
      linea += ' (es la primera compra registrada)';
    }
    partes.push(linea + '.');
    // 2) Cuánto se gana con el precio de hoy
    if (sinIva > 0) {
      const gana = (sinIva - costoDef) / sinIva * 100;
      partes.push('Con el precio actual de <b>' + pesos(precioDef) + '</b> usted ' +
        (gana < 0 ? '<b class="editar-costo-sube">PIERDE ' + Math.abs(gana).toFixed(0) + ' %</b>'
                  : 'gana <b>' + gana.toFixed(0) + ' %</b>') + '.');
    }
    // 3) Precio sugerido para ganar el margen de Configuración
    let html = partes.join('<br>');
    if (MARGEN > 0 && MARGEN < 100) {
      const sugerido = redondearPrecio(costoDef / (1 - MARGEN / 100) * (1 + tasa));
      const maximo = +def.precio_maximo || 0;
      if (Math.abs(sugerido - precioDef) >= 1) {
        html += '<div class="editar-costo-sugerido">💡 Para ganar ' + String(MARGEN).replace('.', ',') +
          ' % véndalo a <b>' + pesos(sugerido) + '</b>' + (factor > 1 ? ' el ' + esc(nombreDef) : '') +
          (maximo && sugerido > maximo
            ? ' <span class="editar-costo-sube">(pasa el precio máximo de ' + pesos(maximo) + ')</span>' : '') +
          (PUEDE_VENTA ? ' <button type="button" class="boton-chico" id="editar-usar-sugerido" data-precio="' +
            sugerido + '">Usar este precio</button>' : '') + '</div>';
      }
    }
    caja.innerHTML = html;
    caja.hidden = false;
    const usar = $('editar-usar-sugerido');
    if (usar) usar.addEventListener('click', () => usarPrecio(def, +usar.dataset.precio));
  }
  // "Usar este precio": lo pone en la casilla de lo que se vende normalmente
  function usarPrecio(def, precio) {
    verPestana('venta');
    let casilla = $('editar-precio');                           // la unidad
    if (def.id !== 0) {                                          // el sello, la caja...
      const radio = filas.querySelector('.editar-pres-fila input[name="venta_defecto"][value="' + def.unidad_id + '"]');
      if (radio) casilla = radio.closest('tr').querySelector('input[name="pres_precio"]');
    }
    casilla.value = String(precio);
    casilla.focus();
    casilla.classList.add('editar-recien-cambiado');
    setTimeout(() => casilla.classList.remove('editar-recien-cambiado'), 1500);
  }

  // ---------- Laboratorios: el "+" crea uno nuevo sin salir ----------
  async function refrescarLaboratorios() {
    // Trae también los laboratorios creados después de abrir la página
    try {
      const r = await fetch('/admin/catalogos/laboratorio/api/lista', { credentials: 'same-origin' });
      const j = await r.json();
      if (j.ok) j.items.forEach((l) => agregarLaboratorio(String(l.id), l.nombre));
    } catch (e) { /* sin conexión: se queda con la lista que ya tenía */ }
  }
  function agregarLaboratorio(id, nombre) {
    const sel = $('editar-laboratorio');
    if (sel.querySelector('option[value="' + id + '"]')) return;     // ya está
    const op = document.createElement('option');
    op.value = id;
    op.textContent = nombre;
    if (window.insertarOrdenado) window.insertarOrdenado(sel, op, false); else sel.appendChild(op);
  }
  $('editar-nuevo-lab').addEventListener('click', async () => {
    if (!window.pedirDatos) return;
    const resp = await window.pedirDatos({
      titulo: 'Nuevo laboratorio',
      campos: [{ nombre: 'nombre', etiqueta: 'Nombre del laboratorio', minimo: 2, maximo: 120 }],
      textoAceptar: 'Crear',
    });
    if (!resp) return;
    const datos = new FormData();
    datos.append('nombre', resp.nombre.trim());
    datos.append('_csrf', csrf());
    try {
      const r = await fetch('/admin/catalogos/laboratorio/api/crear', { method: 'POST', body: datos, credentials: 'same-origin' });
      if (r.status === 403) { avisar('Solo el administrador o el director técnico pueden crear laboratorios.', 'error'); return; }
      const j = await r.json();
      if (!j.ok) { avisar('Error: ' + (j.error || 'no se pudo crear.'), 'error'); return; }
      agregarLaboratorio(String(j.id), j.nombre);
      $('editar-laboratorio').value = String(j.id);
      // Las otras listas de la página (ej. «Nuevo producto» de la Recepción) se enteran con este evento
      document.dispatchEvent(new CustomEvent('laboratorio-creado', { detail: { id: j.id, nombre: j.nombre } }));
      avisar(j.existente ? 'Ese laboratorio ya existía: quedó escogido.' : 'Laboratorio creado.');
    } catch (e) {
      avisar('Error de conexión: ' + e.message, 'error');
    }
  });
  // Principios activos: sugerencias mientras se escribe (varios separados por comas)
  if (window.campoConComas) {
    window.campoConComas($('editar-principios'), JSON.parse($('editar-principios-lista').textContent || '[]'));
  }

  // ---------- Abrir, llenar y cerrar ----------
  async function abrir(productoOId, opciones) {
    opciones = opciones || {};
    alGuardar = opciones.alGuardar || null;
    let p = productoOId;
    // Si llegó solo el número, o datos sin la parte técnica (versión vieja), se piden completos
    if (typeof productoOId !== 'object' || !productoOId.tecnicos) {
      const id = typeof productoOId === 'object' ? productoOId.id : productoOId;
      try {
        const r = await fetch(URL_INFO.replace(/0$/, String(id)), { credentials: 'same-origin' });
        const j = await r.json();
        if (!j.ok) { avisar(j.error || 'No se pudo abrir el producto.', 'error'); return; }
        p = j.producto;
      } catch (e) {
        avisar('Error de conexión: ' + e.message, 'error');
        return;
      }
    }
    await refrescarLaboratorios();
    llenar(p, opciones);
  }

  function llenar(p, opciones) {
    editandoId = p.id;
    producto = p;
    form.reset();
    $('editar-error').hidden = true;
    $('editar-titulo').textContent = 'Editar producto · ' + p.nombre;
    $('editar-guardar').textContent = opciones.textoGuardar || 'Guardar';

    // --- Pestaña Venta ---
    if (PUEDE_VENTA) {
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
    }

    // --- Pestaña Datos técnicos ---
    const t = p.tecnicos || {};
    $('editar-registro').value = t.registro_sanitario || '';
    $('editar-registro-vence').value = t.registro_vence || '';
    $('editar-laboratorio').value = t.laboratorio_id ? String(t.laboratorio_id) : '';
    $('editar-concentracion').value = p.concentracion || '';
    $('editar-principios').value = t.principios || '';
    $('editar-forma').value = t.forma_farmaceutica_id ? String(t.forma_farmaceutica_id) : '';

    // --- Foto ---
    $('editar-foto-accion').value = '';
    mostrarFoto(p.imagen ? ESTATICOS + p.imagen : '');

    // --- Recuadro de costo (Recepción) y pestaña inicial ---
    pintarCosto(p, opciones.recepcion);
    verPestana(opciones.pestana || 'venta');
    modal.classList.remove('modal-oculto');
    // El cursor queda en la primera casilla de la pestaña que se ve
    const primero = modal.querySelector('.editar-panel:not([hidden]) input:not([type="hidden"]), .editar-panel:not([hidden]) select');
    if (primero) primero.focus();
  }

  function cerrar() {
    modal.classList.add('modal-oculto');
    editandoId = null;
    producto = null;
  }

  // ---------- Guardar (en dos partes) ----------
  function mostrarError(texto, pestana) {
    const caja = $('editar-error');
    caja.textContent = texto;
    caja.hidden = false;
    if (pestana) verPestana(pestana);
  }
  async function enviar(url, datos) {
    const r = await fetch(url, { method: 'POST', body: datos, credentials: 'same-origin' });
    return r.json().catch(() => ({ ok: false, error: 'No tienes permiso para guardar esto.' }));
  }
  // Marca en rojo las filas de «Cómo se vende» sin precio (y pone el cursor en la primera)
  function marcarFilasSinPrecio() {
    if (!filas) return;
    let primera = null;
    filas.querySelectorAll('.editar-pres-fila').forEach((tr) => {
      const precio = tr.querySelector('input[name="pres_precio"]');
      const mal = !(parseFloat(precio.value) > 0);
      tr.classList.toggle('editar-fila-error', mal);
      if (mal && !primera) primera = precio;
    });
    if (primera) { primera.focus(); primera.select(); }
  }

  async function guardar() {
    $('editar-error').hidden = true;
    const id = editandoId;
    $('editar-guardar').disabled = true;
    try {
      // 0) REVISAR la parte de venta sin guardar nada (versión 1.1.18)
      if (PUEDE_VENTA) {
        const revisar = new FormData(form);
        revisar.append('_csrf', csrf());
        revisar.append('_solo_revisar', '1');
        revisar.append('_registro_nuevo', $('editar-registro').value.trim());
        revisar.delete('imagen');                      // la foto no hace falta para revisar
        const j0 = await enviar(URL_EDITAR.replace('/0/', '/' + id + '/'), revisar);
        if (!j0.ok) {
          mostrarError((j0.error || 'Revisa los datos.') + ' No se guardó nada todavía.', 'venta');
          marcarFilasSinPrecio();
          return;
        }
      }
      // 1) DATOS TÉCNICOS (y la foto, si quien edita no ve la pestaña Venta)
      const tec = new FormData();
      tec.append('_csrf', csrf());
      tec.append('registro_sanitario', $('editar-registro').value.trim());
      tec.append('registro_vence', $('editar-registro-vence').value);
      tec.append('laboratorio_id', $('editar-laboratorio').value);
      tec.append('concentracion', $('editar-concentracion').value.trim());
      tec.append('principios', $('editar-principios').value);
      tec.append('forma_farmaceutica_id', $('editar-forma').value);
      if (!PUEDE_VENTA) {
        const archivo = $('editar-foto-archivo').files[0];
        if (archivo) tec.append('imagen', archivo);
        tec.append('imagen_accion', $('editar-foto-accion').value);
      }
      const j1 = await enviar(URL_TECNICOS.replace('/0/', '/' + id + '/'), tec);
      if (!j1.ok) { mostrarError(j1.error || 'No se pudieron guardar los datos técnicos.', 'tecnicos'); return; }
      if (j1.aviso) avisar(j1.aviso, 'error');
      // 2) VENTA: todos los campos con "name" del formulario (incluida la foto)
      if (PUEDE_VENTA) {
        const datos = new FormData(form);
        datos.append('_csrf', csrf());
        const j2 = await enviar(URL_EDITAR.replace('/0/', '/' + id + '/'), datos);
        if (!j2.ok) {
          mostrarError((j2.error || 'No se pudo guardar.') + ' (Los datos técnicos sí quedaron guardados.)', 'venta');
          marcarFilasSinPrecio();
          // 1.1.18: la pantalla de atrás (ej. la línea de la Recepción) se entera de los datos
          // técnicos que SÍ quedaron guardados, aunque la ventana siga abierta.
          if (alGuardar) await alGuardar(id, j1.producto || {});
          return;
        }
      }
      const tecnicos = j1.producto || {};
      cerrar();
      avisar('Producto actualizado.');
      if (alGuardar) await alGuardar(id, tecnicos);
    } catch (e) {
      mostrarError('Error de conexión: ' + e.message);
    } finally {
      $('editar-guardar').disabled = false;
    }
  }

  // ---------- Botones ----------
  $('editar-cerrar').addEventListener('click', cerrar);
  $('editar-descartar').addEventListener('click', cerrar);
  $('editar-guardar').addEventListener('click', guardar);
  if (PUEDE_VENTA) {
    $('editar-iva-tipo').addEventListener('change', actualizarTarifa);
    $('editar-suelto').addEventListener('change', revisarSuelto);
    $('editar-pres-agregar').addEventListener('click', () => {
      agregarFila(null).querySelector('select').focus();
    });
  }
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
