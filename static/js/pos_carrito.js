// =====================================================================
// POS · CARRITO DE VENTAS
// =====================================================================
// Controla la pantalla de venta:
//   1. Buscar productos (por nombre o escaneando el código de barras)
//   2. Armar el carrito (agregar, cambiar cantidad, descuento, quitar)
//   3. Ver info detallada de un producto (botón "i")
//   4. Cambiar el precio al vender (Opción B: todos pueden, queda en bitácora)
//   5. Cobrar (efectivo, Nequi, Davivienda, tarjeta)
//   6. Atajos de teclado físico (números, backspace, delete, +, -, Enter)
//   7. Registrar gastos sin salir del POS
//   8. Carrito persistente (no se pierde al navegar o cerrar)
// =====================================================================
(function () {
  'use strict';

  // ---------------------------------------------------------------
  // 1. ESTADO
  // ---------------------------------------------------------------
  let carrito = [];
  let seleccionado = -1;
  let modo = 'cantidad';         // 'cantidad', 'descuento' o 'precio'
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
    productoInfo: ($('url-api-producto-info') && $('url-api-producto-info').value) || '/pos/api/producto/',
    productoEditar: ($('url-producto-editar') && $('url-producto-editar').value) || '/productos/',
  };
  if (!URL.productos || !URL.cobrar) return;

  const CAJA_ID = ($('pos-caja-id') && $('pos-caja-id').value) || 'default';
  const CLAVE_CARRITO = 'pos_carrito_caja_' + CAJA_ID;

  // Limpieza: borrar carritos de cajas anteriores
  try {
    const aBorrar = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith('pos_carrito_caja_') && k !== CLAVE_CARRITO) {
        aBorrar.push(k);
      }
    }
    aBorrar.forEach(k => localStorage.removeItem(k));
  } catch (e) { /* silencio */ }

  // Cargar carrito guardado
  try {
    const guardado = localStorage.getItem(CLAVE_CARRITO);
    if (guardado) carrito = JSON.parse(guardado) || [];
  } catch (e) { carrito = []; }

  function guardarCarrito() {
    try { localStorage.setItem(CLAVE_CARRITO, JSON.stringify(carrito)); } catch (e) {}
  }
  function limpiarCarrito() {
    carrito = [];
    seleccionado = -1;
    try { localStorage.removeItem(CLAVE_CARRITO); } catch (e) {}
  }

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
        '<button type="button" class="pos-card-info-btn" data-info-id="' + p.id + '" title="Ver información del producto">i</button>' +
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
        // Actualizar stock real por si cambió
        carrito[pos].stock = prod.stock;
      }
    } else {
      carrito.push({
        producto_id: prod.id, codigo: prod.codigo, nombre: prod.nombre,
        concentracion: prod.concentracion, precio: prod.precio,
        precio_original: prod.precio, motivo_precio: null,
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
        const cambioPrecio = it.precio_original != null && Math.abs(it.precio - it.precio_original) > 0.01;
        const badgePrecio = cambioPrecio
          ? '<span class="pos-item-badge-precio" title="Precio editado: era ' + peso(it.precio_original) + '">✏️ precio editado</span>'
          : '';
        return '<div class="pos-item' + (i === seleccionado ? ' seleccionado' : '') + '" data-idx="' + i + '">' +
          '<div><div class="pos-item-nombre">' + esc(it.nombre) + '</div>' +
          '<div class="pos-item-presentacion">' + esc(detalle) + '</div>' + badgePrecio + '</div>' +
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
    guardarCarrito();
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
    inputBusqueda.blur();
  });

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
    if (tecla === 'cantidad' || tecla === 'descuento' || tecla === 'precio') {
      modo = tecla;
      escribiendo = false;
      buffer = '';
      marcarModo();
      return;
    }
    if (tecla === 'borrar-todo') {
      if (carrito.length && confirm('¿Vaciar el carrito?')) {
        limpiarCarrito();
        pintarCarrito();
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
      it.cantidad = Math.max(1, valor);
    } else if (modo === 'descuento') {
      if (valor > 100) { valor = 100; buffer = '100'; }
      it.descuento_pct = valor;
    } else if (modo === 'precio') {
      it.precio = Math.max(0, valor);
    }
    pintarCarrito();
  }

  document.querySelectorAll('.pos-numpad button').forEach((b) => {
    b.addEventListener('mousedown', () => inputBusqueda.blur());
    b.addEventListener('click', () => teclear(b.dataset.key));
  });
  marcarModo();

  // ---------------------------------------------------------------
  // 6b. TECLADO FÍSICO GLOBAL
  // ---------------------------------------------------------------
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    const key = e.key;

    if (key === 'F2') { e.preventDefault(); if (carrito.length) abrirPago(); return; }
    if (key === 'F3') { e.preventDefault(); inputBusqueda.focus(); return; }

    if (key === 'Enter') { e.preventDefault(); if (carrito.length) abrirPago(); return; }

    if (key === 'Escape') {
      seleccionado = -1; pintarCarrito();
      return;
    }

    if (key === 'Backspace') {
      e.preventDefault();
      const it = carrito[seleccionado];
      if (escribiendo && buffer) {
        buffer = buffer.slice(0, -1);
        if (it) {
          let valor = parseFloat(buffer) || 0;
          if (modo === 'cantidad') it.c
