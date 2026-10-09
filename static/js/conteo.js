// =====================================================================
// TOMA DE INVENTARIO · pantalla de conteo
// =====================================================================
// Qué hace este archivo:
//   1. Busca productos (por nombre, código o lector de código de barras).
//   2. Dibuja cada producto con sus lotes: lo que dice el sistema y una
//      casilla para escribir lo contado.
//   3. Guarda lo contado al presionar Enter (o al salir de la casilla).
//   4. Permite agregar un lote que apareció en la estantería y no está
//      en el sistema (así se carga el inventario inicial).
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
  let productos = [];        // productos que se están mostrando
  let numeroBusqueda = 0;    // para ignorar respuestas viejas si se escribe rápido

  // ---------------------------------------------------------------
  // 3. BUSCAR
  // ---------------------------------------------------------------
  async function buscar(agregar) {
    const mio = ++numeroBusqueda;
    if (!agregar) pagina = 0;
    const url = URL_BUSCAR + '?q=' + encodeURIComponent(buscador.value.trim()) +
      '&filtro=' + filtro + '&pagina=' + pagina;
    try {
      const json = await (await fetch(url, { credentials: 'same-origin' })).json();
      if (mio !== numeroBusqueda) return;        // llegó tarde: ya hay otra búsqueda
      productos = agregar ? productos.concat(json.productos) : json.productos;
      pintar();
      pintarResumen(json.resumen);
      botonMas.hidden = !json.hay_mas;
      // Lector de código de barras: si encontró el producto exacto, va directo
      // a la primera casilla sin contar de ese producto.
      if (json.exacto && productos.length === 1) {
        const casilla = lista.querySelector('input.conteo-cantidad:not([data-contado])') ||
                        lista.querySelector('input.conteo-cantidad');
        if (casilla) { casilla.focus(); casilla.select(); }
        else abrirFormularioNuevo(productos[0].id);
      }
    } catch (e) {
      lista.innerHTML = '<p class="conteo-error">Error de conexión: ' + esc(e.message) + '</p>';
    }
  }

  // ---------------------------------------------------------------
  // 4. DIBUJAR
  // ---------------------------------------------------------------
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
    if (!linea) return '<span class="suave">—</span>';
    const d = linea.diferencia;
    if (Math.abs(d) < 1e-9) return '<span class="conteo-dif conteo-dif-ok">✓ igual</span>';
    return '<span class="conteo-dif ' + (d < 0 ? 'conteo-dif-falta' : 'conteo-dif-sobra') + '">' +
      (d > 0 ? '+' : '') + cant(d) + '</span>';
  }

  function filaLote(p, l) {
    const vencido = l.vencimiento && l.vencimiento.slice(0, 10) < HOY;
    // Si ya se contó, mostramos lo que decía el sistema AL CONTAR (es contra lo que se compara)
    const sistema = l.linea ? l.linea.sistema : l.sistema_actual;
    const etiquetaEstado = l.nuevo ? '<span class="conteo-tag conteo-tag-nuevo">nuevo</span>'
      : (l.estado !== 'disponible' && l.estado !== 'agotado'
        ? '<span class="conteo-tag">' + esc(l.estado) + '</span>' : '');
    return '<tr>' +
      '<td>' + esc(l.lote || 'Sin lote') + ' ' + etiquetaEstado + '</td>' +
      '<td class="' + (vencido ? 'conteo-vencido' : '') + '">' + fecha(l.vencimiento) + (vencido ? ' ⚠' : '') + '</td>' +
      '<td class="num">' + cant(sistema) + '</td>' +
      '<td><input type="text" inputmode="decimal" class="conteo-cantidad"' +
        ' data-producto="' + p.id + '"' +
        (l.lote_id ? ' data-lote="' + l.lote_id + '"' : '') +
        // data-guardado = lo que ya está guardado: si no lo cambias, no se vuelve a enviar
        (l.linea ? ' data-linea="' + l.linea.id + '" data-contado="1" value="' + cant(l.linea.contada) +
          '" data-guardado="' + cant(l.linea.contada) + '"' : '') +
        ' placeholder="¿cuántos?" aria-label="Cantidad contada del lote ' + esc(l.lote || '') + '"></td>' +
      '<td class="conteo-celda-dif">' + etiquetaDiferencia(l.linea) + '</td>' +
      '<td>' + (l.linea ? '<button type="button" class="conteo-quitar" data-linea="' + l.linea.id +
        '" title="Borrar lo contado de este lote">✕</button>' : '') + '</td>' +
      '</tr>';
  }

  function tarjetaProducto(p) {
    const filas = p.lotes.map((l) => filaLote(p, l)).join('');
    const sinLotes = !p.lotes.length;
    return '<div class="conteo-producto" data-id="' + p.id + '">' +
      '<div class="conteo-producto-cab">' +
        '<div><strong>' + esc(p.nombre) + (p.concentracion ? ' ' + esc(p.concentracion) : '') + '</strong>' +
        '<span class="suave"> · ' + esc(p.codigo) + (p.codigo_barras ? ' · ' + esc(p.codigo_barras) : '') + '</span></div>' +
        '<button type="button" class="conteo-agregar" data-agregar="' + p.id + '">+ Lote encontrado</button>' +
      '</div>' +
      (sinLotes
        ? '<p class="suave conteo-sin-lotes">No tiene lotes en el sistema. Si lo tienes en la estantería, usa "+ Lote encontrado".</p>'
        : '<table class="conteo-tabla"><thead><tr><th>Lote</th><th>Vence</th><th class="num">Sistema</th>' +
          '<th>Contado</th><th>Dif.</th><th></th></tr></thead><tbody>' + filas + '</tbody></table>') +
      // Formulario para un lote nuevo (oculto hasta que se toca "+ Lote encontrado")
      '<form class="conteo-form-nuevo" data-producto="' + p.id + '" hidden>' +
        '<label>Lote' + (p.maneja_vencimiento ? ' *' : '') +
          '<input type="text" name="lote" maxlength="40"' + (p.maneja_vencimiento ? ' required' : ' placeholder="Opcional"') + '></label>' +
        '<label>Vence' + (p.maneja_vencimiento ? ' *' : '') +
          '<input type="date" name="vencimiento"' + (p.maneja_vencimiento ? ' required' : '') + '></label>' +
        '<label>Costo unitario *<input type="text" inputmode="decimal" name="costo" value="' +
          (p.costo_sugerido > 0 ? Math.round(p.costo_sugerido) : '') + '" required></label>' +
        '<label>Cantidad *<input type="text" inputmode="decimal" name="cantidad" required></label>' +
        '<button type="submit" class="boton">Guardar</button>' +
        '<button type="button" class="boton secundario" data-cancelar>Cancelar</button>' +
      '</form>' +
    '</div>';
  }

  function pintar() {
    if (!productos.length) {
      lista.innerHTML = '<p class="suave conteo-vacio">No hay productos para mostrar con ese filtro.</p>';
      return;
    }
    lista.innerHTML = productos.map(tarjetaProducto).join('');
  }

  // Vuelve a pedir y dibujar SOLO un producto (después de guardar un lote nuevo o quitar)
  async function refrescarProducto(id) {
    const p = productos.find((x) => x.id === id);
    if (!p) return;
    const url = URL_BUSCAR + '?q=' + encodeURIComponent(p.codigo) + '&filtro=todos';
    const json = await (await fetch(url, { credentials: 'same-origin' })).json();
    const nuevo = json.productos.find((x) => x.id === id);
    if (!nuevo) return;
    productos[productos.indexOf(p)] = nuevo;
    const tarjeta = lista.querySelector('.conteo-producto[data-id="' + id + '"]');
    if (tarjeta) tarjeta.outerHTML = tarjetaProducto(nuevo);
    pintarResumen(json.resumen);
  }

  // ---------------------------------------------------------------
  // 5. GUARDAR LO CONTADO
  // ---------------------------------------------------------------
  async function enviar(datos) {
    datos.append('_csrf', csrf());
    const resp = await fetch(URL_CONTAR, { method: 'POST', body: datos, credentials: 'same-origin' });
    return resp.json();
  }

  async function guardarCasilla(input) {
    const valor = input.value.trim();
    if (valor === '' || valor === input.dataset.guardado) return;   // vacío o sin cambios
    const datos = new FormData();
    datos.append('cantidad', valor);
    if (input.dataset.lote) datos.append('lote_id', input.dataset.lote);
    else if (input.dataset.linea) datos.append('linea_id', input.dataset.linea);   // lote nuevo ya anotado
    input.classList.add('guardando');
    // Lo marcamos como guardado ANTES de enviar: así, si Enter y "salir de la
    // casilla" ocurren casi juntos, no se envía dos veces.
    const anterior = input.dataset.guardado;
    input.dataset.guardado = valor;
    try {
      const json = await enviar(datos);
      if (!json.ok) {
        input.dataset.guardado = anterior || '';
        aviso(json.error || 'No se pudo guardar.', true);
        input.classList.add('con-error');
        return;
      }
      input.classList.remove('con-error');
      input.dataset.contado = '1';
      input.dataset.linea = json.linea.id;
      // Actualizamos en la fila: sistema al contar, diferencia y botón de quitar
      const fila = input.closest('tr');
      fila.querySelector('.num').textContent = cant(json.linea.sistema);
      fila.querySelector('.conteo-celda-dif').innerHTML = etiquetaDiferencia(json.linea);
      fila.lastElementChild.innerHTML = '<button type="button" class="conteo-quitar" data-linea="' +
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

  // ---------------------------------------------------------------
  // 6. LOTE ENCONTRADO, QUITAR Y CANCELAR
  // ---------------------------------------------------------------
  function abrirFormularioNuevo(productoId) {
    const form = lista.querySelector('.conteo-form-nuevo[data-producto="' + productoId + '"]');
    if (!form) return;
    form.hidden = false;
    form.querySelector('input').focus();
  }

  lista.addEventListener('click', async (e) => {
    const agregar = e.target.closest('[data-agregar]');
    if (agregar) { abrirFormularioNuevo(agregar.dataset.agregar); return; }

    if (e.target.closest('[data-cancelar]')) { e.target.closest('form').hidden = true; return; }

    const quitar = e.target.closest('.conteo-quitar');
    if (quitar) {
      if (!confirm('¿Borrar lo contado de este lote?')) return;
      const datos = new FormData();
      datos.append('linea_id', quitar.dataset.linea);
      datos.append('_csrf', csrf());
      const json = await (await fetch(URL_QUITAR, { method: 'POST', body: datos, credentials: 'same-origin' })).json();
      if (!json.ok) { aviso(json.error || 'No se pudo borrar.', true); return; }
      await refrescarProducto(+quitar.closest('.conteo-producto').dataset.id);
    }
  });

  lista.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const datos = new FormData(form);
    datos.append('producto_id', form.dataset.producto);
    const json = await enviar(datos);
    if (!json.ok) { aviso(json.error || 'No se pudo guardar.', true); return; }
    aviso('Lote guardado.');
    await refrescarProducto(+form.dataset.producto);
  });

  // ---------------------------------------------------------------
  // 7. BUSCADOR, FILTROS Y "CARGAR MÁS"
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
