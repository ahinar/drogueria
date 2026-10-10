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
//   9. VARIAS VENTAS A LA VEZ: pestañas "Venta 1", "Venta 2"... y botón +
//      para atender a otro cliente sin perder la venta que estaba a medias.
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
  const CLAVE_CARRITO = 'pos_carrito_caja_' + CAJA_ID;   // formato viejo (una sola venta)
  const CLAVE_VENTAS = 'pos_ventas_caja_' + CAJA_ID;     // formato nuevo (varias ventas)
  const MAX_VENTAS = 8;

  // Limpieza: borrar lo guardado de cajas anteriores (de otro turno)
  try {
    const aBorrar = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && ((k.startsWith('pos_carrito_caja_') && k !== CLAVE_CARRITO) ||
                (k.startsWith('pos_ventas_caja_') && k !== CLAVE_VENTAS))) {
        aBorrar.push(k);
      }
    }
    aBorrar.forEach(k => localStorage.removeItem(k));
  } catch (e) { /* silencio */ }

  // ---------------------------------------------------------------
  // VARIAS VENTAS ABIERTAS
  // ---------------------------------------------------------------
  // "ventas" es la lista de ventas abiertas; cada una tiene su carrito,
  // su cliente y su nota. "activa" es la posición de la que se ve.
  // Las variables carrito / cliente / nota de siempre apuntan a la venta
  // activa, así el resto del código no cambia.
  const ventaVacia = (id) => ({ id: id, carrito: [], cliente: { nombre: '', documento: '' }, nota: '' });
  let ventas = [ventaVacia(1)];
  let activa = 0;

  // Cargar lo guardado en el navegador (o el carrito del formato viejo)
  try {
    const guardado = JSON.parse(localStorage.getItem(CLAVE_VENTAS) || 'null');
    if (guardado && Array.isArray(guardado.ventas) && guardado.ventas.length) {
      ventas = guardado.ventas;
      activa = Math.min(Math.max(0, guardado.activa || 0), ventas.length - 1);
    } else {
      const viejo = JSON.parse(localStorage.getItem(CLAVE_CARRITO) || 'null');
      if (Array.isArray(viejo)) ventas[0].carrito = viejo;
    }
    localStorage.removeItem(CLAVE_CARRITO);
  } catch (e) { ventas = [ventaVacia(1)]; activa = 0; }
  carrito = ventas[activa].carrito;
  cliente = ventas[activa].cliente || { nombre: '', documento: '' };
  nota = ventas[activa].nota || '';

  // Carritos guardados antes de existir las presentaciones: eran todos "unidad principal"
  ventas.forEach((v) => v.carrito.forEach((it) => {
    if (it.factor == null) { it.factor = 1; it.presentacion_id = 0; it.presentacion = ''; }
    if (it.stock_base == null) it.stock_base = it.stock;
  }));

  // Guarda TODAS las ventas abiertas en el navegador: no se pierden si se
  // recarga la página, se cierra el navegador o se va la luz.
  function guardarCarrito() {
    ventas[activa].carrito = carrito;
    ventas[activa].cliente = cliente;
    ventas[activa].nota = nota;
    try {
      const hayAlgo = ventas.some((v) => v.carrito.length || v.cliente.nombre || v.nota);
      if (hayAlgo || ventas.length > 1) {
        localStorage.setItem(CLAVE_VENTAS, JSON.stringify({ ventas: ventas, activa: activa }));
      } else {
        localStorage.removeItem(CLAVE_VENTAS);
      }
    } catch (e) { /* si el navegador no deja guardar, seguimos sin guardar */ }
    pintarPestanas();
  }

  // Después de cobrar: la venta cobrada se cierra. Si había otras abiertas,
  // se pasa a la siguiente; si no, queda una venta nueva vacía.
  function limpiarCarrito() {
    ventas.splice(activa, 1);
    if (!ventas.length) ventas.push(ventaVacia(1));
    activa = Math.min(activa, ventas.length - 1);
    carrito = ventas[activa].carrito;
    cliente = ventas[activa].cliente;
    nota = ventas[activa].nota;
    seleccionado = -1;
    guardarCarrito();
  }

  // Cambiar a otra venta abierta (clic en su pestaña)
  function cambiarVenta(i) {
    if (i === activa || !ventas[i]) return;
    guardarCarrito();                 // primero se guarda la que se deja
    activa = i;
    carrito = ventas[i].carrito;
    cliente = ventas[i].cliente;
    nota = ventas[i].nota;
    seleccionado = -1;
    pintarCarrito();
    inputBusqueda.focus();
  }

  // Botón +: abre una venta nueva (para atender a otro cliente)
  function nuevaVenta() {
    if (ventas.length >= MAX_VENTAS) { aviso('Máximo ' + MAX_VENTAS + ' ventas abiertas a la vez.'); return; }
    guardarCarrito();
    const siguiente = ventas.reduce((m, v) => Math.max(m, v.id), 0) + 1;
    ventas.push(ventaVacia(siguiente));
    cambiarVenta(ventas.length - 1);
    aviso('Venta ' + siguiente + ' abierta. La anterior quedó guardada en su pestaña.');
  }

  // La ✕ de una pestaña: descarta esa venta (pregunta si tiene productos)
  async function cerrarVenta(i) {
    const v = ventas[i];
    if (!v) return;
    const lista = i === activa ? carrito : v.carrito;
    if (lista.length && !(await window.confirmar('¿Descartar la Venta ' + v.id + ' con ' + lista.length +
        ' producto(s)? No se cobra nada.', { textoAceptar: 'Descartar' }))) return;
    guardarCarrito();
    ventas.splice(i, 1);
    if (!ventas.length) ventas.push(ventaVacia(1));
    // Si se cerró una pestaña anterior a la activa, la activa corre una posición
    if (i < activa) activa -= 1;
    activa = Math.min(activa, ventas.length - 1);
    carrito = ventas[activa].carrito;
    cliente = ventas[activa].cliente;
    nota = ventas[activa].nota;
    seleccionado = -1;
    pintarCarrito();
  }

  // Dibuja las pestañas: "Venta 1 · 3", "Venta 2 · Juan · 1", y el botón +
  function pintarPestanas() {
    const caja = $('pos-ventas-tabs');
    if (!caja) return;
    caja.innerHTML = ventas.map((v, i) => {
      const lista = i === activa ? carrito : v.carrito;
      const n = lista.reduce((s, it) => s + 1, 0);
      const quien = v.cliente && v.cliente.nombre ? ' · ' + esc(v.cliente.nombre.split(' ')[0]) : '';
      return '<div class="pos-venta-tab' + (i === activa ? ' activa' : '') + '">' +
        '<button type="button" class="pos-venta-ir" data-venta="' + i + '" title="Ver esta venta">' +
          'Venta ' + v.id + quien + (n ? ' <span class="pos-venta-n">' + n + '</span>' : '') + '</button>' +
        (ventas.length > 1 || n ? '<button type="button" class="pos-venta-cerrar" data-cerrar="' + i +
          '" aria-label="Descartar la venta ' + v.id + '" title="Descartar esta venta">×</button>' : '') +
        '</div>';
    }).join('') +
      '<button type="button" class="pos-venta-nueva" id="pos-venta-nueva" title="Nueva venta: atender a otro cliente (F4)" ' +
      'aria-label="Nueva venta">+</button>';
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
    if (it.libre) return 1e9;   // venta libre: no sale del inventario, no hay tope
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
          // Otras presentaciones: el chip se puede tocar para escoger (data-elegir)
          (vendibles(p).length > 1
            ? '<div class="pos-card-pres" data-elegir="' + p.id + '" title="Tocar para escoger cómo venderlo">📦 ' +
              (defectoDe(p).id ? 'Otras: ' : 'También: ') +
              esc(vendibles(p).filter((x) => x.id !== defectoDe(p).id).map((x) => x.nombre).join(' · ')) + '</div>'
            : '') +
          // Stock en la unidad en que se vende (ej: "29 Sobre x 10 + 5 Tableta")
          '<div class="pos-card-stock">' + (agotado ? 'Agotado' : 'Hay: ' + esc(textoExistencias(p, p.stock))) + '</div>' +
          // Precio de lo que se vende al tocar (ej: "Sobre x 10 · $2.000")
          '<div class="pos-card-precio">' + (defectoDe(p).id ? '<small>' + esc(defectoDe(p).nombre) + '</small> ' : '') +
            peso(defectoDe(p).precio) + '</div>' +
        '</div></div>';
    }).join('');
  }

  // ---------------------------------------------------------------
  // 5. CARRITO
  // ---------------------------------------------------------------
  // presentacionId: 0 = unidad principal; otro número = sobre, caja...
  // Si no se indica y el producto tiene varias presentaciones, se pregunta.
  // Presentaciones que el POS puede vender (sin la pasta suelta si no se vende suelto)
  function vendibles(prod) {
    return (prod.presentaciones || []).filter((x) => x.vendible !== false);
  }

  // "295 tabletas" dicho como se vende: "29 Sobre x 10 + 5 Tableta"
  // (igual que presentaciones.texto_existencias en Python)
  function textoExistencias(prod, cantidad) {
    const opciones = prod.presentaciones || [];
    const base = opciones[0] ? opciones[0].nombre : 'unidades';
    const pres = defectoDe(prod);
    const n = (x) => String(+x.toFixed(2)).replace('.', ',');
    if (!pres || !(pres.factor > 1) || cantidad <= 0) return n(cantidad) + ' ' + base;
    const enteros = Math.floor(cantidad / pres.factor + 1e-9);
    const resto = +(cantidad - enteros * pres.factor).toFixed(4);
    const partes = [];
    if (enteros) partes.push(enteros + ' ' + pres.nombre);
    if (resto > 1e-9) partes.push(n(resto) + ' ' + base);
    return partes.join(' + ');
  }

  // La presentación que se vende al tocar la tarjeta (ficha: "Se vende normalmente por")
  function defectoDe(prod) {
    const opciones = prod.presentaciones || [];
    return opciones.find((x) => x.id === prod.presentacion_defecto) ||
      opciones[0] || { id: 0, nombre: '', factor: 1, precio: prod.precio };
  }

  function agregar(prod, presentacionId) {
    if (prod.control_especial) {
      aviso('Medicamento de control especial: aún no se puede vender desde el POS.');
      return;
    }
    if (prod.stock <= 0) { aviso('Producto agotado.'); return; }

    // Solo las presentaciones que se pueden vender (si no se vende suelto,
    // la unidad mínima no aparece: vendible = false)
    const opciones = prod.presentaciones && prod.presentaciones.length
      ? prod.presentaciones.filter((x) => x.vendible !== false)
      : [{ id: 0, nombre: '', factor: 1, precio: prod.precio }];
    if (presentacionId != null && !opciones.some((x) => x.id === presentacionId)) {
      presentacionId = prod.presentacion_defecto;     // ej. escanearon el código de la pasta
    }
    if (presentacionId == null) {
      // Si la ficha dice "vender por defecto como Sobre x 10", se agrega directo.
      // Si no, y hay varias presentaciones, se pregunta "¿Cómo lo vendes?".
      if (prod.presentacion_defecto) presentacionId = prod.presentacion_defecto;
      else if (opciones.length > 1) { elegirPresentacion(prod); return; }
      else presentacionId = opciones[0].id;
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
          it.libre ? 'Venta libre' + (it.iva_tarifa > 0 ? ' · IVA ' + it.iva_tarifa + '%' : '') : '',
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
    // Botón flotante del celular ("Carrito 3 · $6.000 · Ver"): se esconde si está vacío
    const barra = $('pos-ir-carrito');
    if (barra) {
      barra.classList.toggle('vacio', !carrito.length);
      $('pos-ir-n').textContent = carrito.length;
      $('pos-ir-total').textContent = peso(total);
    }
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
          // Vaciar = quitar los productos de ESTA venta (la pestaña sigue abierta)
          if (ok) { carrito.splice(0); seleccionado = -1; pintarCarrito(); }
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
  // "async" = la función puede esperar (await) a que el cajero responda
  // en la ventana del programa. Por eso quien la llama usa "await".
  async function pedirMotivosDePrecio() {
    for (const it of carrito) {
      if (!cambioDePrecio(it)) { it.motivo_precio = null; continue; }
      if (!(it.precio > 0)) {
        aviso('"' + it.nombre + '" quedó con precio 0. Corrígelo antes de cobrar.');
        return false;
      }
      // Si ya dio un motivo para ESTE mismo precio, no se lo volvemos a pedir.
      if (it.motivo_precio && it.motivo_precio_valor === it.precio) continue;
      // Ventana propia (ui.js) en vez de prompt() del navegador
      const datos = await window.pedirDatos({
        titulo: 'Motivo del cambio de precio',
        texto: '"' + it.nombre + '": de ' + peso(it.precio_original) + ' a ' + peso(it.precio) + '.',
        campos: [{ nombre: 'motivo', etiqueta: 'Motivo (obligatorio)', minimo: 3, maximo: 200,
                   placeholder: 'Ej: descuento a cliente frecuente' }],
        textoAceptar: 'Continuar',
      });
      if (datos === null) {
        aviso('Sin motivo no se puede cambiar un precio.');
        return false;
      }
      it.motivo_precio = datos.motivo;
      it.motivo_precio_valor = it.precio;   // recordamos para qué precio fue el motivo
    }
    guardarCarrito();
    return true;
  }

  async function abrirPago() {
    if (carrito.some((i) => !(i.cantidad > 0))) {
      aviso('Hay un producto con cantidad 0. Corrígelo o quítalo.');
      return;
    }
    if (!carrito.length) return;
    if (!(await pedirMotivosDePrecio())) return;
    $('pago-total').textContent = peso(totalVenta());
    $('pago-form').style.display = '';
    $('pago-exito').style.display = 'none';
    $('pago-error').style.display = 'none';
    $('pago-recibido').value = '';
    clienteCredito = null;              // cada cobro empieza sin cliente de crédito
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
    // Crédito: se muestra el buscador de clientes de Cartera
    $('pago-credito').hidden = forma !== 'credito';
    if (forma === 'credito') {
      pintarClienteCredito();
      if (!clienteCredito) { $('credito-buscar').value = ''; buscarClientesCredito(''); $('credito-buscar').focus(); }
    }
  }

  // ---------------------------------------------------------------
  // 7b. VENTA A CRÉDITO: escoger el cliente (ver app/cartera.py)
  // ---------------------------------------------------------------
  let clienteCredito = null;          // el cliente escogido para esta venta a crédito
  let ultimosClientes = [];           // resultados de la última búsqueda
  let esperaBusqueda = null;

  // Pide al servidor los clientes que coinciden con lo escrito
  async function buscarClientesCredito(q) {
    try {
      const resp = await fetch($('url-api-clientes').value + '?q=' + encodeURIComponent(q),
                               { credentials: 'same-origin' });
      const json = await resp.json();
      ultimosClientes = json.clientes || [];
    } catch (e) { ultimosClientes = []; }
    const caja = $('credito-resultados');
    if (!ultimosClientes.length) {
      caja.innerHTML = '<p class="suave" style="margin:.3rem 0">No hay clientes con ese nombre. ' +
        'Regístralos en Cartera → Nuevo cliente.</p>';
      return;
    }
    caja.innerHTML = ultimosClientes.map((c, i) =>
      '<button type="button" class="credito-opcion" data-i="' + i + '">' +
        '<strong>' + esc(c.nombre) + '</strong>' +
        '<span>' + esc(c.documento || c.telefono || '') + '</span>' +
        '<small>' + (c.saldo > 0.5 ? 'debe ' + peso(c.saldo) : 'al día') +
        (c.disponible != null ? ' · disponible ' + peso(Math.max(c.disponible, 0)) : ' · sin límite') + '</small>' +
      '</button>').join('');
  }

  // Muestra la tarjeta del cliente escogido (o el buscador si no hay)
  function pintarClienteCredito() {
    const tarjeta = $('credito-elegido');
    const buscar = $('credito-buscar').closest('label');
    if (!clienteCredito) {
      tarjeta.hidden = true; buscar.hidden = false; $('credito-resultados').hidden = false;
      return;
    }
    const c = clienteCredito;
    const despues = c.saldo + totalVenta();
    const pasa = c.disponible != null && totalVenta() > c.disponible + 0.5;
    tarjeta.innerHTML = '<div><strong>' + esc(c.nombre) + '</strong> ' + esc(c.documento || '') + '<br>' +
      '<small>Debe ' + peso(c.saldo) + ' · con esta venta quedará debiendo <strong>' + peso(despues) + '</strong>' +
      (c.cupo != null ? ' · cupo ' + peso(c.cupo) : '') + '</small>' +
      (pasa ? '<br><small class="credito-sin-cupo">No le alcanza el cupo: le quedan ' +
        peso(Math.max(c.disponible, 0)) + '.</small>' : '') + '</div>' +
      '<button type="button" class="boton secundario" id="credito-cambiar">Cambiar</button>';
    tarjeta.hidden = false; buscar.hidden = true; $('credito-resultados').hidden = true;
    $('credito-cambiar').addEventListener('click', () => {
      clienteCredito = null; pintarClienteCredito(); $('credito-buscar').focus();
    });
  }

  $('credito-buscar').addEventListener('input', (e) => {
    clearTimeout(esperaBusqueda);       // espera a que deje de escribir (300 ms)
    esperaBusqueda = setTimeout(() => buscarClientesCredito(e.target.value.trim()), 300);
  });
  $('credito-resultados').addEventListener('click', (e) => {
    const b = e.target.closest('.credito-opcion');
    if (!b) return;
    clienteCredito = ultimosClientes[+b.dataset.i];
    pintarClienteCredito();
  });

  function actualizarCambio() {
    const recibido = parseFloat($('pago-recibido').value);
    const cambio = isNaN(recibido) ? 0 : recibido - totalVenta();
    $('pago-cambio').textContent = cambio >= 0 ? peso(cambio) : 'Falta ' + peso(-cambio);
  }

  async function confirmarVenta() {
    if (cobrando) return;
    const errorBox = $('pago-error');
    errorBox.style.display = 'none';
    if (formaPago === 'credito' && !clienteCredito) {
      errorBox.textContent = 'Escoge el cliente al que se le fía.';
      errorBox.style.display = 'block';
      return;
    }

    const datos = new FormData();
    datos.append('_csrf', csrf());
    // Por cada producto mandamos solo lo necesario. El precio normal NO se manda:
    // lo pone el servidor. Solo si el cajero lo cambió viajan precio_nuevo y motivo_precio.
    datos.append('carrito', JSON.stringify(carrito.map((i) => {
      // Venta libre: aquí SÍ viaja el precio, porque no hay uno guardado
      if (i.libre) {
        return { libre: 1, descripcion: i.nombre, precio: i.precio, cantidad: i.cantidad,
                 descuento_pct: i.descuento_pct, iva_tarifa: i.iva_tarifa,
                 costo: i.costo === '' || i.costo == null ? null : i.costo };
      }
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
    if (formaPago === 'credito') datos.append('cliente_id', clienteCredito.id);

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
      limpiarCarrito();   // cierra la venta cobrada (si hay otras abiertas, pasa a la siguiente)
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
  // Ventanas propias (window.pedirDatos, en static/js/ui.js) en vez de
  // prompt(): se ven como el resto del programa y piden todo de una vez.
  async function pedirCliente() {
    const datos = await window.pedirDatos({
      titulo: 'Cliente de esta venta',
      texto: 'Déjalo vacío para "Consumidor final".',
      campos: [
        { nombre: 'nombre', etiqueta: 'Nombre', valor: cliente.nombre, placeholder: 'Consumidor final', maximo: 120 },
        { nombre: 'documento', etiqueta: 'Documento (opcional)', valor: cliente.documento, placeholder: 'Cédula o NIT', maximo: 30 },
      ],
    });
    if (datos === null) return;           // canceló: no cambia nada
    cliente = { nombre: datos.nombre, documento: datos.documento };
    guardarCarrito();                     // queda guardado aunque se vaya la luz
    aviso(cliente.nombre ? 'Cliente: ' + cliente.nombre : 'Consumidor final');
  }
  async function pedirNota() {
    const datos = await window.pedirDatos({
      titulo: 'Nota de la venta',
      campos: [{ nombre: 'nota', etiqueta: 'Nota', tipo: 'area', valor: nota, maximo: 300,
                 placeholder: 'Ej: domicilio a la calle 5' }],
    });
    if (datos === null) return;
    nota = datos.nota;
    guardarCarrito();
    aviso(nota ? 'Nota guardada' : 'Nota borrada');
  }
  // VENTA LIBRE: vender algo que no está en el inventario (una inyectología,
  // una toma de presión, una fotocopia...). Entra al carrito como una línea
  // más, pero al cobrar no descuenta nada del inventario.
  async function pedirVentaLibre() {
    const datos = await window.pedirDatos({
      titulo: 'Venta libre',
      texto: 'Para cobrar algo que no está en el inventario (ej: inyectología, toma de presión).',
      campos: [
        { nombre: 'descripcion', etiqueta: '¿Qué se vende?', minimo: 3, maximo: 120,
          placeholder: 'Ej: Inyectología' },
        { nombre: 'precio', etiqueta: 'Precio de cada uno (con IVA)', tipo: 'numero',
          obligatorio: true, mayorQue: 0, placeholder: 'Ej: 5000' },
        { nombre: 'cantidad', etiqueta: 'Cantidad', tipo: 'numero', valor: '1', mayorQue: 0 },
        { nombre: 'iva', etiqueta: 'IVA', tipo: 'opciones', opciones: [
          { valor: '0', texto: 'Sin IVA (excluido o exento)' },
          { valor: '19', texto: 'IVA 19 %' },
          { valor: '5', texto: 'IVA 5 %' },
        ] },
        { nombre: 'costo', etiqueta: 'Costo de cada uno (opcional)', tipo: 'numero', minimoNumero: 0,
          ayuda: 'Lo que le cuesta a la droguería (jeringa, algodón...). Sirve para calcular la ganancia.' },
      ],
      textoAceptar: 'Agregar al carrito',
    });
    if (datos === null) return;
    const tarifa = Number(datos.iva) || 0;
    carrito.push({
      libre: true,                         // así se reconoce en todo el código
      producto_id: null, presentacion_id: 0, presentacion: '', factor: 1, stock_base: 0,
      nombre: datos.descripcion,
      precio: datos.precio,
      precio_original: null,               // no hay precio "normal" con qué comparar
      cantidad: datos.cantidad === '' ? 1 : datos.cantidad,
      descuento_pct: 0,
      iva_tipo: tarifa > 0 ? 'gravado' : 'excluido',
      iva_tarifa: tarifa,
      costo: datos.costo,
    });
    seleccionar(carrito.length - 1);
    pintarCarrito();
    aviso('Agregado: ' + datos.descripcion);
  }
  $('btn-venta-libre').addEventListener('click', pedirVentaLibre);

  // OTRO INGRESO: plata que entra y NO es una venta (comisión de recargas,
  // arriendo, reciclaje...). Si es en efectivo, entra a esta caja.
  async function pedirOtroIngreso() {
    let categorias = [];
    try { categorias = JSON.parse($('categorias-ingreso').textContent || '[]'); } catch (e) { /* vacío */ }
    if (!categorias.length) {
      aviso('No hay categorías de ingreso. Créalas en Administración → Catálogos.');
      return;
    }
    const datos = await window.pedirDatos({
      titulo: 'Otro ingreso',
      texto: 'Plata que entra y NO es una venta: comisión de recargas, arriendo, reciclaje…',
      campos: [
        { nombre: 'categoria_id', etiqueta: 'Categoría', tipo: 'opciones',
          opciones: categorias.map((c) => ({ valor: String(c.id), texto: c.nombre })) },
        { nombre: 'descripcion', etiqueta: 'Descripción', minimo: 3, maximo: 200,
          placeholder: 'Ej: comisión recargas de la semana' },
        { nombre: 'monto', etiqueta: 'Monto', tipo: 'numero', obligatorio: true, mayorQue: 0 },
        { nombre: 'forma_pago', etiqueta: 'Cómo llegó la plata', tipo: 'opciones', opciones: [
          { valor: 'efectivo', texto: 'Efectivo (entra a esta caja)' },
          { valor: 'nequi', texto: 'Nequi' },
          { valor: 'davivienda', texto: 'Davivienda' },
          { valor: 'transferencia', texto: 'Transferencia' },
        ] },
      ],
      textoAceptar: 'Registrar ingreso',
    });
    if (datos === null) return;
    const form = new FormData();
    form.append('_csrf', csrf());
    for (const clave in datos) form.append(clave, datos[clave]);
    try {
      const resp = await fetch($('url-api-otro-ingreso').value,
        { method: 'POST', body: form, credentials: 'same-origin' });
      const json = await resp.json();
      if (!json.ok) { window.avisar(json.error || 'No se pudo registrar.', 'error'); return; }
      window.avisar('Ingreso registrado: ' + datos.descripcion + ' · ' + peso(datos.monto), 'ok');
    } catch (e) {
      window.avisar('Error de conexión: ' + e.message, 'error');
    }
  }
  // ABONO DE CARTERA: un cliente paga (todo o parte) de lo que debe.
  async function pedirAbono() {
    let deudores = [];
    try {
      const resp = await fetch($('url-api-clientes').value + '?con_saldo=1', { credentials: 'same-origin' });
      deudores = (await resp.json()).clientes || [];
    } catch (e) { /* sin conexión: la lista queda vacía */ }
    if (!deudores.length) { aviso('Ningún cliente debe nada en este momento.'); return; }
    const datos = await window.pedirDatos({
      titulo: 'Abono de cartera',
      texto: 'El cliente paga todo o una parte de lo que debe. Los abonos pagan primero las ventas más viejas.',
      campos: [
        { nombre: 'cliente_id', etiqueta: 'Cliente', tipo: 'opciones',
          opciones: deudores.map((c) => ({ valor: String(c.id), texto: c.nombre + ' — debe ' + peso(c.saldo) })) },
        { nombre: 'monto', etiqueta: 'Monto del abono', tipo: 'numero', obligatorio: true, mayorQue: 0 },
        { nombre: 'forma_pago', etiqueta: 'Cómo pagó', tipo: 'opciones', opciones: [
          { valor: 'efectivo', texto: 'Efectivo (entra a esta caja)' },
          { valor: 'nequi', texto: 'Nequi' },
          { valor: 'davivienda', texto: 'Davivienda' },
          { valor: 'transferencia', texto: 'Transferencia' },
          { valor: 'tarjeta', texto: 'Tarjeta' },
        ] },
        { nombre: 'observaciones', etiqueta: 'Observaciones (opcional)', maximo: 200 },
      ],
      textoAceptar: 'Registrar abono',
    });
    if (datos === null) return;
    const form = new FormData();
    form.append('_csrf', csrf());
    for (const clave in datos) form.append(clave, datos[clave]);
    try {
      const resp = await fetch($('url-api-abono').value, { method: 'POST', body: form, credentials: 'same-origin' });
      const json = await resp.json();
      if (!json.ok) { window.avisar(json.error || 'No se pudo registrar el abono.', 'error'); return; }
      const imprimir = await window.confirmar(
        'Abono ' + json.numero + ' registrado. Saldo pendiente: ' + peso(json.saldo) + '. ¿Imprimir el recibo?',
        { titulo: 'Abono registrado', icono: '✅', tipo: 'info', textoAceptar: 'Imprimir recibo', textoCancelar: 'No' });
      if (imprimir) window.open(json.url_recibo, '_blank');
    } catch (e) {
      window.avisar('Error de conexión: ' + e.message, 'error');
    }
  }

  // Para que el botón de la ventana "Ingreso de efectivo" (pos.js) la pueda abrir
  window.pedirOtroIngreso = pedirOtroIngreso;
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
      else if (accion === 'venta-libre') { cerrar(); pedirVentaLibre(); }
      else if (accion === 'otro-ingreso') { cerrar(); pedirOtroIngreso(); }
      else if (accion === 'abono-cartera') { cerrar(); pedirAbono(); }
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
    // "A la mano" como se vende (29 sobres + 5 tab.) y entre paréntesis en pastas
    $('info-a-la-mano').textContent = 'A la mano: ' + textoExistencias(p, p.stock) +
      (defectoDe(p).factor > 1 ? ' (' + cant(p.stock) + ' en total)' : '');
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
      ' · hay ' + textoExistencias(prod, prod.stock);
    // Unidades que ya están en el carrito de este producto (cualquier presentación)
    const enCarrito = carrito.reduce((suma, x) =>
      x.producto_id === prod.id ? suma + x.cantidad * x.factor : suma, 0);
    $('pres-opciones').innerHTML = prod.presentaciones.filter((x) => x.vendible !== false).map((x, i) => {
      const alcanza = prod.stock - enCarrito >= x.factor - 1e-9;
      const trae = x.factor === 1 ? 'unidad de inventario' : 'trae ' + (+x.factor.toFixed(2));
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
    if (!prod) return;
    // Tocar "📦 Otras: ..." abre "¿Cómo lo vendes?" para escoger otra presentación
    if (e.target.closest('[data-elegir]') && vendibles(prod).length > 1) {
      if (prod.control_especial) agregar(prod);        // muestra el aviso de siempre
      else if (prod.stock <= 0) aviso('Producto agotado.');
      else elegirPresentacion(prod);
    } else {
      agregar(prod);
    }
    // Si se abrió "¿Cómo lo vendes?", el foco se queda en sus botones (teclas 1, 2, 3)
    if (!modalPres || modalPres.classList.contains('modal-oculto')) inputBusqueda.focus();
  });

  // F4 = nueva venta (atender a otro cliente). Funciona aunque se esté
  // escribiendo en el buscador, pero no con una ventana abierta.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'F4') return;
    if (document.querySelector('[id^="modal-"]:not(.modal-oculto)')) return;
    e.preventDefault();
    nuevaVenta();
  });

  // Pestañas de ventas: cambiar, descartar o abrir una nueva
  const tabsVentas = $('pos-ventas-tabs');
  if (tabsVentas) {
    tabsVentas.addEventListener('click', (e) => {
      const ir = e.target.closest('[data-venta]');
      const cerrar = e.target.closest('[data-cerrar]');
      if (cerrar) cerrarVenta(+cerrar.dataset.cerrar);
      else if (ir) cambiarVenta(+ir.dataset.venta);
      else if (e.target.closest('#pos-venta-nueva')) nuevaVenta();
    });
  }

  $('pos-categorias').addEventListener('click', (e) => {
    const boton = e.target.closest('.pos-cat');
    // "+ Venta libre" vive en esta fila pero NO es un filtro: tiene su propio clic
    if (!boton || boton.classList.contains('pos-cat-libre')) return;
    document.querySelectorAll('.pos-cat').forEach((b) => b.classList.remove('activo'));
    boton.classList.add('activo');
    categoria = boton.dataset.cat;
    buscar(false);
  });

  pintarCarrito();
  buscar(false);
})();
