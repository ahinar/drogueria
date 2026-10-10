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
      // a su primera casilla sin contar; si no tiene lotes, abre "Producto encontrado".
      if (json.exacto && productos.length === 1) {
        const casilla = lista.querySelector('input.conteo-cantidad:not([data-contado])') ||
                        lista.querySelector('input.conteo-cantidad');
        if (casilla) { casilla.focus(); casilla.select(); }
        else abrirEncontrado(productos[0]);
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

  // Producto sin ningún lote en el sistema: una fila con botón para ingresarlo
  function filaSinLotes(p) {
    return '<div class="cnt-fila cnt-sin-lotes" data-producto="' + p.id + '">' +
      '<div class="cnt-prod"><strong>' + esc(p.nombre) + (p.concentracion ? ' ' + esc(p.concentracion) : '') +
        '</strong><span class="suave"> ' + esc(p.codigo) + '</span></div>' +
      '<div class="cnt-sin-lotes-texto suave">Sin lotes en el sistema</div>' +
      '<div class="cnt-sin-lotes-accion"><button type="button" class="conteo-ingresar" data-ingresar="' + p.id +
        '">➕ Ingresar</button></div>' +
    '</div>';
  }

  function pintar() {
    if (!productos.length) {
      lista.innerHTML = '<p class="suave conteo-vacio">No hay productos para mostrar con ese filtro.</p>';
      return;
    }
    // Los productos ya llegan en orden alfabético desde el servidor
    lista.innerHTML = productos.map((p) => p.lotes.length
      ? p.lotes.map((l, i) => filaLote(p, l, i === 0)).join('')
      : filaSinLotes(p)).join('');
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
    if (caja.dataset.lote) datos.append('lote_id', caja.dataset.lote);
    else if (caja.dataset.linea) datos.append('linea_id', caja.dataset.linea);   // lote encontrado ya anotado
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
    const ingresar = e.target.closest('[data-ingresar]');
    if (ingresar) {
      abrirEncontrado(productos.find((p) => p.id === +ingresar.dataset.ingresar));
      return;
    }
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
  // 5. VENTANA "PRODUCTO ENCONTRADO"
  // ---------------------------------------------------------------
  const modal = $('modal-producto-encontrado');
  const peBuscar = $('pe-buscar');
  const peSugerencias = $('pe-sugerencias');
  const peElegido = $('pe-elegido');
  const peError = $('pe-error');
  let peProducto = null;          // producto elegido
  let peResultados = [];          // sugerencias que se están mostrando
  let peEspera = null;

  function mostrarError(texto) {
    peError.textContent = texto;
    peError.hidden = !texto;
  }

  // Abre la ventana. Si viene un producto (botón "Ingresar" o lector), queda elegido.
  function abrirEncontrado(producto) {
    $('form-producto-encontrado').reset();
    mostrarError('');
    peSugerencias.innerHTML = '';
    elegir(producto || null);
    modal.classList.remove('modal-oculto');
    (producto ? $('pe-lote') : peBuscar).focus();
  }

  function cerrarEncontrado() {
    modal.classList.add('modal-oculto');
    buscador.focus();
  }

  // Deja un producto elegido y ajusta qué campos son obligatorios
  function elegir(p) {
    peProducto = p;
    $('pe-producto-id').value = p ? p.id : '';
    peBuscar.hidden = !!p;
    peSugerencias.innerHTML = '';
    peElegido.hidden = !p;
    if (p) {
      peElegido.innerHTML = '<strong>' + esc(p.nombre) + (p.concentracion ? ' ' + esc(p.concentracion) : '') +
        '</strong> <span class="suave">' + esc(p.codigo) + '</span>' +
        ' <button type="button" class="conteo-cambiar" id="pe-cambiar">Cambiar</button>';
      $('pe-cambiar').addEventListener('click', () => { elegir(null); peBuscar.value = ''; peBuscar.focus(); });
      // Costo sugerido: el de la última compra o el de la ficha del producto
      if (p.costo_sugerido > 0) $('pe-costo').value = Math.round(p.costo_sugerido);
    }
    // Si el producto maneja lotes, lote y vencimiento son obligatorios
    const obligatorio = !!(p && p.maneja_vencimiento);
    $('pe-lote-etiqueta').textContent = obligatorio ? 'Lote *' : 'Lote (opcional)';
    $('pe-vence-etiqueta').textContent = obligatorio ? 'Vence *' : 'Vence (opcional)';
  }

  // Sugerencias mientras se escribe el nombre del producto
  async function sugerir() {
    const q = peBuscar.value.trim();
    if (q.length < 2) { peSugerencias.innerHTML = ''; return; }
    const json = await pedirJSON(URL_BUSCAR + '?q=' + encodeURIComponent(q) + '&filtro=todos');
    peResultados = json.productos.slice(0, 8);
    if (json.exacto && peResultados.length === 1) { elegir(peResultados[0]); $('pe-lote').focus(); return; }
    peSugerencias.innerHTML = peResultados.length
      ? peResultados.map((p) => '<button type="button" data-elegir="' + p.id + '">' + esc(p.nombre) +
          (p.concentracion ? ' ' + esc(p.concentracion) : '') + ' <span class="suave">' + esc(p.codigo) +
          '</span></button>').join('')
      : '<p class="suave">No se encontró. Si es un producto nuevo, créalo primero en Productos.</p>';
  }

  peBuscar.addEventListener('input', () => { clearTimeout(peEspera); peEspera = setTimeout(sugerir, 250); });
  peBuscar.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); clearTimeout(peEspera); sugerir(); }
  });
  peSugerencias.addEventListener('click', (e) => {
    const b = e.target.closest('[data-elegir]');
    if (b) { elegir(peResultados.find((p) => p.id === +b.dataset.elegir)); $('pe-lote').focus(); }
  });

  async function guardarEncontrado() {
    mostrarError('');
    if (!peProducto) { mostrarError('Primero elige el producto.'); peBuscar.focus(); return; }
    const datos = new FormData($('form-producto-encontrado'));
    $('pe-guardar').disabled = true;
    try {
      const json = await enviarConteo(datos);
      if (!json.ok) { mostrarError(json.error || 'No se pudo guardar.'); return; }
      aviso('Guardado: ' + peProducto.nombre);
      cerrarEncontrado();
      buscar(false);                             // la lista se vuelve a dibujar con el lote nuevo
    } catch (e) {
      mostrarError('Error de conexión: ' + e.message);
    } finally {
      $('pe-guardar').disabled = false;
    }
  }

  $('btn-producto-encontrado').addEventListener('click', () => abrirEncontrado(null));
  $('pe-guardar').addEventListener('click', guardarEncontrado);
  $('pe-cancelar').addEventListener('click', cerrarEncontrado);
  $('pe-cerrar').addEventListener('click', cerrarEncontrado);
  modal.addEventListener('click', (e) => { if (e.target === modal) cerrarEncontrado(); });
  // Enter en los campos del lote = Guardar
  $('form-producto-encontrado').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target !== peBuscar) { e.preventDefault(); guardarEncontrado(); }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.classList.contains('modal-oculto')) cerrarEncontrado();
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
