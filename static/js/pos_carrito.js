// =====================================================================
// POS · CARRITO DE VENTAS
// =====================================================================
// Controla la pantalla de venta:
//   1. Buscar productos (por nombre o escaneando el código de barras)
//   2. Armar el carrito (agregar, cambiar cantidad, descuento, quitar)
//      Cada producto puede venderse en varias presentaciones (unidad,
//      sobre, caja...). El inventario se cuenta en la unidad principal:
//      1 "Caja x 100" descuenta 100 unidades.
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
    // Termina en /0: JS cambia ese 0 por el id del producto (ver abrirInfoProducto)
    productoInfo: ($('url-api-producto-info') && $('url-api-producto-info').value) || '/pos/api/producto/0',
    // Vacío = este usuario no puede editar productos (solo administrador / director técnico)
    productoEditarApi: ($('url-api-producto-editar') && $('url-api-producto-editar').value) || '',
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
  // Carritos guardados antes de existir las presentaciones: eran todos "unidad principal"
  carrito.forEach((it) => {
    if (it.factor == null) { it.factor = 1; it.presentacion_id = 0; it.presentacion = ''; }
    if (it.stock_base == null) it.stock_base = it.stock;
  });

  // Guarda una copia del carrito en el navegador para no perderlo si se recarga la página.
  // Si el carrito está vacío no guardamos nada (así no quedan restos de ventas ya cobradas).
  function guardarCarrito() {
    try {
      if (carrito.length) localStorage.setItem(CLAVE_CARRITO, JSON.stringify(carrito));
      else localStorage.removeItem(CLAVE_CARRITO);
    } catch (e) { /* si el navegador no deja guardar, seguimos sin guardar */ }
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
  // 3b. ¿CUÁNTAS SE PUEDEN VENDER DE ESTA LÍNEA?
  // ---------------------------------------------------------------
  // El inventario (stock_base) está en unidades principales y lo comparten
  // todas las líneas del mismo producto. Ej: hay 120 tabletas; si ya hay
  // 1 caja x 100 en el carrito, de sobres x 10 solo caben (120-100)/10 = 2.
  function topeDe(it) {
    const otras = carrito.reduce((suma, x) =>
      (x !== it && x.producto_id === it.producto_id) ? suma + x.cantidad * x.factor : suma, 0);
    const libres = Math.max(0, it.stock_base - otras);
    return Math.floor(libres / it.factor * 100 + 1e-9) / 100;   // 2 decimales hacia abajo
  }
  function avisoTope(it) {
    const tope = topeDe(it);
    aviso(it.factor === 1
      ? 'Solo hay ' + (+tope.toFixed(2)) + ' disponible(s).'
      : 'Solo alcanza para ' + (+tope.toFixed(2)) + ' ' + it.presentacion +
        ' (hay ' + (+it.stock_base.toFixed(2)) + ' unidades).');
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
          // Si se escaneó el código de una presentación (ej: la caja), se agrega esa.
          agregar(json.productos[0], json.presentacion_id);
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
      // "Sirve para": se muestra cuando se buscó por síntoma, es decir, cuando
      // lo escrito NO está en el nombre pero sí en los usos del producto.
      const buscado = inputBusqueda.value.trim().toLowerCase();
      const porSintoma = buscado && p.usos && p.usos.length &&
        !p.nombre.toLowerCase().includes(buscado.split(' ')[0]);
      const sirvePara = porSintoma
        ? '<div class="pos-card-usos" title="' + esc(p.usos.join(', ')) + '">🩺 ' + esc(p.usos.join(' · ')) + '</div>'
        : '';
      return '<div class="pos-card' + (agotado ? ' agotado' : '') + '" data-id="' + p.id + '">' +
        '<button type="button" class="pos-card-info-btn" data-info-id="' + p.id + '" title="Ver información del producto">i</button>' +
        '<div class="pos-card-img">' + imagen + '</div>' +
        '<div class="pos-card-info">' +
          '<div class="pos-card-nombre">' + esc(p.nombre) + esc(etiquetas) + '</div>' +
          '<div class="pos-card-codigo">' + esc(p.concentracion || p.codigo) + '</div>' +
          sirvePara +
          (p.presentaciones && p.presentaciones.length > 1
            ? '<div class="pos-card-pres">📦 También: ' +
              esc(p.presentaciones.slice(1).map((x) => x.nombre).join(' · ')) + '</div>'
            : '') +
          '<div class="pos-card-stock">' + (agotado ? 'Agotado' : 'Stock: ' + (+p.stock.toFixed(2))) + '</div>' +
          '<div class="pos-card-precio">' + peso(p.precio) + '</div>' +
        '</div></div>';
    }).join('');
  }

  // ---------------------------------------------------------------
  // 5. CARRITO
  // ---------------------------------------------------------------
  // presentacionId: 0 = unidad principal; otro número = sobre, caja...
  // Si no se indica y el producto tiene varias presentaciones, se pregunta.
  function agregar(prod, presentacionId) {
    if (prod.control_especial) {
      aviso('Medicamento de control especial: aún no se puede vender desde el POS.');
      return;
    }
    if (prod.stock <= 0) { aviso('Producto agotado.'); return; }

    const opciones = prod.presentaciones && prod.presentaciones.length
      ? prod.presentaciones
      : [{ id: 0, nombre: '', factor: 1, precio: prod.precio }];
    if (presentacionId == null) {
      if (opciones.length > 1) { elegirPresentacion(prod); return; }
      presentacionId = opciones[0].id;
    }
    const pres = opciones.find((x) => x.id === presentacionId) || opciones[0];

    // Todas las líneas de este producto conocen el stock más reciente
    carrito.forEach((x) => { if (x.producto_id === prod.id) x.stock_base = prod.stock; });

    let pos = carrito.findIndex((i) => i.producto_id === prod.id && i.presentacion_id === pres.id);
    if (pos >= 0) {
      if (carrito[pos].cantidad + 1 > topeDe(carrito[pos])) avisoTope(carrito[pos]);
      else carrito[pos].cantidad += 1;
    } else {
      const nueva = {
        producto_id: prod.id, codigo: prod.codigo, nombre: prod.nombre,
        concentracion: prod.concentracion, precio: pres.precio,
        precio_original: pres.precio, motivo_precio: null,
        iva_tipo: prod.iva_tipo, iva_tarifa: prod.iva_tarifa,
        requiere_formula: prod.requiere_formula,
        // Presentación: nombre solo se muestra si el producto tiene varias
        presentacion_id: pres.id, factor: pres.factor,
        presentacion: opciones.length > 1 ? pres.nombre : '',
        stock_base: prod.stock, cantidad: 1, descuento_pct: 0,
      };
      if (topeDe(nueva) < 1) { avisoTope(nueva); return; }
      carrito.push(nueva);
      pos = carrito.length - 1;
      if (prod.requiere_formula) aviso('📋 Requiere fórmula médica: verifícala antes de entregar.');
    }
    seleccionar(pos);
    pintarCarrito();
  }

  // Pregunta con la ventana del programa y, si acepta, quita esa línea del carrito
  function quitarConConfirmacion(pos) {
    const it = carrito[pos];
    if (!it) return;
    window.confirmar('¿Quitar "' + it.nombre + '" del carrito?', { textoAceptar: 'Quitar' }).then((ok) => {
      if (!ok) return;
      carrito.splice(carrito.indexOf(it), 1);
      seleccionado = -1;
      pintarCarrito();
    });
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
          it.presentacion ? '📦 ' + it.presentacion : '',
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
      if (it.cantidad + 1 > topeDe(it)) avisoTope(it);
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
      // window.confirmar (base.html) muestra la ventana del programa y responde después
      if (carrito.length) {
        window.confirmar('¿Vaciar el carrito?').then((ok) => {
          if (ok) { limpiarCarrito(); pintarCarrito(); }
        });
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
      if (valor > topeDe(it)) {
        avisoTope(it);
        valor = topeDe(it); buffer = String(valor);
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
  // Si el foco NO está en un input, capturamos las teclas y las
  // dirigimos al carrito/numpad. Esto permite usar el teclado numérico
  // físico sin que el texto vaya a la barra de búsqueda.
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    // Si hay alguna ventana abierta (info, editar, pago, gasto...), el teclado es de ella
    if (document.querySelector('[id^="modal-"]:not(.modal-oculto)')) return;

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
          else if (modo === 'precio') it.precio = Math.max(0, valor);
          else it.descuento_pct = Math.min(100, Math.max(0, valor));
        }
        pintarCarrito();
      } else if (it) {
        // Reducir cantidad. Si queda en 0, preguntar para eliminar.
        if (it.cantidad > 1) {
          it.cantidad -= 1;
          pintarCarrito();
        } else {
          quitarConConfirmacion(seleccionado);
        }
      }
      return;
    }

    // Delete / Supr = eliminar producto seleccionado
    if (key === 'Delete') {
      e.preventDefault();
      const it = carrito[seleccionado];
      if (it) quitarConConfirmacion(seleccionado);
      return;
    }

    // + = aumentar cantidad
    if (key === '+' || key === '=') {
      e.preventDefault();
      const it = carrito[seleccionado];
      if (it) {
        if (it.cantidad + 1 > topeDe(it)) avisoTope(it);
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

  // ¿El cajero cambió el precio de esta línea respecto al precio normal?
  function cambioDePrecio(it) {
    return it.precio_original != null && Math.abs(it.precio - it.precio_original) > 0.01;
  }

  // Opción B: cualquiera puede cambiar un precio, pero SIEMPRE con un motivo.
  // Recorre el carrito y, por cada precio cambiado que aún no tenga motivo,
  // lo pregunta. Devuelve false si el cajero cancela (entonces no se cobra).
  function pedirMotivosDePrecio() {
    for (const it of carrito) {
      if (!cambioDePrecio(it)) { it.motivo_precio = null; continue; }
      if (!(it.precio > 0)) {
        aviso('"' + it.nombre + '" quedó con precio 0. Corrígelo antes de cobrar.');
        return false;
      }
      // Si ya dio un motivo para ESTE mismo precio, no se lo volvemos a pedir.
      if (it.motivo_precio && it.motivo_precio_valor === it.precio) continue;
      const motivo = prompt(
        'Cambiaste el precio de "' + it.nombre + '"\n' +
        'de ' + peso(it.precio_original) + ' a ' + peso(it.precio) + '.\n\n' +
        'Motivo del cambio (obligatorio):', '');
      if (motivo === null || motivo.trim().length < 3) {
        aviso('Sin motivo no se puede cambiar un precio.');
        return false;
      }
      it.motivo_precio = motivo.trim();
      it.motivo_precio_valor = it.precio;   // recordamos para qué precio fue el motivo
    }
    guardarCarrito();
    return true;
  }

  function abrirPago() {
    if (carrito.some((i) => !(i.cantidad > 0))) {
      aviso('Hay un producto con cantidad 0. Corrígelo o quítalo.');
      return;
    }
    if (!carrito.length) return;
    if (!pedirMotivosDePrecio()) return;
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
    // Por cada producto mandamos solo lo necesario. El precio normal NO se manda:
    // lo pone el servidor. Solo si el cajero lo cambió viajan precio_nuevo y motivo_precio.
    datos.append('carrito', JSON.stringify(carrito.map((i) => {
      const linea = { producto_id: i.producto_id, presentacion_id: i.presentacion_id || 0,
                      cantidad: i.cantidad, descuento_pct: i.descuento_pct };
      if (cambioDePrecio(i)) {
        linea.precio_nuevo = i.precio;
        linea.motivo_precio = i.motivo_precio;
      }
      return linea;
    })));
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
      limpiarCarrito();   // vacía el carrito Y borra la copia guardada en el navegador
      cliente = { nombre: '', documento: '' }; nota = '';
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
  // 8b. VENTANA "i": INFORMACIÓN DEL PRODUCTO
  // ---------------------------------------------------------------
  // Flujo: tocar la "i" -> abrirInfoProducto(id) -> pide los datos al
  // servidor -> pintarInfo(p) los pone en la ventana.
  const modalInfo = $('modal-info-producto');
  const NEGOCIO = ($('negocio-nombre') && $('negocio-nombre').value) || 'Droguería';
  let productoInfo = null;   // datos del producto que se está mostrando (para "Editar")

  // "2028-05-01" o "2028-05-01 10:00:00" -> "01/05/2028" (formato colombiano)
  function fechaCorta(iso) {
    if (!iso) return '—';
    const p = String(iso).slice(0, 10).split('-');
    return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : iso;
  }

  // Muestra 9 como "9" y 2.5 como "2,5"
  const cant = (n) => (+(+n).toFixed(2)).toLocaleString('es-CO');

  // Pinta una tabla sencilla. columnas = ['Lote', 'Vence', ...], filas = [[...], [...]]
  function tabla(columnas, filas) {
    return '<table class="info-tabla"><tr>' + columnas.map((c) => '<th>' + esc(c) + '</th>').join('') + '</tr>' +
      filas.map((f) => '<tr>' + f.map((celda) => '<td>' + celda + '</td>').join('') + '</tr>').join('') +
      '</table>';
  }

  function cerrarInfoProducto() {
    if (modalInfo) modalInfo.classList.add('modal-oculto');
    productoInfo = null;
    inputBusqueda.focus();
  }

  async function abrirInfoProducto(id) {
    if (!modalInfo) return;
    $('info-nombre').textContent = 'Cargando…';
    ['info-precio', 'info-a-la-mano', 'info-iva', 'info-inventario-resumen', 'info-otros-lotes', 'info-stock-minimo']
      .forEach((x) => { $(x).textContent = ''; });
    ['info-insignias', 'info-detalle', 'info-lotes', 'info-compras', 'info-finanzas'].forEach((x) => { $(x).innerHTML = ''; });
    modalInfo.classList.remove('modal-oculto');
    try {
      // La dirección termina en /0; cambiamos ese 0 por el id del producto
      const resp = await fetch(URL.productoInfo.replace(/0$/, String(id)), { credentials: 'same-origin' });
      const json = await resp.json();
      if (!json.ok) { $('info-nombre').textContent = json.error || 'No se pudo cargar.'; return; }
      productoInfo = json.producto;
      pintarInfo(productoInfo);
    } catch (e) {
      $('info-nombre').textContent = 'Error de conexión: ' + e.message;
    }
  }

  function pintarInfo(p) {
    // ---- Franja amarilla ----
    $('info-nombre').textContent = p.nombre + (p.concentracion ? ' ' + p.concentracion : '');
    $('info-precio').textContent = peso(p.precio);
    $('info-a-la-mano').textContent = 'A la mano: ' + cant(p.stock) + ' unidades';
    $('info-iva').textContent = p.iva_tipo === 'gravado'
      ? 'IVA: ' + cant(p.iva_tarifa) + ' % (= ' + peso(p.iva_valor) + ')'
      : 'IVA: ' + (p.iva_tipo === 'exento' ? 'Exento' : 'Excluido') + ' (= $0)';
    // Principio activo y "sirve para" (los usos), debajo del nombre
    const detalle = [];
    if (p.principio_activo) detalle.push('🧪 ' + esc(p.principio_activo));
    if (p.usos && p.usos.length) detalle.push('🩺 Sirve para: ' + esc(p.usos.join(', ')));
    $('info-detalle').innerHTML = detalle.join(' &nbsp;·&nbsp; ');
    $('info-insignias').innerHTML = [
      p.requiere_formula ? '<span class="info-insignia">📋 Requiere fórmula</span>' : '',
      p.cadena_frio ? '<span class="info-insignia">❄️ Cadena de frío</span>' : '',
      p.control_especial ? '<span class="info-insignia info-insignia-roja">🔒 Control especial</span>' : '',
    ].join('');

    // ---- 1. Inventario ----
    $('info-inventario-resumen').innerHTML =
      esc(NEGOCIO) + ': <strong>' + cant(p.stock) + '</strong> unidades disponibles para vender';
    $('info-lotes').innerHTML = p.lotes.length
      ? tabla(['Lote', 'Vence', 'Cant.', ''], p.lotes.map((l, i) => [
          esc(l.lote || '—'), fechaCorta(l.vencimiento), cant(l.cantidad),
          i === 0 ? '<span class="info-primero">🟢 sale primero</span>' : '',
        ]))
      : '<p class="suave">No hay lotes disponibles para vender.</p>';
    // Avisa si hay mercancía que NO se puede vender todavía
    const o = p.otros_lotes, avisos = [];
    if (o.cuarentena) avisos.push(o.cuarentena + ' en cuarentena');
    if (o.bloqueados) avisos.push(o.bloqueados + ' bloqueado(s)');
    if (o.vencidos) avisos.push(o.vencidos + ' vencido(s)');
    $('info-otros-lotes').textContent = avisos.length ? '⚠️ Otros lotes: ' + avisos.join(' · ') : '';

    // ---- 2. Reabastecimiento: últimas 4 compras ----
    $('info-compras').innerHTML = p.compras.length
      ? tabla(['Fecha', 'Proveedor', 'Recepción', 'Cant.', 'Costo'], p.compras.map((c) => [
          fechaCorta(c.fecha), esc(c.proveedor), esc(c.numero), cant(c.cantidad), peso(c.costo),
        ]))
      : '<p class="suave">Aún no hay compras registradas por recepción técnica.</p>';
    if (p.stock_minimo > 0) {
      $('info-stock-minimo').textContent = 'Stock mínimo: ' + cant(p.stock_minimo) + '  →  ' +
        (p.stock > p.stock_minimo ? '✅ por encima' : '⚠️ hay que pedir');
    }

    // ---- 3. Finanzas (1 unidad) ----
    const filas = [
      ['Precio sin IVA', peso(p.precio_sin_iva)],
      ['Costo', peso(p.costo) + ' <span class="suave">(' + esc(p.costo_origen) + ')</span>'],
      ['Margen', '<span class="' + (p.margen < 0 ? 'info-negativo' : '') + '">' +
        peso(p.margen) + ' (' + cant(p.margen_pct) + ' %)</span>'],
    ];
    if (p.precio_maximo > 0) filas.push(['Precio máximo', peso(p.precio_maximo)]);
    $('info-finanzas').innerHTML = filas.map((f) => '<dt>' + f[0] + '</dt><dd>' + f[1] + '</dd>').join('');

    // Presentaciones (solo si hay más de una): precio, cuánto trae y margen de cada una
    const presInfo = $('info-presentaciones');
    if (presInfo) {
      presInfo.innerHTML = p.presentaciones && p.presentaciones.length > 1
        ? tabla(['Presentación', 'Trae', 'Precio', 'Margen'], p.presentaciones.map((x) => [
            esc(x.nombre), cant(x.factor), peso(x.precio),
            '<span class="' + (x.margen < 0 ? 'info-negativo' : '') + '">' +
              peso(x.margen) + ' (' + cant(x.margen_pct) + ' %)</span>',
          ]))
        : '';
    }
  }

  if (modalInfo) {
    $('info-cerrar').addEventListener('click', cerrarInfoProducto);
    $('info-ok').addEventListener('click', cerrarInfoProducto);
    // Clic en el fondo oscuro (fuera de la caja) también cierra
    modalInfo.addEventListener('click', (e) => { if (e.target === modalInfo) cerrarInfoProducto(); });
    if ($('info-editar')) $('info-editar').addEventListener('click', () => { if (productoInfo) abrirEditar(productoInfo); });
  }

  // ---------------------------------------------------------------
  // 8c. VENTANA "EDITAR PRODUCTO" (encima de la "i")
  // ---------------------------------------------------------------
  // Solo existe en la página si el usuario es administrador o director técnico.
  const modalEditar = $('modal-editar-producto');
  const formEditar = $('form-editar-producto');
  let editandoId = null;

  // 9800 -> "9800"; null -> "" (para poner números en las cajas de texto)
  const textoNumero = (n) => (n === null || n === undefined || n === '' ? '' : String(+n));

  // Muestra la foto actual, o el ícono 💊 si no hay
  function mostrarFoto(src) {
    const img = $('editar-foto-img');
    img.hidden = !src;
    $('editar-foto-vacia').hidden = !!src;
    if (src) img.src = src;
  }

  // La casilla de tarifa solo aparece si el IVA es "gravado"
  function actualizarTarifa() {
    const gravado = $('editar-iva-tipo').value === 'gravado';
    $('editar-iva-tarifa').hidden = !gravado;
    $('editar-iva-porcentaje').hidden = !gravado;
  }

  function abrirEditar(p) {
    if (!modalEditar) return;
    editandoId = p.id;
    formEditar.reset();
    $('editar-error').hidden = true;
    $('editar-nombre').value = p.nombre;
    $('editar-codigo-barras').value = p.codigo_barras || '';
    $('editar-maneja-lotes').checked = p.maneja_vencimiento;
    $('editar-precio').value = textoNumero(p.precio);
    $('editar-precio-maximo').value = textoNumero(p.precio_maximo);
    $('editar-iva-tipo').value = p.iva_tipo || 'excluido';
    $('editar-iva-tarifa').value = p.iva_tipo === 'gravado' ? textoNumero(p.iva_tarifa) : '';
    $('editar-formula').checked = p.requiere_formula;
    $('editar-control').checked = p.control_especial;
    // Marcar las categorías que ya tiene el producto
    formEditar.querySelectorAll('input[name="categorias"]').forEach((c) => {
      c.checked = p.categorias.includes(+c.value);
    });
    $('editar-foto-accion').value = '';
    mostrarFoto(p.imagen ? URL.estaticos + p.imagen : '');
    actualizarTarifa();
    modalEditar.classList.remove('modal-oculto');
    $('editar-nombre').focus();
  }

  function cerrarEditar() {
    if (modalEditar) modalEditar.classList.add('modal-oculto');
    editandoId = null;
  }

  // Si se cambió un producto que está en el carrito, actualizamos su línea.
  // Si el cajero NO le había cambiado el precio a mano, toma el precio nuevo.
  function refrescarEnCarrito(p) {
    let tocado = false;
    carrito.forEach((it) => {
      if (it.producto_id !== p.id) return;
      const sinCambioManual = Math.abs(it.precio - it.precio_original) <= 0.01;
      it.nombre = p.nombre;
      it.iva_tipo = p.iva_tipo;
      it.iva_tarifa = p.iva_tarifa;
      it.requiere_formula = p.requiere_formula;
      // El modal "Editar" solo cambia el precio de la unidad principal;
      // las líneas de sobre/caja conservan el suyo.
      if (!it.presentacion_id) {
        it.precio_original = p.precio;
        if (sinCambioManual) it.precio = p.precio;
      }
      if (p.control_especial) aviso('"' + p.nombre + '" ahora es de control especial: no se podrá cobrar desde el POS.');
      tocado = true;
    });
    if (tocado) pintarCarrito();
  }

  async function guardarEdicion() {
    const errorBox = $('editar-error');
    errorBox.hidden = true;
    const datos = new FormData(formEditar);   // toma todos los campos del formulario, incluida la foto
    datos.append('_csrf', csrf());
    $('editar-guardar').disabled = true;
    try {
      const url = URL.productoEditarApi.replace('/0/', '/' + editandoId + '/');
      const resp = await fetch(url, { method: 'POST', body: datos, credentials: 'same-origin' });
      const json = await resp.json().catch(() => ({ ok: false, error: 'No tienes permiso para editar.' }));
      if (!json.ok) {
        errorBox.textContent = json.error || 'No se pudo guardar.';
        errorBox.hidden = false;
        return;
      }
      const id = editandoId;
      cerrarEditar();
      aviso('Producto actualizado.');
      await abrirInfoProducto(id);                 // la "i" se vuelve a pintar con los datos nuevos
      if (productoInfo) refrescarEnCarrito(productoInfo);
      buscar(false);                               // y las tarjetas también
    } catch (e) {
      errorBox.textContent = 'Error de conexión: ' + e.message;
      errorBox.hidden = false;
    } finally {
      $('editar-guardar').disabled = false;
    }
  }

  if (modalEditar) {
    $('editar-cerrar').addEventListener('click', cerrarEditar);
    $('editar-descartar').addEventListener('click', cerrarEditar);
    $('editar-guardar').addEventListener('click', guardarEdicion);
    $('editar-iva-tipo').addEventListener('change', actualizarTarifa);
    modalEditar.addEventListener('click', (e) => { if (e.target === modalEditar) cerrarEditar(); });
    // Enter dentro del formulario = Guardar (en vez de recargar la página)
    formEditar.addEventListener('submit', (e) => { e.preventDefault(); guardarEdicion(); });
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
  }

  // Escape cierra la ventana de ARRIBA primero (Editar), y luego la "i"
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (modalPres && !modalPres.classList.contains('modal-oculto')) { cerrarPresentacion(); e.stopImmediatePropagation(); }
    else if (modalEditar && !modalEditar.classList.contains('modal-oculto')) { cerrarEditar(); e.stopImmediatePropagation(); }
    else if (modalInfo && !modalInfo.classList.contains('modal-oculto')) { cerrarInfoProducto(); e.stopImmediatePropagation(); }
  }, true);

  // ---------------------------------------------------------------
  // 8d. VENTANA "¿CÓMO LO VENDES?" (elegir presentación)
  // ---------------------------------------------------------------
  // Un botón por presentación: Tableta $200 · Sobre x 10 $1.800 · Caja x 100 $15.000.
  // Las que ya no alcanzan con el stock aparecen apagadas.
  const modalPres = $('modal-presentacion');
  let productoEligiendo = null;

  function elegirPresentacion(prod) {
    if (!modalPres) { agregar(prod, 0); return; }
    productoEligiendo = prod;
    $('pres-producto').textContent = prod.nombre + (prod.concentracion ? ' ' + prod.concentracion : '') +
      ' · hay ' + (+prod.stock.toFixed(2)) + ' ' + (prod.presentaciones[0].nombre || 'unidades');
    // Unidades que ya están en el carrito de este producto (cualquier presentación)
    const enCarrito = carrito.reduce((suma, x) =>
      x.producto_id === prod.id ? suma + x.cantidad * x.factor : suma, 0);
    $('pres-opciones').innerHTML = prod.presentaciones.map((x, i) => {
      const alcanza = prod.stock - enCarrito >= x.factor - 1e-9;
      const trae = x.factor === 1 ? 'unidad principal' : 'trae ' + (+x.factor.toFixed(2));
      return '<button type="button" class="pres-opcion" data-pres="' + x.id + '"' + (alcanza ? '' : ' disabled') + '>' +
        '<span class="pres-tecla">' + (i + 1) + '</span>' +
        '<span><span class="pres-nombre">' + esc(x.nombre) + '</span>' +
        '<span class="pres-detalle">' + trae + (alcanza ? '' : ' · no alcanza el stock') + '</span></span>' +
        '<span class="pres-precio">' + peso(x.precio) + '</span></button>';
    }).join('');
    modalPres.classList.remove('modal-oculto');
    const primera = modalPres.querySelector('.pres-opcion:not([disabled])');
    if (primera) primera.focus();
  }

  function cerrarPresentacion() {
    if (modalPres) modalPres.classList.add('modal-oculto');
    productoEligiendo = null;
    inputBusqueda.focus();
  }

  if (modalPres) {
    $('pres-cerrar').addEventListener('click', cerrarPresentacion);
    modalPres.addEventListener('click', (e) => {
      if (e.target === modalPres) { cerrarPresentacion(); return; }
      const boton = e.target.closest('.pres-opcion');
      if (!boton || boton.disabled || !productoEligiendo) return;
      const prod = productoEligiendo;
      cerrarPresentacion();
      agregar(prod, +boton.dataset.pres);
    });
    // Atajo de teclado: 1, 2, 3... eligen la opción de ese número
    modalPres.addEventListener('keydown', (e) => {
      if (!/^[1-9]$/.test(e.key)) return;
      const boton = modalPres.querySelectorAll('.pres-opcion')[+e.key - 1];
      // stopPropagation: que la misma tecla NO llegue también al teclado del carrito
      // (si no, el "2" que eligió "Sobre" pondría además cantidad 2)
      if (boton) { e.preventDefault(); e.stopPropagation(); boton.click(); }
    });
  }

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
    // Si tocaron la "i", mostramos la información y NO agregamos al carrito
    const botonInfo = e.target.closest('.pos-card-info-btn');
    if (botonInfo) { e.stopPropagation(); abrirInfoProducto(+botonInfo.dataset.infoId); return; }
    const tarjeta = e.target.closest('.pos-card');
    if (!tarjeta) return;
    const prod = productosMostrados.find((p) => p.id === +tarjeta.dataset.id);
    if (prod) agregar(prod);
    // Si se abrió "¿Cómo lo vendes?", el foco se queda en sus botones (teclas 1, 2, 3)
    if (!modalPres || modalPres.classList.contains('modal-oculto')) inputBusqueda.focus();
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
