// =====================================================================
// LO PRIMERO QUE CARGA CADA PÁGINA (va en el <head> de base.html)
// ---------------------------------------------------------------------
// Versión 1.1.15: antes estaba escrito dentro de base.html. Va en el <head> (no en
// ui.js) porque los scripts de cada página lo usan apenas cargan.
//   1. Reintento con la clave nueva (_csrf) y respuestas en JSON (fetch envuelto).
//   2. Chip del laboratorio (window.chipLaboratorio).
//   3. Registro del "service worker" para instalar el programa desde Chrome.
// =====================================================================
// ------------------------------------------------------------------
// REINTENTO CON LA CLAVE NUEVA (versión 1.1.11)
// Cada página trae una "clave de seguridad" (_csrf). Si se vuelve a entrar al
// programa en OTRA ventana, la clave cambia y esta página queda con la vieja: al
// cobrar, el programa la rechaza. Ahora el programa contesta con la clave nueva
// (csrf_nuevo): aquí se cambia en toda la página y el pedido se repite UNA vez,
// solo. La persona ni se entera. (Ver auth.verificar_csrf.)
// ------------------------------------------------------------------
//
// Además, si un pedido de datos (/api/...) recibe una PÁGINA WEB en vez de datos
// (la pantalla de Ingresar, o una página de error), se cambia por un mensaje claro
// en JSON. Así ninguna pantalla vuelve a mostrar "Unexpected token '<'".
// ------------------------------------------------------------------
(function () {
  const fetchOriginal = window.fetch.bind(window);
  function direccion(url) { return String((url && url.url) || url || ''); }
  function comoJSON(resp, url) {
    const tipo = resp.headers.get('content-type') || '';
    // (1.1.16: una FOTO también es una respuesta buena: la manda «Buscar foto» de la ficha)
    if (tipo.indexOf('json') >= 0 || tipo.indexOf('image/') === 0 || direccion(url).indexOf('/api/') < 0) return resp;
    const alIngreso = resp.redirected && resp.url.indexOf('/login') >= 0;
    const mensaje = (alIngreso || resp.status === 401)
      ? 'Tu sesión se cerró. Recarga la página con F5, entra otra vez y vuelve a intentarlo: esto NO se guardó.'
      : 'El programa respondió con un error (código ' + resp.status + '). Recarga la página con F5 y, '
        + 'antes de repetirlo, revisa si quedó guardado.';
    return new Response(JSON.stringify({ ok: false, error: mensaje, sesion: alIngreso || resp.status === 401 }),
                        { status: resp.status, headers: { 'Content-Type': 'application/json' } });
  }
  window.fetch = async function (url, opciones) {
    const resp = await fetchOriginal(url, opciones);
    const cuerpo = opciones && opciones.body;
    if (resp.status !== 400 || !(cuerpo instanceof FormData) || !cuerpo.has('_csrf')) return comoJSON(resp, url);
    let datos = null;
    try { datos = await resp.clone().json(); } catch (e) { return comoJSON(resp, url); }
    if (!datos || !datos.csrf_nuevo) return resp;
    document.querySelectorAll('input[name="_csrf"]').forEach(function (i) { i.value = datos.csrf_nuevo; });
    cuerpo.set('_csrf', datos.csrf_nuevo);
    return comoJSON(await fetchOriginal(url, opciones), url);   // segundo y último intento
  };
})();

// Cuántas unidades trae una unidad de medida: su cantidad, o si quedó en 1,
// lo que diga el nombre ("CAJA X 12" -> 12). Igual que presentaciones.cantidad_efectiva
window.cantidadDeUnidad = function (nombre, cantidad) {
  cantidad = parseFloat(cantidad) || 1;
  if (cantidad <= 1) {
    const m = String(nombre || '').match(/x\s*(\d+(?:[.,]\d+)?)\s*$/i);
    if (m) return parseFloat(m[1].replace(',', '.'));
  }
  return cantidad;
};

