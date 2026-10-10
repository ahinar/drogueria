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
  function etiquetaDiferencia(linea) {
    if (!linea) return '';
    const d = linea.diferencia;
    if (Math.abs(d) < 1e-9) return '<span class="conteo-dif conteo-dif-ok">✓</span>';
    return '<span class="conteo-dif ' + (d < 0 ? 'conteo-dif-falta' : 'conteo-dif-sobra') + '">' +
      (d > 0 ? '+' : '') + cant(d) + '</span>';
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
          '<span class="suave"> ' + esc(p.codigo) + ' · se cuenta en ' + esc(p.unidad || 'unidades') + '</span>'
        : '') + '</div>' +
      '<div class="cnt-lote"><span class="cnt-etq">Lote </span>' + esc(l.lote || 'Sin lote') + etiqueta + '</div>' +
      '<div class="cnt-vence' + (vencido ? ' conteo-vencido' : '') + '"><span class="cnt-etq">Vence </span>' +
        fecha(l.vencimiento) + (vencido ? ' ⚠' : '') + '</div>' +
      '<div class="cnt-sistema num"><span class="cnt-etq">Sistema </span><b>' + cant(sistema) + '</b></div>' +
      '<div class="cnt-contado"><input type="text" inputmode="decimal" class="conteo-cantidad"' +
        (l.lote_id ? ' data-lote="' + l.lote_id + '"' : '') +
        // data-guardado = lo ya guardado: si no lo cambias, no se vuelve a enviar
        (l.linea ? ' data-linea="' + l.linea.id + '" data-contado="1" value="' + cant(l.linea.contada) +
          '" data-guardado="' + cant(l.linea.contada) + '"' : '') +
        ' placeholder="¿cuántos?" aria-label="Contado de ' + esc(p.nombre) + ' lote ' + esc(l.lote || '') + '"></div>' +
      '<div class="cnt-dif">' + etiquetaDiferencia(l.linea) + '</div>' +
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

  async function guardarCasilla(input) {
    const valor = input.value.trim();
    if (valor === '' || valor === input.dataset.guardado) return;   // vacío o sin cambios
    const datos = new FormData();
    datos.append('cantidad', valor);
    if (input.dataset.lote) datos.append('lote_id', input.dataset.lote);
    else if (input.dataset.linea) datos.append('linea_id', input.dataset.linea);   // lote encontrado ya anotado
    input.classList.add('guardando');
    // Se marca como guardado ANTES de enviar: así, si Enter y "salir de la
    // casilla" ocurren casi juntos, no se envía dos veces.
    const anterior = input.dataset.guardado;
    input.dataset.guardado = valor;
    try {
      const json = await enviarConteo(datos);
      if (!json.ok) {
        input.dataset.guardado = anterior || '';
        aviso(json.error || 'No se pudo guardar.', true);
        input.classList.add('con-error');
        return;
      }
      input.classList.remove('con-error');
      input.dataset.contado = '1';
      input.dataset.linea = json.linea.id;
      // Se actualiza la fila: sistema al contar, diferencia y botón de quitar
      const fila = input.closest('.cnt-fila');
      fila.querySelector('.cnt-sistema b').textContent = cant(json.linea.sistema);
      fila.querySelector('.cnt-dif').innerHTML = etiquetaDiferencia(json.linea);
      fila.querySelector('.cnt-quitar').innerHTML = '<button type="button" class="conteo-quitar" data-linea="' +
        json.linea.id + '" title="Borrar lo contado de este lote">✕</button>';
      pintarResumen(json.resumen);
    } catch (e) {
      input.dataset.guardado = anterior || '';
      aviso('Error de conexión: ' + e.message, true);
    } finally {
      input.classList.remove('guardando');
    }
  }

  // Enter = guardar y pasar a la siguiente casilla
  lista.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !e.target.classList.contains('conteo-cantidad')) return;
    e.preventDefault();
    const casillas = [...lista.querySelectorAll('input.conteo-cantidad')];
    const siguiente = casillas[casillas.indexOf(e.target) + 1];
    guardarCasilla(e.target);
    if (siguiente) { siguiente.focus(); siguiente.select(); }
    else { buscador.focus(); buscador.select(); }   // último lote: volver al buscador
  });
  // Salir de la casilla también guarda
  lista.addEventListener('focusout', (e) => {
    if (e.target.classList.contains('conteo-cantidad')) guardarCasilla(e.target);
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
