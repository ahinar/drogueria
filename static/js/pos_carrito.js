// =====================================================================
// POS · CARRITO DE VENTAS
// =====================================================================
// Controla la pantalla de venta:
//   1. Buscar productos (por nombre o escaneando el código de barras)
//   2. Armar el carrito (agregar, cambiar cantidad, descuento, quitar)
//   3. Cobrar (efectivo, Nequi, Davivienda, tarjeta)
//   4. Atajos de teclado físico (números, backspace, delete, +, -, Enter)
//   5. Registrar gastos sin salir del POS
// =====================================================================
(function () {
  'use strict';

  // ---------------------------------------------------------------
  // 1. ESTADO
  // ---------------------------------------------------------------
  let carrito = [];
  let seleccionado = -1;
  let modo = 'cantidad';         // 'cantidad' o 'descuento'
  let buffer = '';
  let escribiendo = false;
  let categoria = '';
  let productosMostrados = [];
  let numeroBusqueda = 0;
  let formaPago = 'efectivo';
  let cliente = { nombre: '', documento: '' };
  let nota = '';
  let cobrando = false;

  // ---------------------------------------------------------------
  // 2. AYUDAS
  // ---------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const peso = (n) => '$' + Math.round(n).toLocaleString('es-CO');
  const aPesos = (v) => Math.floor(v + 0.5);
  const csrf = () => (document.querySelector('input[name="_csrf"]') || {}).value || '';

  function esc(texto) {
    return String(texto == null ? '' : texto)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function aviso(texto) {
    const div = document.createElement('div');
    div.className = 'pos-toast';
    div.textContent = texto;
    document.body.appendChild(div);
    setTimeout(() => div.remove(), 3000);
  }

  const URL = {
    productos: $('url-api-productos') && $('url-api-productos').value,
    cobrar: $('url-api-cobrar') && $('url-api-cobrar').value,
    gasto: $('url-api-gasto') && $('url-api-gasto').value,
    ventas: $('url-ventas') && $('url-ventas').value,
    ultima: $('url-ultima-venta') && $('url-ultima-venta').value,
    inventario: $('url-inventario') && $('url-inventario').value,
    estaticos: ($('url-static-base') && $('url-static-base').value) || '/static/',
  };
  if (!URL.productos || !URL.cobrar) return;

  const inputBusqueda = $('pos-input-busqueda');
  const grid = $('pos-grid');
  const contenedorCarrito = $('pos-carrito-items');
  const btnPago = $('btn-pago');

  // ---------------------------------------------------------------
  // 3. CÁLCULO DE UNA LÍNEA
  // ---------------------------------------------------------------
  function calcularLinea(it) {
    const bruto = it.cantidad * it.precio;
    const descuento = aPesos(bruto * it.descuento_pct / 100);
    const total = aPesos(bruto) - descuento;
    let base = total, iva = 0;
    if (it.iva_tipo === 'gravado' && it.iva_tarifa > 0) {
      base = aPesos(total / (1 + it.iva_tarifa / 100));
      iva = total - base;
    }
    return { descuento, total, base, iva };
  }

  // ---------------------------------------------------------------
  // 4. BUSCAR PRODUCTOS
  // ---------------------------------------------------------------
  async function buscar(desdeEnter) {
    const miNumero = ++numeroBusqueda;
    const q = inputBusqueda.value.trim();
    const url = URL.productos + '?q=' + encodeURIComponent(q) + '&cat=' + encodeURIComponent(categoria);
    try {
      const resp = await fetch(url, { credentials: 'same-origin' });
      const json = await resp.json();
      if (miNumero !== numeroBusqueda || !json.ok) return;
      productosMostrados = json.productos;
      pintarProductos();
      if (desdeEnter) {
        if (json.productos.length === 1) {
          agregar(json.productos[0]);
          inputBusqueda.value = '';
          buscar(false);
        } else if (json.productos.length === 0) {
          aviso('No se encontró ningún producto.');
        }
      }
    } catch (e) {
      aviso('No se pudo buscar: ' + e.message);
    }
  }

  function pintarProductos() {
    if (!productosMostrados.length) {
      grid.innerHTML = '<p class="suave" style="padding:2rem;text-align:center;grid-column:1/-1">No hay productos para mostrar.</p>';
      return;
    }
    grid.innerHTML = productosMostrados.map((p) => {
      const agotado = p.stock <= 0;
      const imagen = p.imagen
        ? '<img src="' + esc(URL.estaticos + p.imagen) + '" alt="">'
        : '<span class="pos-card-img-vacia">💊</span>';
      const etiquetas =
        (p.control_especial ? ' 🔒' : '') + (p.requiere_formula ? ' 📋' : '');
      return '<div class="pos-card' + (agotado ? ' agotado' : '') + '" data-id="' + p.id + '">' +
        '<div class="pos-card-img">' + imagen + '</div>' +
        '<div class="pos-card-info">' +
          '<div class="pos-card-nombre">' + esc(p.nombre) + esc(etiquetas) + '</div>' +
          '<div class="pos-card-codigo">' + esc(p.concentracion || p.codigo) + '</div>' +
          '<div class="pos-card-stock">' + (agotado ? 'Agotado' : 'Stock: ' + (+p.stock.toFixed(2))) + '</div>' +
          '<div class="pos-card-precio">' + peso(p.precio) + '</div>' +
        '</div></div>';
    }).join('');
  }

  // ---------------------------------------------------------------
  // 5. CARRITO
  // ---------------------------------------------------------------
  function agregar(prod) {
    if (prod.control_especial) {
      aviso('Medicamento de control especial: aún no se puede vender desde el POS.');
      return;
    }
    if (prod.stock <= 0) { aviso('Producto agotado.'); return; }

    let pos = carrito.findIndex((i) => i.producto_id === prod.id);
    if (pos >= 0) {
      if (carrito[pos].cantidad + 1 > prod.stock) {
        aviso('Solo hay ' + (+prod.stock.toFixed(2)) + ' disponible(s).');
      } else {
        carrito[pos].cantidad += 1;
      }
    } else {
      carrito.push({
        producto_id: prod.id, codigo: prod.codigo, nombre: prod.nombre,
        concentracion: prod.concentracion, precio: prod.precio,
        iva_tipo: prod.iva_tipo, iva_tarifa: prod.iva_tarifa,
        requiere_formula: prod.requiere_formula,
        stock: prod.stock, cantidad: 1, descuento_pct: 0,
      });
      pos = carrito.length - 1;
      if (prod.requiere_formula) aviso('📋 Requiere fórmula médica: verifícala antes de entregar.');
    }
    seleccionar(pos);
    pintarCarrito();
  }

  function seleccionar(pos) {
    seleccionado = pos;
    escribiendo = false;
    buffer = '';
  }

  function pintarCarrito() {
    if (!carrito.length) {
      contenedorCarrito.innerHTML =
        '<p class="suave" style="text-align:center;padding:2rem 1rem">Carrito vacío.<br>Busca un producto para comenzar.</p>';
    } else {
      contenedorCarrito.innerHTML = carrito.map((it, i) => {
        const l = calcularLinea(it);
        const detalle = [
          it.concentracion,
          peso(it.precio) + ' c/u',
          it.descuento_pct > 0 ? 'desc. ' + it.descuento_pct + '%' : '',
          it.requiere_formula ? '📋 fórmula' : '',
        ].filter(Boolean).join(' · ');
        return '<div class="pos-item' + (i === seleccionado ? ' seleccionado' : '') + '" data-idx="' + i + '">' +
          '<div><div class="pos-item-nombre">' + esc(it.nombre) + '</div>' +
          '<div class="pos-item-presentacion">' + esc(detalle) + '</div></div>' +
          '<div class="pos-item-precio">' + peso(l.total) + '</div>' +
          '<div class="pos-item-cant">' +
            '<button type="button" data-a="menos">−</button>' +
            '<span>' + (+it.cantidad.toFixed(2)) + '</span>' +
            '<button type="button" data-a="mas">+</button></div>' +
          '<div class="pos-item-acciones"><button type="button" class="pos-item-eliminar" data-a="eliminar" title="Quitar">🗑</button></div>' +
          '</div>';
      }).join('');
    }

    let subtotal = 0, descuento = 0, iva = 0, total = 0;
    carrito.forEach((it) => {
      const l = calcularLinea(it);
      subtotal += l.base; descuento += l.descuento; iva += l.iva; total += l.total;
    });
    $('pos-subtotal').textContent = peso(subtotal);
    $('pos-descuento').textContent = peso(descuento);
    $('pos-iva').textContent = peso(iva);
    $('pos-total').textContent = peso(total);
    btnPago.disabled = carrito.length === 0;
    btnPago.textContent = carrito.length ? '💵 PAGO ' + peso(total) : '💵 PAGO';
  }

  function totalVenta() {
    return carrito.reduce((suma, it) => suma + calcularLinea(it).total, 0);
  }

  contenedorCarrito.addEventListener('click', (e) => {
    const fila = e.target.closest('.pos-item');
    if (!fila) return;
    const pos = +fila.dataset.idx;
    const it = carrito[pos];
    const accion = e.target.dataset.a;
    if (accion === 'mas') {
      if (it.cantidad + 1 > it.stock) aviso('Solo hay ' + (+it.stock.toFixed(2)) + ' disponible(s).');
      else it.cantidad += 1;
    } else if (accion === 'menos') {
      if (it.cantidad > 1) it.cantidad -= 1;
    } else if (accion === 'eliminar') {
      carrito.splice(pos, 1);
      seleccionado = -1;
      pintarCarrito();
      return;
    }
    seleccionar(pos);
    pintarCarrito();
    inputBusqueda.blur();   // <-- CLAVE: quitar el foco del buscador
  });

  // Al hacer clic en cualquier parte del carrito, quitamos el foco del buscador
  contenedorCarrito.addEventListener('mousedown', () => inputBusqueda.blur());

  // ---------------------------------------------------------------
  // 6. TECLADO NUMÉRICO
  // ---------------------------------------------------------------
  function marcarModo() {
    document.querySelectorAll('.pos-numpad-accion').forEach((b) => {
      b.classList.toggle('activo', b.dataset.key === modo);
    });
  }

  function teclear(tecla) {
    if (tecla === 'cantidad' || tecla === 'descuento') {
      modo = tecla; escribiendo = false; buffer = ''; marcarModo(); return;
    }
    if (tecla === 'precio') {
      aviso('El precio lo define el producto; no se cambia al vender.');
      return;
    }
    if (tecla === 'borrar-todo') {
      if (carrito.length && confirm('¿Vaciar el carrito?')) {
        carrito = []; seleccionado = -1; pintarCarrito();
      }
      return;
    }
    const it = carrito[seleccionado];
    if (!it) { aviso('Primero toca un producto del carrito.'); return; }

    let texto = escribiendo ? buffer : '';
    if (tecla === 'borrar') texto = texto.slice(0, -1);
    else if (tecla === '.') { if (!texto.includes('.')) texto += (texto === '' ? '0' : '') + '.'; }
    else texto += tecla;
    escribiendo = true;
    buffer = texto;

    let valor = parseFloat(texto) || 0;
    if (modo === 'cantidad') {
      if (valor > it.stock) {
        valor = it.stock; buffer = String(valor);
        aviso('Solo hay ' + (+it.stock.toFixed(2)) + ' disponible(s).');
      }
      it.cantidad = valor;
    } else {
      if (valor > 100) { valor = 100; buffer = '100'; }
      it.descuento_pct = valor;
    }
    pintarCarrito();
  }

  document.querySelectorAll('.pos-numpad button').forEach((b) => {
    // Al hacer clic en un botón del numpad, quitar foco del buscador
    b.addEventListener('mousedown', () => inputBusqueda.blur());
    b.addEventListener('click', () => teclear(b.dataset.key));
  });
  marcarModo();

  // ---------------------------------------------------------------
  // 6b. TECLADO FÍSICO GLOBAL
  // ---------------------------------------------------------------
  // Si el foco NO está en un input, capturamos las teclas y las
  // dirigimos al carrito/numpad. Esto permite usar el teclado numérico
  // físico sin que el texto vaya a la barra de búsqueda.
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    const key = e.key;

    // F2 = cobrar · F3 = enfocar buscador
    if (key === 'F2') { e.preventDefault(); if (carrito.length) abrirPago(); return; }
    if (key === 'F3') { e.preventDefault(); inputBusqueda.focus(); return; }

    // Enter = cobrar
    if (key === 'Enter') { e.preventDefault(); if (carrito.length) abrirPago(); return; }

    // Escape = deseleccionar
    if (key === 'Escape') {
      seleccionado = -1; pintarCarrito();
      document.querySelectorAll('.modal-oculto').forEach(m => {});
      return;
    }

    // Backspace = borrar dígito o reducir cantidad
    if (key === 'Backspace') {
      e.preventDefault();
      const it = carrito[seleccionado];
      if (escribiendo && buffer) {
        // Borrar último dígito del número que se está escribiendo
        buffer = buffer.slice(0, -1);
        if (it) {
          let valor = parseFloat(buffer) || 0;
          if (modo === 'cantidad') it.cantidad = Math.max(1, valor);
          else it.descuento_pct = Math.min(100, Math.max(0, valor));
        }
        pintarCarrito();
      } else if (it) {
        // Reducir cantidad. Si queda en 0, preguntar para eliminar.
        if (it.cantidad > 1) {
          it.cantidad -= 1;
          pintarCarrito();
        } else if (confirm('¿Quitar "' + it.nombre + '" del carrito?')) {
          carrito.splice(seleccionado, 1);
          seleccionado = -1;
          pintarCarrito();
        }
      }
      return;
    }

    // Delete / Supr = eliminar producto seleccionado
    if (key === 'Delete') {
      e.preventDefault();
      const it = carrito[seleccionado];
      if (it && confirm('¿Quitar "' + it.nombre + '" del carrito?')) {
        carrito.splice(seleccionado, 1);
        seleccionado = -1;
        pintarCarrito();
      }
      return;
    }

    // + = aumentar cantidad
    if (key === '+' || key === '=') {
      e.preventDefault();
      const it = carrito[seleccionado];
      if (it) {
        if (it.cantidad + 1 > it.stock) aviso('Solo hay ' + (+it.stock.toFixed(2)) + ' disponible(s).');
        else { it.cantidad += 1; pintarCarrito(); }
      }
      return;
    }

    // - = disminuir cantidad
    if (key === '-' || key === '_') {
      e.preventDefault();
      const it = carrito[seleccionado];
      if (it && it.cantidad > 1) { it.cantidad -= 1; pintarCarrito(); }
      return;
    }

    // Números y punto = ir al numpad
    if (/^[0-9]$/.test(key) || key === '.' || key === ',') {
      e.preventDefault();
      teclear(key === ',' ? '.' : key);
      return;
    }
  });

  // ---------------------------------------------------------------
  // 7. COBRAR
  // ---------------------------------------------------------------
  const modalPago = $('modal-pago');

  function abrirPago() {
    if (carrito.some((i) => !(i.cantidad > 0))) {
      aviso('Hay un producto con cantidad 0. Corrígelo o quítalo.');
      return;
    }
    if (!carrito.length) return;
    $('pago-total').textContent = peso(totalVenta());
    $('pago-form').style.display = '';
    $('pago-exito').style.display = 'none';
    $('pago-error').style.display = 'none';
    $('pago-recibido').value = '';
    elegirForma('efectivo');
    actualizarCambio();
    modalPago.classList.remove('modal-oculto');
    $('pago-recibido').focus();
  }

  function cerrarPago() { modalPago.classList.add('modal-oculto'); inputBusqueda.focus(); }

  function elegirForma(forma) {
    formaPago = forma;
    document.querySelectorAll('.pos-pago-metodo').forEach((b) => {
      b.classList.toggle('activo', b.dataset.forma === forma);
    });
    $('pago-efectivo').style.display = forma === 'efectivo' ? '' : 'none';
  }

  function actualizarCambio() {
    const recibido = parseFloat($('pago-recibido').value);
    const cambio = isNaN(recibido) ? 0 : recibido - totalVenta();
    $('pago-cambio').textContent = cambio >= 0 ? peso(cambio) : 'Falta ' + peso(-cambio);
  }

  async function confirmarVenta() {
    if (cobrando) return;
    const errorBox = $('pago-error');
    errorBox.style.display = 'none';

    const datos = new FormData();
    datos.append('_csrf', csrf());
    datos.append('carrito', JSON.stringify(carrito.map((i) => ({
      producto_id: i.producto_id, cantidad: i.cantidad, descuento_pct: i.descuento_pct,
    }))));
    datos.append('forma_pago', formaPago);
    if (formaPago === 'efectivo') datos.append('monto_recibido', $('pago-recibido').value);
    datos.append('cliente_nombre', cliente.nombre);
    datos.append('cliente_documento', cliente.documento);
    datos.append('observaciones', nota);

    cobrando = true;
    $('pago-confirmar').disabled = true;
    try {
      const resp = await fetch(URL.cobrar, { method: 'POST', body: datos, credentials: 'same-origin' });
      const json = await resp.json();
      if (!json.ok) {
        errorBox.textContent = json.error || 'No se pudo registrar la venta.';
        errorBox.style.display = 'block';
        buscar(false);
        return;
      }
      $('exito-consecutivo').textContent = json.consecutivo + ' · ' + peso(json.total);
      $('exito-cambio').textContent = peso(json.cambio);
      $('exito-cambio-linea').style.display = json.cambio > 0 ? '' : 'none';
      $('exito-comprobante').href = json.url_comprobante;
      $('pago-form').style.display = 'none';
      $('pago-exito').style.display = '';
      carrito = []; seleccionado = -1; cliente = { nombre: '', documento: '' }; nota = '';
      pintarCarrito();
      buscar(false);
    } catch (e) {
      errorBox.textContent = 'Error de conexión: ' + e.message;
      errorBox.style.display = 'block';
    } finally {
      cobrando = false;
      $('pago-confirmar').disabled = false;
    }
  }

  btnPago.addEventListener('click', abrirPago);
  $('pago-cancelar').addEventListener('click', cerrarPago);
  $('pago-confirmar').addEventListener('click', confirmarVenta);
  $('exito-nueva').addEventListener('click', cerrarPago);
  $('pago-recibido').addEventListener('input', actualizarCambio);
  document.querySelectorAll('.pos-pago-metodo').forEach((b) => {
    b.addEventListener('click', () => elegirForma(b.dataset.forma));
  });
  $('pago-rapidos').addEventListener('click', (e) => {
    const monto = e.target.dataset.monto;
    if (!monto) return;
    $('pago-recibido').value = monto === 'exacto' ? totalVenta() : monto;
    actualizarCambio();
  });

  // ---------------------------------------------------------------
  // 8. CLIENTE, NOTA, MENÚ LATERAL Y GASTO
  // ---------------------------------------------------------------
  function pedirCliente() {
    const nombre = prompt('Nombre del cliente (vacío = Consumidor final):', cliente.nombre);
    if (nombre === null) return;
    const doc = prompt('Documento del cliente (opcional):', cliente.documento);
    cliente = { nombre: nombre.trim(), documento: (doc || '').trim() };
    aviso(cliente.nombre ? 'Cliente: ' + cliente.nombre : 'Consumidor final');
  }
  function pedirNota() {
    const texto = prompt('Nota de la venta:', nota);
    if (texto !== null) nota = texto.trim();
  }
  $('btn-cliente').addEventListener('click', pedirCliente);
  $('btn-nota').addEventListener('click', pedirNota);

  // ----- Modal de gasto -----
  const modalGasto = $('modal-gasto');
  const formGasto = $('form-gasto');
  const gastoError = $('gasto-error');
  const gastoFormaPago = $('gasto-forma-pago');
  const gastoOrigenWrap = $('gasto-origen-wrap');

  function abrirModalGasto() {
    if (!modalGasto) return;
    formGasto.reset();
    gastoError.style.display = 'none';
    gastoOrigenWrap.style.display = '';
    modalGasto.classList.remove('modal-oculto');
    setTimeout(() => {
      const primero = formGasto.querySelector('select');
      if (primero) primero.focus();
    }, 50);
  }

  function cerrarModalGasto() {
    if (modalGasto) modalGasto.classList.add('modal-oculto');
  }

  if (gastoFormaPago) {
    gastoFormaPago.addEventListener('change', function () {
      const esEfectivo = gastoFormaPago.value === 'efectivo';
      gastoOrigenWrap.style.display = esEfectivo ? '' : 'none';
    });
  }

  if ($('gasto-cancelar')) {
    $('gasto-cancelar').addEventListener('click', cerrarModalGasto);
  }
  if (modalGasto) {
    modalGasto.addEventListener('click', (e) => {
      if (e.target === modalGasto) cerrarModalGasto();
    });
  }

  if ($('gasto-guardar')) {
    $('gasto-guardar').addEventListener('click', async function () {
      const datos = new FormData(formGasto);
      datos.append('_csrf', csrf());
      // Si la forma no es efectivo, forzamos origen="ninguna"
      if (gastoFormaPago.value !== 'efectivo') {
        datos.set('origen', 'ninguna');
      }
      gastoError.style.display = 'none';
      try {
        const resp = await fetch(URL.gasto, { method: 'POST', body: datos, credentials: 'same-origin' });
        const json = await resp.json();
        if (!json.ok) {
          gastoError.textContent = json.error || 'No se pudo guardar.';
          gastoError.style.display = 'block';
          return;
        }
        cerrarModalGasto();
        aviso('Gasto registrado.');
      } catch (e) {
        gastoError.textContent = 'Error: ' + e.message;
        gastoError.style.display = 'block';
      }
    });
  }

  document.querySelectorAll('.pos-drawer-item').forEach((b) => {
    b.addEventListener('click', () => {
      const accion = b.dataset.accion;
      const cerrar = () => { const d = $('pos-drawer'); if (d) d.setAttribute('hidden', ''); };
      if (accion === 'ultimas-ventas') window.location.href = URL.ventas;
      else if (accion === 'reimprimir') window.open(URL.ultima, '_blank');
      else if (accion === 'consulta-inventario') window.location.href = URL.inventario;
      else if (accion === 'cliente') { cerrar(); pedirCliente(); }
      else if (accion === 'nota') { cerrar(); pedirNota(); }
      else if (accion === 'registrar-gasto') { cerrar(); abrirModalGasto(); }
    });
  });

  // ---------------------------------------------------------------
  // 9. ARRANQUE
  // ---------------------------------------------------------------
  let temporizador = null;
  inputBusqueda.addEventListener('input', () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(() => buscar(false), 250);
  });
  inputBusqueda.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); clearTimeout(temporizador); buscar(true); }
  });

  grid.addEventListener('click', (e) => {
    const tarjeta = e.target.closest('.pos-card');
    if (!tarjeta) return;
    const prod = productosMostrados.find((p) => p.id === +tarjeta.dataset.id);
    if (prod) agregar(prod);
    inputBusqueda.focus();
  });

  $('pos-categorias').addEventListener('click', (e) => {
    const boton = e.target.closest('.pos-cat');
    if (!boton) return;
    document.querySelectorAll('.pos-cat').forEach((b) => b.classList.remove('activo'));
    boton.classList.add('activo');
    categoria = boton.dataset.cat;
    buscar(false);
  });

  pintarCarrito();
  buscar(false);
})();