// ===== Orden de las listas (versión 1.1.6, igual que app/nombres.py) =====
// Comparar como en el diccionario: sin tildes ni mayúsculas ("Ácido" va con la A).
window.compararNombres = function (a, b) {
  return String(a || '').localeCompare(String(b || ''), 'es', { sensitivity: 'base' });
};
// Unidades: "Unidad" primero y después por tamaño (Sello x 4, Caja x 10, Sello x 10...)
window.compararUnidades = function (a, b) {
  const esUnidad = (u) => String(u.nombre || '').trim().toLowerCase() === 'unidad' ? 0 : 1;
  return (esUnidad(a) - esUnidad(b)) ||
    (window.cantidadDeUnidad(a.nombre, a.cantidad) - window.cantidadDeUnidad(b.nombre, b.cantidad)) ||
    window.compararNombres(a.nombre, b.nombre);
};
// Mete una opción NUEVA (creada con el botón +) en su lugar de la lista, no al final.
// Las opciones vacías del principio ("— Seleccionar —") se quedan arriba.
window.insertarOrdenado = function (sel, opcion, esUnidad) {
  const datos = (o) => ({ nombre: o.textContent.trim(), cantidad: o.dataset.cantidad });
  const nueva = datos(opcion);
  const siguiente = Array.from(sel.options).find(function (o) {
    if (o.value === '' || o === opcion) return false;
    return esUnidad ? window.compararUnidades(datos(o), nueva) > 0
                    : window.compararNombres(o.textContent.trim(), nueva.nombre) > 0;
  });
  sel.insertBefore(opcion, siguiente || null);
};

// ===== Campo de VARIOS nombres separados por comas, con sugerencias (versión 1.1.6) =====
// Lo usan los principios activos: "acetaminofén, codeína". Mientras se escribe
// el nombre que va después de la última coma, se muestran los que ya existen
// (sin importar tildes ni mayúsculas). Clic o Enter = se pone ese y una coma.
// input = el campo de texto; opciones = lista de nombres ['Acetaminofén', ...]
window.campoConComas = function (input, opciones) {
  if (!input || input.dataset.comas) return;
  input.dataset.comas = '1';
  input.setAttribute('autocomplete', 'off');
  const plano = (t) => String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const lista = document.createElement('div');
  lista.className = 'comas-sugerencias';
  lista.hidden = true;
  input.insertAdjacentElement('afterend', lista);
  let elegida = -1;
  function partes() { return input.value.split(','); }
  function pintar() {
    const p = partes();
    const actual = plano(p[p.length - 1]);
    const ya = p.slice(0, -1).map(plano);
    const encontrados = actual ? opciones.filter((o) => plano(o).includes(actual) && !ya.includes(plano(o))).slice(0, 8) : [];
    elegida = encontrados.length ? 0 : -1;
    lista.innerHTML = '';
    encontrados.forEach(function (o, i) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = o;
      if (i === 0) b.classList.add('activa');
      b.addEventListener('mousedown', (e) => { e.preventDefault(); poner(o); });
      lista.appendChild(b);
    });
    lista.hidden = !encontrados.length;
  }
  function poner(nombre) {
    const p = partes();
    p[p.length - 1] = ' ' + nombre;
    input.value = p.map((x) => x.trim()).filter(Boolean).join(', ') + ', ';
    lista.hidden = true;
    input.focus();
  }
  input.addEventListener('input', pintar);
  input.addEventListener('keydown', function (e) {
    const botones = lista.querySelectorAll('button');
    if (lista.hidden || !botones.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      elegida = (elegida + (e.key === 'ArrowDown' ? 1 : -1) + botones.length) % botones.length;
      botones.forEach((b, i) => b.classList.toggle('activa', i === elegida));
    } else if (e.key === 'Enter' && elegida >= 0) {
      e.preventDefault();                     // no enviar el formulario: escoger la sugerencia
      poner(botones[elegida].textContent);
    } else if (e.key === 'Escape') {
      lista.hidden = true;
    }
  });
  input.addEventListener('blur', function () {
    setTimeout(() => { lista.hidden = true; }, 150);
    // Al salir, se quita la coma suelta del final
    input.value = input.value.split(',').map((x) => x.trim()).filter(Boolean).join(', ');
  });
};

// Versión 1.1.3: etiqueta del LABORATORIO para los resultados de búsqueda.
// Hay productos que se llaman igual y solo cambia el laboratorio
// (TRAZODONA 50 MG · SAN FER / · GENFAR): por eso se muestra bien visible.
// Si el producto no tiene laboratorio, lo dice (para completarlo en Productos).
// Devuelve HTML: el nombre se "escapa" para que un nombre con < > no rompa la página.
window.chipLaboratorio = function (lab) {
  const seguro = String(lab || '').replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
  return seguro
    ? '<span class="lab-chip" title="Laboratorio">' + seguro + '</span>'
    : '<span class="lab-chip sin-lab" title="Este producto no tiene laboratorio: complétalo en Productos">Sin laboratorio</span>';
};

// Registra el "service worker" (app/instalable.py). Solo funciona en direcciones
// seguras (localhost o https); en las demás el navegador lo ignora sin dar error.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js').catch(function () {});
  });
}
