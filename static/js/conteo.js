// =====================================================================
// TOMA DE INVENTARIO · pantalla de conteo
// =====================================================================
// Qué hace este archivo:
//   1. Muestra una LISTA en orden alfabético: una fila por cada lote
//      (producto, lote, vence, lo que dice el sistema y una casilla "Contado").
//   2. Filtros: Todos / Pendientes / Contados / Con diferencia, y buscador
//      (nombre, código o lector de código de barras).
//   3. Guarda lo contado al presionar Enter o al salir de la casilla.
//   4. Botón "Producto encontrado": para mercancía que está en la estantería
//      pero no en el sistema (así se carga el inventario inicial).
//   5. Mantiene al día la barra de progreso de arriba.
// =====================================================================
(function () {
  'use strict';

  // ---------------------------------------------------------------
  // 1. AYUDAS
  // ---------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const csrf = () => (document.querySelector('input[name="_csrf"]') || {}).value || '';
  const peso = (n) => '$' + Math.round(n).toLocaleString('es-CO');
  const cant = (n) => (+(+n).toFixed(2)).toLocaleString('es-CO');   // 9 -> "9", 2.5 -> "2,5"
  const HOY = new Date().toISOString().slice(0, 10);

  // Cantidad dicha como se vende: 274 unidades, vendiendo por Sello x 10 ->
  // "27 Sello x 10 + 4 Unidad". Sin paquete -> "274".
  function enPaquetes(n, p) {
    n = +n || 0;
    const paq = p && p.paquete;
    if (!paq || n <= 0) return cant(n);
    const enteros = Math.floor(n / paq.factor + 1e-9);
    const resto = +(n - enteros * paq.factor).toFixed(4);
    const partes = [];
    if (enteros) partes.push(enteros + ' ' + paq.nombre);
    if (resto > 0) partes.push(cant(resto) + ' ' + (p.unidad || 'unidades'));
    return partes.join(' + ');
  }

  // Evita que un nombre con < o > rompa la página
  function esc(t) {
    return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  // "2027-03-15" -> "15/03/2027"
  function fecha(iso) {
    if (!iso) return '—';
    const p = String(iso).slice(0, 10).split('-');
    return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : iso;
  }
  // Mensajito que aparece unos segundos abajo
  function aviso(texto, error) {
    const d = document.createElement('div');
    d.className = 'pos-toast' + (error ? ' conteo-toast-error' : '');
    d.textContent = texto;
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 3000);
  }
  async function pedirJSON(url, opciones) {
    const resp = await fetch(url, Object.assign({ credentials: 'same-origin' }, opciones || {}));
    return resp.json();
  }

  const URL_BUSCAR = $('url-buscar').value;
  const URL_CONTAR = $('url-contar').value;
  const URL_QUITAR = $('url-quitar').value;
  const lista = $('conteo-lista');
  const buscador = $('conteo-buscar');
  const botonMas = $('conteo-mas');

  // ---------------------------------------------------------------
  // 2. ESTADO (lo que la pantalla "recuerda")
  // ---------------------------------------------------------------
  let filtro = 'todos';
  let pagina = 0;
  let productos = [];        // productos que se están mostrando (cada uno con sus lotes)
  let numeroBusqueda = 0;    // para ignorar respuestas viejas si se escribe rápido

  // ---------------------------------------------------------------
  // 3. BUSCAR Y DIBUJAR LA LISTA
  // ---------------------------------------------------------------
  async function buscar(agregar) {
    const mio = ++numeroBusqueda;
    if (!agregar) pagina = 0;
    const url = URL_BUSCAR + '?q=' + encodeURIComponent(buscador.value.trim()) +
      '&filtro=' + filtro + '&pagina=' + pagina;
    try {
      const json = await pedirJSON(url);
      if (mio !== numeroBusqueda) return;        // llegó tarde: ya hay otra búsqueda
      productos = agregar ? productos.concat(json.productos) : json.productos;
      pintar();
      pintarResumen(json.resumen);
      botonMas.hidden = !json.hay_mas;
      // Lector de código de barras: si encontró el producto exacto, va directo
      // a su primera casilla sin contar (si está en 0, a la línea nueva: lote o cantidad)
      if (json.exacto && productos.length === 1) {
        const casilla = lista.querySelector('.cnt-fila-nueva input:not([type=hidden])') ||
                        lista.querySelector('input.conteo-cantidad:not([data-contado])') ||
                        lista.querySelector('input.conteo-cantidad');
        if (casilla) { casilla.focus(); casilla.select(); }
      }
    } catch (e) {
      lista.innerHTML = '<p class="conteo-error">Error de conexión: ' + esc(e.message) + '</p>';
    }
  }

  function pintarResumen(r) {
    if (!r) return;
    $('r-contados').textContent = r.contados;
    $('r-pendientes').textContent = r.pendientes;
    $('r-diferencias').textContent = r.con_diferencia;
    $('r-nuevos').textContent = r.lotes_nuevos;
    $('r-valor').textContent = peso(r.valor_diferencia);
  }

  // Etiqueta de colores para la diferencia: rojo falta, verde sobra, gris igual
  function etiquetaDiferencia(linea, p) {
    if (!linea) return '';
    const d = linea.diferencia;
    if (Math.abs(d) < 1e-9) return '<span class="conteo-dif conteo-dif-ok">✓</span>';
    // Con paquete se dice completo ("−3 Unidad"); sin paquete solo el número
    const texto = p && p.paquete ? enPaquetes(Math.abs(d), p) : cant(Math.abs(d));
    return '<span class="conteo-dif ' + (d < 0 ? 'conteo-dif-falta' : 'conteo-dif-sobra') + '">' +
      (d > 0 ? '+' : '−') + esc(texto) + '</span>';
  }

  // Casilla(s) para escribir lo contado.
  //   - Si se vende por unidad o frasco: una casilla ("¿cuántos?").
  //   - Si se vende por Sello x 10: dos casillas, "sellos" + "sueltas".
  //     Ej: 27 sellos y 4 sueltas -> se guarda 274 (el programa cuenta unidades).
  // Los datos del lote van en el <div class="cnt-contado"> que las envuelve.
  function casillasContado(p, l) {
    const contada = l.linea ? +l.linea.contada : null;
    const datos = (l.lote_id ? ' data-lote="' + l.lote_id + '"' : '') +
      (l.linea ? ' data-linea="' + l.linea.id + '" data-guardado="' + contada + '"' : '');
    const marca = l.linea ? ' data-contado="1"' : '';
    const quien = esc(p.nombre) + ' lote ' + esc(l.lote || '');
    if (!p.paquete) {
      return '<div class="cnt-contado"' + datos + '><input type="text" inputmode="decimal" class="conteo-cantidad"' +
        marca + (l.linea ? ' value="' + cant(contada) + '"' : '') +
        ' placeholder="¿cuántos?" aria-label="Contado de ' + quien + '"></div>';
    }
    const f = p.paquete.factor;
    const enteros = contada === null ? '' : Math.floor(contada / f + 1e-9);
    const sueltas = contada === null ? '' : +(contada - enteros * f).toFixed(4);
    return '<div class="cnt-contado cnt-doble"' + datos + ' data-factor="' + f + '">' +
      '<label><input type="text" inputmode="numeric" class="conteo-cantidad conteo-paq"' + marca +
        ' value="' + enteros + '" placeholder="0" aria-label="' + esc(p.paquete.nombre) + ' de ' + quien + '">' +
        '<small>' + esc(p.paquete.nombre) + '</small></label>' +
      '<label><input type="text" inputmode="decimal" class="conteo-cantidad conteo-sueltas"' + marca +
        ' value="' + (sueltas === '' ? '' : cant(sueltas)) + '" placeholder="0" aria-label="Sueltas de ' + quien + '">' +
        '<small>' + esc(p.unidad || 'unidades') + ' sueltas</small></label>' +
    '</div>';
  }

  // Lo que hay escrito en la fila, en unidades. null = no escribió nada.
  function totalEscrito(caja) {
    // "1.200" (miles) -> 1200 ; "2,5" -> 2.5 ; vacío -> null
    const numero = (i) => {
      let t = i ? i.value.trim() : '';
      if (t === '') return null;
      if (/^\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, '');
      return /^\d*([.,]\d+)?$/.test(t) ? parseFloat(t.replace(',', '.')) : NaN;
    };
    if (!caja.dataset.factor) {
      const v = numero(caja.querySelector('input'));
      return v;
    }
    const paq = numero(caja.querySelector('.conteo-paq'));
    const sue = numero(caja.querySelector('.conteo-sueltas'));
    if (paq === null && sue === null) return null;
    if (Number.isNaN(paq) || Number.isNaN(sue)) return NaN;
    return (paq || 0) * (+caja.dataset.factor) + (sue || 0);
  }

  // Una fila de la lista = un lote. "primera" indica si es el primer lote del
  // producto: solo ahí se escribe el nombre, para que la lista se lea mejor.
  function filaLote(p, l, primera) {
    const vencido = l.vencimiento && l.vencimiento.slice(0, 10) < HOY;
    // Si ya se contó, se muestra lo que decía el sistema AL CONTAR (es contra lo que se compara)
    const sistema = l.linea ? l.linea.sistema : l.sistema_actual;
    const etiqueta = l.nuevo ? ' <span class="conteo-tag conteo-tag-nuevo">encontrado</span>'
      : (l.estado !== 'disponible' && l.estado !== 'agotado'
        ? ' <span class="conteo-tag">' + esc(l.estado) + '</span>' : '');
    return '<div class="cnt-fila' + (primera ? '' : ' cnt-mismo') + '" data-producto="' + p.id + '">' +
      '<div class="cnt-prod">' + (primera
        ? '<strong>' + esc(p.nombre) + (p.concentracion ? ' ' + esc(p.concentracion) : '') + '</strong>' +
          '<span class="suave"> ' + esc(p.codigo) + (p.paquete ? ' · se vende por ' + esc(p.paquete.nombre)
            : ' · se cuenta en ' + esc(p.unidad || 'unidades')) + '</span>'
        : '') + '</div>' +
      '<div class="cnt-lote"><span class="cnt-etq">Lote </span>' + esc(l.lote || 'Sin lote') + etiqueta + '</div>' +
      '<div class="cnt-vence' + (vencido ? ' conteo-vencido' : '') + '"><span class="cnt-etq">Vence </span>' +
        fecha(l.vencimiento) + (vencido ? ' ⚠' : '') + '</div>' +
      '<div class="cnt-sistema num"><span class="cnt-etq">Sistema </span><b>' + esc(enPaquetes(sistema, p)) + '</b></div>' +
      casillasContado(p, l) +
      '<div class="cnt-dif">' + etiquetaDiferencia(l.linea, p) + '</div>' +
      '<div class="cnt-quitar">' + (l.linea ? '<button type="button" class="conteo-quitar" data-linea="' +
        l.linea.id + '" title="Borrar lo contado de este lote">✕</button>' : '') + '</div>' +
    '</div>';
  }

  // LÍNEA NUEVA, en la misma lista (como Odoo): un lote que apareció en la
  // estantería y no está en el sistema, o un producto que estaba en 0.
  //   - Si el producto maneja vencimiento: casillas Lote, Vence y Contado.
  //   - Si no (cepillos, biberones): "Sin lote" y solo Contado.
  //   - Si el producto no tiene costo conocido, también pide el costo de 1 unidad.
  // Al guardar se manda producto + lote + vencimiento + cantidad (Caso B del servidor:
  // si ese lote ya existió, por ejemplo agotado, se cuenta sobre el mismo lote).
  function filaNuevoLote(p, primera, aviso0) {
    const pideLote = p.maneja_vencimiento;
    const pideCosto = !(p.costo_sugerido > 0);
    const caja = casillasContado(p, { lote_id: null, linea: null })
      .replace('<div class="cnt-contado', '<div data-nuevo="1" class="cnt-contado');
    return '<div class="cnt-fila cnt-fila-nueva' + (primera ? '' : ' cnt-mismo') + '" data-producto="' + p.id + '">' +
      '<div class="cnt-prod">' + (primera
        ? '<strong>' + esc(p.nombre) + (p.concentracion ? ' ' + esc(p.concentracion) : '') + '</strong>' +
          '<span class="suave"> ' + esc(p.codigo) + '</span>' +
          (aviso0 ? '<br><span class="conteo-tag conteo-tag-cero">⚠ Está en 0 en el sistema</span>' : '')
        : '') +
        (pideCosto ? '<label class="cnt-costo-nuevo">Costo de 1 ' + esc((p.unidad || 'unidad').toLowerCase()) +
          ' <input type="text" inputmode="decimal" class="nl-costo" placeholder="$"></label>' : '') + '</div>' +
      '<div class="cnt-lote">' + (pideLote
        ? '<input type="text" class="nl-lote" placeholder="Lote" maxlength="40" aria-label="Lote nuevo">'
        : '<span class="suave">Sin lote</span>') + '</div>' +
      '<div class="cnt-vence">' + (pideLote
        ? '<input type="date" class="nl-vence" aria-label="Vence">' : '—') + '</div>' +
      '<div class="cnt-sistema num"><span class="cnt-etq">Sistema </span><b>0</b></div>' +
      caja +
      '<div class="cnt-dif"></div>' +
      '<div class="cnt-quitar"><button type="button" class="conteo-quitar-nueva" title="Quitar esta línea">✕</button></div>' +
    '</div>';
  }

  // Botón debajo de los lotes de un producto que maneja vencimiento
  function filaAgregarLote(p) {
    return '<div class="cnt-agregar" data-producto="' + p.id + '">' +
      '<button type="button" class="conteo-agregar-lote" data-agregar="' + p.id + '">+ Agregar lote</button></div>';
  }

  // Lista vacía: si se buscó algo que no existe, ofrecer crearlo
  function pintarVacio() {
    const q = buscador.value.trim();
    if (!q) {
      lista.innerHTML = '<p class="suave conteo-vacio">No hay productos para mostrar con ese filtro.</p>';
      return;
    }
    lista.innerHTML = '<div class="conteo-vacio">' +
      '<p>No hay ningún producto "<strong>' + esc(q) + '</strong>".</p>' +
      '<button type="button" class="boton" id="btn-crear-producto">+ Crear producto "' + esc(q) + '"</button></div>';
  }

  function pintar() {
    if (!productos.length) { pintarVacio(); return; }
    // Los productos ya llegan en orden alfabético desde el servidor
    lista.innerHTML = productos.map((p) => {
      let html = p.lotes.length
        ? p.lotes.map((l, i) => filaLote(p, l, i === 0)).join('')
        : filaNuevoLote(p, true, true);          // en 0: una línea lista para contar
      if (p.maneja_vencimiento) html += filaAgregarLote(p);
      return html;
    }).join('');
  }

  // ---------------------------------------------------------------
  // 4. GUARDAR LO CONTADO DE UN LOTE
  // ---------------------------------------------------------------
  async function enviarConteo(datos) {
    datos.append('_csrf', csrf());
    return pedirJSON(URL_CONTAR, { method: 'POST', body: datos });
  }

  // Se llama al presionar Enter o al salir de una casilla. Lee TODA la fila
  // (sellos + sueltas) y guarda el total en unidades.
  async function guardarCasilla(input) {
    const caja = input.closest('.cnt-contado');
    const total = totalEscrito(caja);
    if (total === null) return;                                   // no escribió nada
    if (Number.isNaN(total) || total < 0) { aviso('Escribe solo números.', true); return; }
    // data-guardado = lo ya guardado: si no cambió, no se vuelve a enviar
    if (caja.dataset.guardado !== undefined && +caja.dataset.guardado === total) return;
    const datos = new FormData();
    datos.append('cantidad', String(total));
    const filaN = input.closest('.cnt-fila');
    if (caja.dataset.lote) datos.append('lote_id', caja.dataset.lote);
    else if (caja.dataset.linea) datos.append('linea_id', caja.dataset.linea);   // lote encontrado ya anotado
    else if (caja.dataset.nuevo) {
      // Línea nueva: producto + lote + vencimiento (+ costo si lo pidió)
      const loteI = filaN.querySelector('.nl-lote');
      const venceI = filaN.querySelector('.nl-vence');
      const costoI = filaN.querySelector('.nl-costo');
      if (loteI && (!loteI.value.trim() || !venceI.value)) {
        aviso('Escribe el lote y la fecha de vencimiento.', true);
        (loteI.value.trim() ? filaN.querySelector('.cnt-vence input:not([type=hidden])') : loteI).focus();
        return;
      }
      datos.append('producto_id', filaN.dataset.producto);
      if (loteI) { datos.append('lote', loteI.value.trim()); datos.append('vencimiento', venceI.value); }
      if (costoI && costoI.value.trim()) datos.append('costo', costoI.value.trim());
    }
    const casillas = caja.querySelectorAll('input');
    casillas.forEach((i) => i.classList.add('guardando'));
    // Se marca como guardado ANTES de enviar: así, si Enter y "salir de la
    // casilla" ocurren casi juntos, no se envía dos veces.
    const anterior = caja.dataset.guardado;
    caja.dataset.guardado = total;
    try {
      const json = await enviarConteo(datos);
      if (!json.ok) {
        if (anterior === undefined) delete caja.dataset.guardado; else caja.dataset.guardado = anterior;
        aviso(json.error || 'No se pudo guardar.', true);
        casillas.forEach((i) => i.classList.add('con-error'));
        return;
      }
      casillas.forEach((i) => { i.classList.remove('con-error'); i.dataset.contado = '1'; });
      caja.dataset.linea = json.linea.id;
      if (json.lote_id) caja.dataset.lote = json.lote_id;         // era un lote que ya existía
      // ¿Ese lote ya estaba anotado en otra línea de la pantalla? Se deja solo una
      const otra = [...lista.querySelectorAll('.cnt-contado[data-linea="' + json.linea.id + '"]')].find((c) => c !== caja);
      if (caja.dataset.nuevo && otra) {
        filaN.remove();
        const filaOtra = otra.closest('.cnt-fila');
        const pOtro = productos.find((x) => x.id === +filaOtra.dataset.producto);
        filaOtra.querySelector('.cnt-dif').innerHTML = etiquetaDiferencia(json.linea, pOtro);
        aviso('Ese lote ya estaba anotado: se actualizó la cantidad.');
        buscar(false);
        return;
      }
      if (caja.dataset.nuevo) {
        // Ya guardado: el lote y la fecha quedan fijos (para cambiarlos, ✕ y otra vez)
        filaN.querySelectorAll('.nl-lote, .nl-costo, .cnt-vence input, .cnt-vence button').forEach((i) => { i.disabled = true; });
      }
      // Se actualiza la fila: sistema al contar, diferencia y botón de quitar
      const fila = input.closest('.cnt-fila');
      const p = productos.find((x) => x.id === +fila.dataset.producto);
      fila.querySelector('.cnt-sistema b').textContent = enPaquetes(json.linea.sistema, p);
      fila.querySelector('.cnt-dif').innerHTML = etiquetaDiferencia(json.linea, p);
      fila.querySelector('.cnt-quitar').innerHTML = '<button type="button" class="conteo-quitar" data-linea="' +
        json.linea.id + '" title="Borrar lo contado de este lote">✕</button>';
      pintarResumen(json.resumen);
    } catch (e) {
      if (anterior === undefined) delete caja.dataset.guardado; else caja.dataset.guardado = anterior;
      aviso('Error de conexión: ' + e.message, true);
    } finally {
      casillas.forEach((i) => i.classList.remove('guardando'));
    }
  }

  // Enter = guardar y pasar a la siguiente casilla
  lista.addEventListener('keydown', (e) => {
    // Línea nueva: Enter en Lote -> Vence -> Contado (sin guardar todavía)
    if (e.key === 'Enter' && !e.target.classList.contains('conteo-cantidad') && e.target.closest('.cnt-fila-nueva')) {
      e.preventDefault();
      const campos = [...e.target.closest('.cnt-fila-nueva').querySelectorAll('input:not([type=hidden]):not([disabled])')];
      const sig = campos[campos.indexOf(e.target) + 1];
      if (sig) { sig.focus(); if (sig.select) sig.select(); }
      return;
    }
    if (e.key !== 'Enter' || !e.target.classList.contains('conteo-cantidad')) return;
    e.preventDefault();
    const casillas = [...lista.querySelectorAll('input.conteo-cantidad')];
    const siguiente = casillas[casillas.indexOf(e.target) + 1];
    // En "sellos", Enter solo pasa a "sueltas" (se guarda al terminar la fila)
    if (!e.target.classList.contains('conteo-paq')) guardarCasilla(e.target);
    if (siguiente) { siguiente.focus(); siguiente.select(); }
    else { buscador.focus(); buscador.select(); }   // último lote: volver al buscador
  });
  // Salir de la casilla también guarda
  lista.addEventListener('focusout', (e) => {
    if (!e.target.classList.contains('conteo-cantidad')) return;
    const caja = e.target.closest('.cnt-contado');
    if (e.relatedTarget && caja.contains(e.relatedTarget)) return;   // pasó de "sellos" a "sueltas"
    guardarCasilla(e.target);
  });

  // Quitar lo contado / ingresar un producto sin lotes
  lista.addEventListener('click', async (e) => {
    const agregar = e.target.closest('[data-agregar]');
    if (agregar) {
      // Se agrega una línea nueva justo encima del botón y se va a la casilla Lote
      const p = productos.find((x) => x.id === +agregar.dataset.agregar);
      agregar.closest('.cnt-agregar').insertAdjacentHTML('beforebegin', filaNuevoLote(p, false, false));
      const nueva = agregar.closest('.cnt-agregar').previousElementSibling;
      const primero = nueva.querySelector('input:not([type=hidden])');
      if (primero) primero.focus();
      return;
    }
    const quitarNueva = e.target.closest('.conteo-quitar-nueva');
    if (quitarNueva) {
      const fila = quitarNueva.closest('.cnt-fila');
      // Si es la única línea de un producto en 0, no se quita (para poder contarlo)
      const esUnica = !fila.classList.contains('cnt-mismo');
      if (esUnica) { fila.querySelectorAll('input:not([type=hidden])').forEach((i) => { i.value = ''; }); return; }
      fila.remove();
      return;
    }
    if (e.target.closest('#btn-crear-producto')) { abrirCrearProducto(buscador.value.trim()); return; }
    const quitar = e.target.closest('.conteo-quitar');
    if (quitar) {
      if (!(await window.confirmar('¿Borrar lo contado de este lote?'))) return;
      const datos = new FormData();
      datos.append('linea_id', quitar.dataset.linea);
      datos.append('_csrf', csrf());
      const json = await pedirJSON(URL_QUITAR, { method: 'POST', body: datos });
      if (!json.ok) { aviso(json.error || 'No se pudo borrar.', true); return; }
      buscar(false);
    }
  });

  // ---------------------------------------------------------------
  // 5. VENTANA "CREAR PRODUCTO" (lo encontrado no existe en el sistema)
  // ---------------------------------------------------------------
  // Usa la misma dirección que la recepción (/recepciones/api/crear-producto).
  // Si lo buscado parece un código de barras (solo números), se pone ahí;
  // si no, se usa como nombre. Al guardar, la lista busca el producto nuevo
  // y queda su línea lista para escribir lote, vencimiento y cantidad.
  const modalCP = $('modal-crear-producto');
  const cpUnidad = $('cp-unidad');
  const cpTrae = $('cp-trae');

  function mostrarErrorCP(texto) {
    $('cp-error').textContent = texto;
    $('cp-error').hidden = !texto;
  }
  // "por SELLO X 10": cuántas trae sale del nombre; si no lo dice, se pregunta
  function ajustarUnidadCP(sugerir) {
    const opt = cpUnidad.options[cpUnidad.selectedIndex];
    const cantidad = opt ? (parseFloat(opt.dataset.cantidad) || 1) : 1;
    const esUnidad = opt && opt.textContent.trim().toLowerCase() === 'unidad';
    if (sugerir) cpTrae.value = cantidad > 1 ? cantidad : '';
    $('cp-campo-trae').hidden = esUnidad || cantidad > 1;
    const trae = parseFloat((cpTrae.value || '').replace(',', '.')) || 0;
    $('cp-campo-suelto').hidden = !(trae > 1);
    const t = ($('cp-precio').value || '').trim();
    const precio = parseFloat((/^\d{1,3}(\.\d{3})+$/.test(t) ? t.replace(/\./g, '') : t).replace(',', '.')) || 0;
    $('cp-precio-suelto').textContent = trae > 1 && precio > 0 ? '(1 unidad = ' + peso(precio / trae) + ')' : '';
  }
  cpUnidad.addEventListener('change', () => ajustarUnidadCP(true));
  cpTrae.addEventListener('input', () => ajustarUnidadCP(false));
  $('cp-precio').addEventListener('input', () => ajustarUnidadCP(false));

  function abrirCrearProducto(texto) {
    $('form-crear-producto').reset();
    mostrarErrorCP('');
    const esCodigo = /^\d{6,}$/.test(texto);
    $('cp-barras').value = esCodigo ? texto : '';
    $('cp-nombre').value = esCodigo ? '' : texto.toUpperCase();
    ajustarUnidadCP(true);
    modalCP.classList.remove('modal-oculto');
    $('cp-nombre').focus();
  }
  function cerrarCrearProducto() {
    modalCP.classList.add('modal-oculto');
    buscador.focus();
  }

  async function guardarProducto() {
    mostrarErrorCP('');
    const form = $('form-crear-producto');
    if (!$('cp-nombre').value.trim()) { mostrarErrorCP('Escribe el nombre.'); return; }
    if (!$('cp-laboratorio').value) { mostrarErrorCP('Escoge el laboratorio.'); return; }
    if (!$('cp-precio').value.trim()) { mostrarErrorCP('Escribe el precio de venta.'); return; }
    const datos = new FormData(form);
    datos.append('_csrf', csrf());
    $('cp-guardar').disabled = true;
    try {
      const json = await pedirJSON('/recepciones/api/crear-producto', { method: 'POST', body: datos });
      if (!json.ok) { mostrarErrorCP(json.error || 'No se pudo crear.'); return; }
      aviso('Producto creado: ' + json.nombre);
      modalCP.classList.add('modal-oculto');
      // Se busca por su código para que quede solo él en la lista, listo para contar
      buscador.value = json.codigo;
      await buscar(false);
      const casilla = lista.querySelector('.cnt-fila-nueva input:not([type=hidden])');
      if (casilla) casilla.focus();
    } catch (e) {
      mostrarErrorCP('Error de conexión: ' + e.message);
    } finally {
      $('cp-guardar').disabled = false;
    }
  }

  $('cp-guardar').addEventListener('click', guardarProducto);
  $('cp-cancelar').addEventListener('click', cerrarCrearProducto);
  $('cp-cerrar').addEventListener('click', cerrarCrearProducto);
  modalCP.addEventListener('click', (e) => { if (e.target === modalCP) cerrarCrearProducto(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modalCP.classList.contains('modal-oculto')) cerrarCrearProducto();
  });

  // ---------------------------------------------------------------
  // 6. BUSCADOR, FILTROS Y "CARGAR MÁS"
  // ---------------------------------------------------------------
  let espera = null;
  buscador.addEventListener('input', () => {
    clearTimeout(espera);
    espera = setTimeout(() => buscar(false), 300);   // espera a que dejes de escribir
  });
  buscador.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); clearTimeout(espera); buscar(false); }
  });

  $('conteo-filtros').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-filtro]');
    if (!b) return;
    document.querySelectorAll('#conteo-filtros button').forEach((x) => x.classList.remove('activo'));
    b.classList.add('activo');
    filtro = b.dataset.filtro;
    buscar(false);
  });

  botonMas.addEventListener('click', () => { pagina += 1; buscar(true); });

  // Arranque
  buscar(false);
})();
