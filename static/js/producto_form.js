// =====================================================================
// FICHA DEL PRODUCTO (nuevo y editar) — app/templates/productos/form.html
// ---------------------------------------------------------------------
// Versión 1.1.15: este código vivía DENTRO de la página. Ahora está aquí: pestañas,
// foto (cambiar y eliminar), ventanas para crear categoría/laboratorio/unidad,
// presentaciones, precio sugerido con el margen y demás ayudas del formulario.
// Lo único que necesita del servidor es la unidad básica: data-unidad-basica del <form>.
// =====================================================================
  (function () {
    // === Tabs ===
    document.querySelectorAll('.form-tabs .tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        const objetivo = tab.dataset.tab;
        document.querySelectorAll('.form-tabs .tab').forEach(t => t.classList.remove('activo'));
        document.querySelectorAll('.form-tabs .tab-panel').forEach(p => p.classList.remove('activo'));
        tab.classList.add('activo');
        document.querySelector('.form-tabs .tab-panel[data-panel="' + objetivo + '"]').classList.add('activo');
      });
    });

    // === Sincronizar categoría principal con chips ===
    const catPrincipal = document.getElementById('sel-categoria-principal');
    const chipsCat = document.querySelectorAll('input[name="categorias"]');
    if (catPrincipal) {
      // Cambiar la categoría de arriba REEMPLAZA la anterior (se desmarca) y marca
      // la nueva. Para tener varias, se marcan en la pestaña "Categorías y usos".
      let catAnterior = catPrincipal.value;
      const chipDe = (id) => document.querySelector('input[name="categorias"][value="' + id + '"]');
      catPrincipal.addEventListener('change', function () {
        const id = catPrincipal.value;
        if (catAnterior && catAnterior !== id && chipDe(catAnterior)) chipDe(catAnterior).checked = false;
        if (id && chipDe(id)) chipDe(id).checked = true;
        catAnterior = id;
      });
      if (chipsCat.length === 1 && chipsCat[0].checked) {
        catPrincipal.value = chipsCat[0].value;
      }
    }

    // === IVA ===
    const selTipo = document.getElementById('iva_tipo');
    const inpTarifa = document.getElementById('iva_tarifa');
    function ajustarIva() {
      const sinIva = selTipo.value === 'excluido' || selTipo.value === 'exento';
      if (sinIva) {
        inpTarifa.value = '0';
        inpTarifa.readOnly = true;
        inpTarifa.style.background = '#eef2f5';
      } else {
        inpTarifa.readOnly = false;
        inpTarifa.style.background = '';
        if (parseFloat(inpTarifa.value) === 0) inpTarifa.value = '19';
      }
    }
    selTipo.addEventListener('change', ajustarIva);
    ajustarIva();

    // =====================================================================
    // VENTA Y PRECIOS
    // La persona escribe: "se vende por Sello x 10 a $4.000". Con eso:
    //   - "¿Cuántas trae?" se llena solo (10), sale de la unidad de medida
    //   - el precio de 1 unidad suelta se calcula solo ($4.000 ÷ 10 = $400),
    //     pero si la persona lo cambia a mano, ya no se toca
    //   - abajo se muestra un resumen con un ejemplo de recepción y de venta
    // =====================================================================
    const selVenta = document.getElementById('venta_unidad');
    const unidadSel = document.getElementById('unidad_venta_id');      // unidad mínima (se cuenta en ella)
    const inpPrecio = document.getElementById('venta_precio');
    const inpTrae = document.getElementById('venta_trae');
    const inpCosto = document.getElementById('venta_costo');
    const pv = document.getElementById('precio_venta');                 // precio de 1 unidad suelta
    const chkSuelto = document.getElementById('vende_suelto');
    const psug = document.getElementById('precio_sugerido');
    const gan = document.getElementById('ganancia');

    // Convierte lo escrito a número (acepta "4.000" y "2,5" como en Colombia)
    function numero(texto) {
      texto = (texto || '').trim().replace(/\$/g, '').replace(/\s/g, '');
      if (/^\d{1,3}(\.\d{3})+$/.test(texto)) texto = texto.replace(/\./g, '');   // 4.000 -> 4000
      return parseFloat(texto.replace(',', '.')) || 0;
    }
    // "unidad" -> "unidades", "tableta" -> "tabletas"
    function plural(palabra) { return /[aeiou]$/.test(palabra) ? palabra + 's' : palabra + 'es'; }
    function pesos(n) { return '$' + Math.round(n).toLocaleString('es-CO'); }
    function cantidadDe(select) {
      const opt = select.options[select.selectedIndex];
      return opt && opt.value ? window.cantidadDeUnidad(opt.textContent.trim(), opt.dataset.cantidad) : 0;
    }
    function nombreUnidad(select) {
      const opt = select.options[select.selectedIndex];
      return opt && opt.value ? opt.textContent.trim().split(' (')[0] : '';
    }
    // ¿Se vende por algo más grande que la unidad mínima? (Sello x 10 sí; Frasco no)
    function esPresentacion() {
      return selVenta.value && selVenta.value !== unidadSel.value;
    }
    function factorVenta() {
      return esPresentacion() ? numero(inpTrae.value) : 1;
    }

    // ¿El precio suelto lo escribió la persona? Si ya era distinto del calculado, sí.
    let sueltoManual = (function () {
      const f = factorVenta(), p = numero(inpPrecio.value), s = numero(pv.value);
      return f > 1 && s > 0 && Math.abs(s - p / f) > 1;
    })();
    pv.addEventListener('input', function () { sueltoManual = pv.value.trim() !== ''; actualizar(); });

    // Al escoger la unidad de venta: sugerir cuántas trae (Sello x 10 -> 10)
    selVenta.addEventListener('change', function () {
      const base = cantidadDe(unidadSel) || 1;
      const cant = cantidadDe(selVenta);
      inpTrae.value = esPresentacion() && cant / base > 1 ? +(cant / base).toFixed(2) : '';
      actualizar();
    });

    function actualizar() {
      const base = nombreUnidad(unidadSel) || 'Unidad';
      const venta = nombreUnidad(selVenta);
      const factor = factorVenta();
      const precio = numero(inpPrecio.value);
      const costo = numero(inpCosto.value);
      const conPresentacion = esPresentacion();

      // Nombres que aparecen en las etiquetas
      document.querySelectorAll('.nombre-unidad-min').forEach(function (s) { s.textContent = base.toLowerCase(); });
      document.getElementById('nombre-base').textContent = base;
      document.getElementById('costo-por').textContent = venta || 'la unidad de venta';
      // "¿Cuántas trae?" solo se pide si el nombre de la unidad no lo dice
      // (ej. "Sello" a secas). "SELLO X 10" ya trae 10: no hay que preguntar.
      const baseCant = cantidadDe(unidadSel) || 1;
      const pedirTrae = conPresentacion && (cantidadDe(selVenta) / baseCant <= 1 || numero(inpTrae.value) !== cantidadDe(selVenta) / baseCant);
      document.getElementById('campo-trae').hidden = !pedirTrae;
      document.getElementById('etiqueta-trae').hidden = !pedirTrae;
      inpTrae.required = conPresentacion;

      // ¿Se vende suelto? solo si la unidad de venta trae más de 1
      // "¿Se vende suelto?" siempre se ve; solo se puede marcar si la unidad
      // de venta trae varias (SELLO X 10). Con Unidad o Frasco queda apagada.
      const aplica = conPresentacion && factor > 1;
      chkSuelto.disabled = !aplica;
      document.getElementById('suelto-no-aplica').hidden = aplica;
      const suelto = chkSuelto.checked;
      document.getElementById('campo-precio-suelto').hidden = !(aplica && suelto);
      if (factor > 1 && precio > 0 && !sueltoManual) pv.value = Math.round(precio / factor);
      document.getElementById('ayuda-precio-suelto').textContent = factor > 1 && precio > 0
        ? 'Calculado: ' + pesos(precio) + ' ÷ ' + factor + ' = ' + pesos(precio / factor) + '. Puedes cambiarlo.' : '';

      // Ganancia de la unidad de venta
      const dif = precio - costo;
      gan.value = precio > 0 ? pesos(dif) + (costo > 0 ? '  (margen ' + (dif / precio * 100).toFixed(1) + '%)' : '') : '';

      // Resumen con el ejemplo de Fernando: llega una caja x 300, se venden 2 y 3 sueltas
      const resumen = document.getElementById('resumen-venta');
      if (conPresentacion && factor > 1 && venta) {
        const caja = factor * 30;
        const bases = plural(base.toLowerCase());
        let texto = 'Así queda: si recibes una caja de ' + caja + ' ' + bases + ', entran <strong>30 ' + venta + '</strong>. ' +
          'El POS vende por <strong>' + venta + '</strong>' + (precio > 0 ? ' a ' + pesos(precio) : '') + '.';
        texto += suelto && factor > 3
          ? ' Si vendes 1 ' + venta + ' y 3 sueltas, quedan 28 ' + venta + ' + ' + (factor - 3) + ' ' + bases + '.'
          : (suelto ? '' : ' No se vende suelto.');
        resumen.innerHTML = texto;
        resumen.hidden = false;
      } else if (venta) {
        resumen.innerHTML = 'Se vende y se cuenta por <strong>' + venta + '</strong>' + (precio > 0 ? ' a ' + pesos(precio) : '') + '.';
        resumen.hidden = false;
      } else {
        resumen.hidden = true;
      }
      // Aviso si la unidad mínima es "grande" (Caja x 100)
      document.getElementById('aviso-unidad-grande').hidden = !(cantidadDe(unidadSel) > 1);
      presFilas.querySelectorAll('.pres-fila').forEach(equivalePres);
    }
    [inpPrecio, inpTrae, inpCosto].forEach(function (i) { i.addEventListener('input', actualizar); });
    chkSuelto.addEventListener('change', actualizar);
    unidadSel.addEventListener('change', actualizar);

    // === Calcular sugerido: costo ÷ (1 − margen) ===
    document.getElementById('btn-calcular').addEventListener('click', function () {
      const compra = numero(inpCosto.value);
      const m = parseFloat(document.getElementById('margen').value) || 0;
      if (compra <= 0) { window.avisar('Primero escribe el costo.', 'error'); return; }
      if (m >= 100) { window.avisar('El margen debe ser menor a 100%.', 'error'); return; }
      const sugerido = Math.round(compra / (1 - m / 100));
      psug.value = pesos(sugerido);
      inpPrecio.value = sugerido;
      actualizar();
    });

    // === Otras presentaciones (opcional) ===
    // "¿Cuántas trae?" se sugiere solo: cantidad de la unidad elegida ÷
    // cantidad de la unidad mínima. Ej: Caja x 100 sobre Unidad -> 100.
    const presFilas = document.getElementById('pres-filas');
    const presMolde = document.getElementById('pres-molde');

    // Debajo de cada fila: "≈ $350 por unidad" (para comparar con el precio normal)
    function equivalePres(fila) {
      const factor = numero(fila.querySelector('.pres-factor').value);
      const precio = numero(fila.querySelector('.pres-precio').value);
      const base = (nombreUnidad(unidadSel) || 'unidad').toLowerCase();
      const fv = factorVenta(), pvv = numero(inpPrecio.value);
      fila.querySelector('.pres-equivale').textContent = factor > 1 && precio > 0
        ? '≈ ' + pesos(precio / factor) + ' por ' + base +
          (fv > 0 && pvv > 0 ? ' (en la venta normal: ' + pesos(pvv / fv) + ')' : '')
        : '';
    }
    presFilas.addEventListener('change', function (e) {
      const fila = e.target.closest('.pres-fila');
      if (!fila) return;
      if (e.target.classList.contains('pres-unidad')) {
        const factorInput = fila.querySelector('.pres-factor');
        const base = cantidadDe(unidadSel) || 1;
        const cant = cantidadDe(e.target);
        if (cant && !factorInput.value && cant / base > 1) factorInput.value = +(cant / base).toFixed(2);
      }
      equivalePres(fila);
    });
    presFilas.addEventListener('input', function (e) {
      const fila = e.target.closest('.pres-fila');
      if (fila) equivalePres(fila);
    });
    presFilas.addEventListener('click', function (e) {
      if (e.target.classList.contains('pres-quitar')) e.target.closest('.pres-fila').remove();
    });
    document.getElementById('pres-agregar').addEventListener('click', function () {
      presFilas.appendChild(presMolde.content.cloneNode(true));
      presFilas.lastElementChild.querySelector('select').focus();
    });

    // Producto sin movimientos que se contaba en "Sello x 10": pasa a contarse
    // en "Unidad" (la mínima), así se puede vender suelto. Con movimientos no se
    // toca aquí: para eso está el botón "Pasar el inventario a unidades".
    // La unidad básica (Unidad / Tableta) llega en data-unidad-basica del formulario (versión 1.1.15)
    const idBasica = (document.querySelector('form.form-tabs') || {dataset: {}}).dataset.unidadBasica || '';
    if (!unidadSel.disabled && idBasica && cantidadDe(unidadSel) > 1) {
      unidadSel.value = idBasica;
      selVenta.dispatchEvent(new Event('change'));     // recalcula "cuántas trae"
    }

    actualizar();

    // === MODAL: crear catálogos y unidades ===
    const modal = document.getElementById('modal-crear');
    const modalTitulo = document.getElementById('modal-titulo');
    const modalCamposCatalogo = document.getElementById('modal-campos-catalogo');
    const modalCamposUnidad = document.getElementById('modal-campos-unidad');
    const modalNombre = document.getElementById('modal-nombre');
    const modalUnidadNombre = document.getElementById('modal-unidad-nombre');
    const modalUnidadCantidad = document.getElementById('modal-unidad-cantidad');
    const modalUnidadReferencia = document.getElementById('modal-unidad-referencia');
    const modalError = document.getElementById('modal-error');
    const modalGuardar = document.getElementById('modal-guardar');
    const modalCancelar = document.getElementById('modal-cancelar');

    let contextoModal = { tipo: '', select: '' };
    const csrfToken = document.querySelector('input[name="_csrf"]').value;

    function abrirModal(tipo, selectId, titulo) {
      contextoModal = { tipo, select: selectId };
      modalTitulo.textContent = titulo;
      modalError.style.display = 'none';
      modalError.textContent = '';
      modalNombre.value = '';
      modalUnidadNombre.value = '';
      modalUnidadCantidad.value = '1';
      modalUnidadReferencia.value = '';

      if (tipo === 'unidad') {
        modalCamposCatalogo.style.display = 'none';
        modalCamposUnidad.style.display = 'block';
        setTimeout(() => modalUnidadNombre.focus(), 50);
      } else {
        modalCamposCatalogo.style.display = 'block';
        modalCamposUnidad.style.display = 'none';
        setTimeout(() => modalNombre.focus(), 50);
      }
      modal.classList.remove('modal-oculto');
    }

    function cerrarModal() {
      modal.classList.add('modal-oculto');
    }

    function mostrarErrorModal(msg) {
      modalError.textContent = msg;
      modalError.style.display = 'block';
    }

    // Si el nombre dice "x 7" (ej. "Sello x 7"), la cantidad se llena sola
    modalUnidadNombre.addEventListener('input', function () {
      const m = modalUnidadNombre.value.match(/x\s*(\d+)/i);
      if (m) modalUnidadCantidad.value = m[1];
    });

    modalCancelar.addEventListener('click', cerrarModal);
    modal.addEventListener('click', function (e) {
      if (e.target === modal) cerrarModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.classList.contains('modal-oculto')) cerrarModal();
    });

    document.querySelectorAll('.btn-mas').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const tipo = btn.dataset.tipo;
        const selectId = btn.dataset.select;
        const etiqueta = btn.title.replace('Crear nueva ', '').replace('Crear nuevo ', '');
        abrirModal(tipo, selectId, etiqueta.charAt(0).toUpperCase() + etiqueta.slice(1));
      });
    });

    modalGuardar.addEventListener('click', async function () {
      const { tipo, select } = contextoModal;
      const datos = new FormData();
      datos.append('_csrf', csrfToken);

      let url;
      if (tipo === 'unidad') {
        const nombre = modalUnidadNombre.value.trim();
        if (!nombre) { mostrarErrorModal('El nombre es obligatorio.'); return; }
        datos.append('nombre', nombre);
        datos.append('cantidad', modalUnidadCantidad.value || '1');
        datos.append('referencia_id', modalUnidadReferencia.value || '');
        url = '/admin/unidades/api/crear';
      } else {
        const nombre = modalNombre.value.trim();
        if (!nombre) { mostrarErrorModal('El nombre es obligatorio.'); return; }
        datos.append('nombre', nombre);
        url = '/admin/catalogos/' + tipo + '/api/crear';
      }

      modalGuardar.disabled = true;
      modalGuardar.textContent = 'Guardando…';

      try {
        const resp = await fetch(url, { method: 'POST', body: datos, credentials: 'same-origin' });
        const json = await resp.json();
        if (!json.ok) {
          mostrarErrorModal(json.error || 'No se pudo guardar.');
          return;
        }
        // Texto de la opción nueva (ej. "Sello x 7"; los catálogos solo llevan el nombre)
        const texto = json.nombre;
        function agregarOpcion(sel) {
          if (sel.querySelector('option[value="' + json.id + '"]')) return;
          const opcion = document.createElement('option');
          opcion.value = json.id;
          opcion.textContent = texto;
          if (json.cantidad) opcion.dataset.cantidad = json.cantidad;
          // En su lugar: alfabético, o por tamaño si es unidad (base.html → insertarOrdenado)
          window.insertarOrdenado(sel, opcion, tipo === 'unidad');
        }
        const sel = document.getElementById(select);
        agregarOpcion(sel);
        // Una unidad nueva sirve en TODAS las listas de unidades (venta, mínima, presentaciones)
        if (tipo === 'unidad') {
          document.querySelectorAll('select.sel-unidad').forEach(agregarOpcion);
          presMolde.content.querySelectorAll('select.sel-unidad').forEach(agregarOpcion);
        }
        sel.value = json.id;
        // Categoría nueva: también aparece (marcada) en la pestaña "Categorías y usos"
        if (tipo === 'categoria' && !document.querySelector('input[name="categorias"][value="' + json.id + '"]')) {
          const chip = document.createElement('label');
          chip.className = 'chip';
          chip.innerHTML = '<input type="checkbox" name="categorias" value="' + json.id + '"> <span></span>';
          chip.querySelector('span').textContent = json.nombre;
          document.getElementById('chips-categorias').appendChild(chip);
        }
        sel.dispatchEvent(new Event('change'));     // para que se recalcule todo
        cerrarModal();
      } catch (e) {
        mostrarErrorModal('Error de conexión: ' + e.message);
      } finally {
        modalGuardar.disabled = false;
        modalGuardar.textContent = 'Guardar';
      }
    });

    // ===== Flechas ‹ ›: avisar si hay cambios sin guardar =====
    const formFicha = document.querySelector('form.form-tabs');
    let hayCambios = false;
    formFicha.addEventListener('input', function () { hayCambios = true; });
    formFicha.addEventListener('change', function (e) { if (e.isTrusted) hayCambios = true; });
    formFicha.addEventListener('submit', function () { hayCambios = false; });
    async function irA(enlace) {
      if (!enlace) return;
      if (hayCambios && !(await window.confirmar('Tienes cambios sin guardar en este producto. ¿Salir sin guardar?'))) return;
      hayCambios = false;
      window.location = enlace.href;
    }
    document.querySelectorAll('.ficha-flechas a.flecha').forEach(function (a) {
      a.addEventListener('click', function (e) { e.preventDefault(); irA(a); });
    });
    // Atajos de teclado: Alt + ← (anterior) y Alt + → (siguiente)
    document.addEventListener('keydown', function (e) {
      if (!e.altKey) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); irA(document.getElementById('prod-anterior')); }
      if (e.key === 'ArrowRight') { e.preventDefault(); irA(document.getElementById('prod-siguiente')); }
    });

    // ===== Foto del producto: vista previa y «Eliminar» =====
    const inputImagen = document.getElementById('imagen-input');
    const accionImagen = document.getElementById('imagen-accion');
    const btnEliminarImagen = document.getElementById('btn-eliminar-imagen');
    const avisoSeQuita = document.getElementById('imagen-se-quita');
    // Cambia lo que se ve en el cuadro de la foto (se busca cada vez: el elemento se reemplaza)
    function ponerEnCuadro(nuevo) {
      const actual = document.getElementById('imagen-preview');
      nuevo.id = 'imagen-preview';
      actual.parentElement.replaceChild(nuevo, actual);
    }
    if (inputImagen) {
      inputImagen.addEventListener('change', function () {
        const file = this.files[0];
        if (!file) return;
        // Escogió una foto nueva: ya no se trata de "eliminar", sino de cambiarla
        if (accionImagen) accionImagen.value = '';
        if (avisoSeQuita) avisoSeQuita.hidden = true;
        if (btnEliminarImagen) btnEliminarImagen.hidden = false;
        const reader = new FileReader();
        reader.onload = function (e) {
          const nueva = document.createElement('img');
          nueva.src = e.target.result;
          nueva.alt = 'Vista previa';
          ponerEnCuadro(nueva);
        };
        reader.readAsDataURL(file);
      });
    }
    // Versión 1.1.12: «Eliminar» deja el cuadro vacío y marca que se borre al Guardar
    if (btnEliminarImagen) {
      btnEliminarImagen.addEventListener('click', function () {
        accionImagen.value = 'eliminar';
        if (inputImagen) inputImagen.value = '';          // por si había escogido otra
        const vacio = document.createElement('div');
        vacio.className = 'imagen-placeholder';
        vacio.textContent = '📷';
        ponerEnCuadro(vacio);
        btnEliminarImagen.hidden = true;
        if (avisoSeQuita) avisoSeQuita.hidden = false;
      });
    }

  })();
