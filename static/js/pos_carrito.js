// =====================================================================
// POS · CARRITO DE VENTAS
// =====================================================================
// Este archivo controla la pantalla de venta:
//   1. Buscar productos (por nombre o escaneando el código de barras)
//   2. Armar el carrito (agregar, cambiar cantidad, descuento, quitar)
//   3. Cobrar (efectivo, Nequi, Davivienda, tarjeta)
//
// IMPORTANTE: aquí en el navegador SOLO se muestran los totales para que
// el cajero los vea. El servidor (app/pos.py) vuelve a calcular todo con
// los precios reales de la base de datos. Por eso es seguro.
// =====================================================================
(function () {
  'use strict';

  // ---------------------------------------------------------------
  // 1. DATOS QUE RECUERDA LA PANTALLA (el "estado")
  // ---------------------------------------------------------------
  let carrito = [];              // lista de productos que se van a vender
  let seleccionado = -1;         // posición de la línea seleccionada (-1 = ninguna)
  let modo = 'cantidad';         // qué edita el teclado numérico: 'cantidad' o 'descuento'
  let buffer = '';               // números que se están tecleando en el teclado numérico
  let escribiendo = false;       // ¿ya empezó a teclear un número nuevo?
  let categoria = '';            // categoría activa en los botones de arriba ('' = todas)
  let productosMostrados = [];   // resultado de la última búsqueda
  let numeroBusqueda = 0;        // para ignorar respuestas viejas si el cajero escribe rápido
  let formaPago = 'efectivo';
  let cliente = { nombre: '', documento: '' };
  let nota = '';
  let cobrando = false;          // evita doble clic en "Confirmar venta"

  // ---------------------------------------------------------------
  // 2. AYUDAS PEQUEÑAS
  // ---------------------------------------------------------------
  const $ = (id) => document.getElementById(id);   // atajo: $('algo') busca el elemento con id="algo"

  // Convierte un número a pesos: 12500 -> "$12.500"
  const peso = (n) => '$' + Math.round(n).toLocaleString('es-CO');

  // Evita que un texto raro (como <script>) se interprete como código HTML.
  function esc(texto) {
    return String(texto == null ? '' : texto)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Redondeo al peso (igual que el servidor: 0.5 sube).
  const aPesos = (v) => Math.floor(v + 0.5);

  // Token de seguridad que el servidor exige en cada envío.
  const csrf = () => (document.querySelector('input[name="_csrf"]') || {}).value || '';

  // Mensaje flotante que desaparece solo a los 3 segundos.
  function aviso(texto) {
    const div = document.createElement('div');
    div.className = 'pos-toast';
    div.textContent = texto;
    document.body.appendChild(div);
    setTimeout(() => div.remove(), 3000);
  }

  // Direcciones (URLs) que la página nos entrega en campos ocultos.
  const URL = {
    productos: $('url-api-productos') && $('url-api-productos').value,
    cobrar: $('url-api-cobrar') && $('url-api-cobrar').value,
    ventas: $('url-ventas') && $('url-ventas').value,
    ultima: $('url-ultima-venta') && $('url-ultima-venta').value,
    inventario: $('url-inventario') && $('url-inventario').value,
    estaticos: ($('url-static-base') && $('url-static-base').value) || '/static/',
  };
  // Si faltan los campos ocultos, esta no es la pantalla del POS: no hacemos nada.
  if (!URL.productos || !URL.cobrar) return;

  const inputBusqueda = $('pos-input-busqueda');
  const grid = $('pos-grid');
  const contenedorCarrito = $('pos-carrito-items');
  const btnPago = $('btn-pago');

  // ---------------------------------------------------------------
  // 3. CÁLCULO DE UNA LÍNEA (igual que en el servidor)
  // ---------------------------------------------------------------
  // El precio de venta YA INCLUYE el IVA. Si el producto es "gravado",
  // separamos cuánto de ese precio es IVA.
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
  // Si desdeEnter es true (el cajero presionó Enter, típico de un lector
  // de código de barras) y sale un solo producto, se agrega directo al carrito.
  async function buscar(desdeEnter) {
    const miNumero = ++numeroBusqueda;
    const q = inputBusqueda.value.trim();
    const url = URL.productos + '?q=' + encodeURIComponent(q) + '&cat=' + encodeURIComponent(categoria);
    try {
      const resp = await fetch(url, { credentials: 'same-origin' });
      const json = await resp.json();
      if (miNumero !== numeroBusqueda || !json.ok) return;   // llegó una respuesta vieja: se ignora
      productosMostrados = json.productos;
      pintarProductos();
      if (desdeEnter) {
        if (json.productos.length === 1) {
          agregar(json.productos[0]);
          inputBusqueda.value = '';
          buscar(false);                                      // vuelve a mostrar la lista completa
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
      // Ya estaba en el carrito: sumamos 1, sin pasar el stock disponible.
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
    escribiendo = false;     // el próximo número que teclee reemplaza al anterior
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

    // Totales de toda la venta
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

  // Clics dentro del carrito: botones − + 🗑, o seleccionar una línea.
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
  });

  // ---------------------------------------------------------------
  // 6. TECLADO NUMÉRICO (para cantidad y descuento)
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
    b.addEventListener('click', () => teclear(b.dataset.key));
  });
  marcarModo();

  // ---------------------------------------------------------------
  // 7. COBRAR
  // ---------------------------------------------------------------
  const modalPago = $('modal-pago');

  function abrirPago() {
    // Revisamos que ninguna línea tenga cantidad 0.
    if (carrito.some((i) => !(i.cantidad > 0))) {
      aviso('Hay un producto con cantidad 0. Corrígelo o quítalo.');
      return;
    }
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
    if (cobrando) return;               // ya se está enviando: evita cobrar dos veces
    const errorBox = $('pago-error');
    errorBox.style.display = 'none';

    const datos = new FormData();
    datos.append('_csrf', csrf());
    // Al servidor solo le mandamos qué producto, cuánta cantidad y el % de descuento.
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
        buscar(false);                 // por si el stock cambió, refresca los números
        return;
      }
      // ¡Venta guardada! Mostramos el resultado y dejamos todo listo para la siguiente.
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
  // 8. CLIENTE, NOTA Y MENÚ LATERAL
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

  document.querySelectorAll('.pos-drawer-item').forEach((b) => {
    b.addEventListener('click', () => {
      const accion = b.dataset.accion;
      const cerrar = () => { const d = $('pos-drawer'); if (d) d.setAttribute('hidden', ''); };
      if (accion === 'ultimas-ventas') window.location.href = URL.ventas;
      else if (accion === 'reimprimir') window.open(URL.ultima, '_blank');
      else if (accion === 'consulta-inventario') window.location.href = URL.inventario;
      else if (accion === 'cliente') { cerrar(); pedirCliente(); }
      else if (accion === 'nota') { cerrar(); pedirNota(); }
    });
  });

  // ---------------------------------------------------------------
  // 9. ARRANQUE: conectar la búsqueda y mostrar productos
  // ---------------------------------------------------------------
  let temporizador = null;
  inputBusqueda.addEventListener('input', () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(() => buscar(false), 250);   // espera 0,25 s tras dejar de escribir
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
