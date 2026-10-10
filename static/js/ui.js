/* =====================================================================
   FERVIFARMA · ui.js — piezas de pantalla que usan TODAS las páginas
   ---------------------------------------------------------------------
   Este archivo se carga en base.html, así que funciona en cualquier
   página del programa. Tiene tres herramientas:

     1. MENSAJES TIPO "TOAST"  → window.avisar('Guardado', 'ok')
        Cuadritos que aparecen arriba a la derecha y se van solos.

     2. VENTANA PARA PEDIR DATOS → await window.pedirDatos({...})
        Reemplaza la ventana gris del navegador (prompt), que se ve fea
        y en inglés. Ejemplo: pedir el nombre del cliente en el POS.

     3. FECHAS EN dd/mm/aaaa → automático en todo <input type="date">
        El calendario del navegador cambia según el idioma de Windows
        (a veces sale en inglés mm/dd/yyyy). Aquí lo cambiamos por uno
        propio en español. Al servidor le sigue llegando aaaa-mm-dd,
        así que el resto del programa NO tuvo que cambiar.

   Para aprender: todo está dentro de "(function () { ... })();".
   Eso se llama IIFE: una función que se ejecuta sola enseguida. Sirve
   para que las variables de aquí no choquen con las de otros archivos.
   ===================================================================== */
(function () {
  'use strict';   // modo estricto: JavaScript avisa de más errores

  /* ===================================================================
     1. MENSAJES TIPO TOAST
     =================================================================== */

  // Cuánto dura un mensaje bueno en pantalla (milisegundos: 5000 = 5 s).
  // Los de ERROR no se van solos: hay que cerrarlos con la ×, para que
  // nadie se pierda un problema por estar mirando para otro lado.
  const DURACION_OK = 5000;

  // Devuelve la caja donde se apilan los mensajes. Si la página no la
  // tiene (por ejemplo una página suelta), la crea.
  function cajaDeToasts() {
    let caja = document.getElementById('toasts');
    if (!caja) {
      caja = document.createElement('div');
      caja.id = 'toasts';
      caja.className = 'toasts';
      caja.setAttribute('aria-live', 'polite');   // lectores de pantalla lo leen
      document.body.appendChild(caja);
    }
    return caja;
  }

  // Le da vida a un mensaje: botón × para cerrarlo y, si es bueno,
  // un temporizador para que se vaya solo.
  function activarToast(el) {
    if (el.dataset.activo) return;        // ya estaba activado
    el.dataset.activo = '1';
    const cerrar = function () {
      el.classList.add('saliendo');       // animación de salida (CSS)
      setTimeout(function () { el.remove(); }, 250);
    };
    const boton = el.querySelector('.toast-cerrar');
    if (boton) boton.addEventListener('click', cerrar);
    if (!el.classList.contains('error')) setTimeout(cerrar, DURACION_OK);
  }

  // window.avisar('texto', 'ok' | 'error')  → muestra un mensaje nuevo.
  // "window." la deja disponible para cualquier otro archivo JS.
  window.avisar = function (texto, tipo) {
    tipo = tipo === 'error' ? 'error' : 'ok';
    const el = document.createElement('div');
    el.className = 'aviso toast ' + tipo;
    el.setAttribute('role', tipo === 'error' ? 'alert' : 'status');
    const span = document.createElement('span');
    span.className = 'toast-txt';
    span.textContent = texto;             // textContent = seguro, no ejecuta HTML
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'toast-cerrar';
    x.setAttribute('aria-label', 'Cerrar mensaje');
    x.textContent = '×';
    el.append(span, x);
    cajaDeToasts().appendChild(el);
    activarToast(el);
  };


  /* ===================================================================
     2. VENTANA PARA PEDIR DATOS (reemplaza a prompt)
     ---------------------------------------------------------------
     Uso:
       const datos = await window.pedirDatos({
         titulo: 'Cliente',
         texto: 'Explicación opcional',
         campos: [
           { nombre: 'nombre', etiqueta: 'Nombre', valor: 'Ana' },
           { nombre: 'nota', etiqueta: 'Nota', tipo: 'area', minimo: 3 },
         ],
         textoAceptar: 'Guardar',
       });
       if (datos === null) → la persona canceló
       si no → datos.nombre, datos.nota ... (texto ya sin espacios sobrantes)
     =================================================================== */
  window.pedirDatos = function (opciones) {
    opciones = opciones || {};
    // Una "Promise" (promesa) es una respuesta que llega después: cuando
    // la persona toque Guardar o Cancelar. Por eso se usa con "await".
    return new Promise(function (resolver) {
      const fondo = document.createElement('div');
      fondo.className = 'modal-fondo-ui';            // fondo oscuro
      // El id empieza por "modal-": así el POS sabe que hay una ventana
      // abierta y no usa el teclado para el carrito mientras tanto.
      fondo.id = 'modal-pedir-datos';
      const caja = document.createElement('form');   // <form>: Enter = Guardar
      caja.className = 'modal-caja modal-ui';
      caja.noValidate = true;                        // validamos nosotros

      const h2 = document.createElement('h2');
      h2.textContent = opciones.titulo || 'Datos';
      caja.appendChild(h2);

      if (opciones.texto) {
        const p = document.createElement('p');
        p.className = 'modal-ui-texto';
        p.textContent = opciones.texto;
        caja.appendChild(p);
      }

      // Un campo por cada elemento de opciones.campos
      const entradas = {};
      (opciones.campos || []).forEach(function (c) {
        const label = document.createElement('label');
        label.textContent = c.etiqueta || c.nombre;
        const input = c.tipo === 'area'
          ? document.createElement('textarea')
          : document.createElement('input');
        if (c.tipo === 'area') input.rows = 3; else input.type = 'text';
        input.value = c.valor || '';
        input.placeholder = c.placeholder || '';
        input.autocomplete = 'off';
        if (c.maximo) input.maxLength = c.maximo;
        label.appendChild(input);
        caja.appendChild(label);
        entradas[c.nombre] = { input: input, campo: c };
      });

      const error = document.createElement('p');
      error.className = 'aviso error';
      error.style.display = 'none';
      caja.appendChild(error);

      const acciones = document.createElement('div');
      acciones.className = 'modal-acciones';
      const cancelar = document.createElement('button');
      cancelar.type = 'button';
      cancelar.className = 'boton secundario';
      cancelar.textContent = opciones.textoCancelar || 'Cancelar';
      const aceptar = document.createElement('button');
      aceptar.type = 'submit';
      aceptar.className = 'boton';
      aceptar.textContent = opciones.textoAceptar || 'Guardar';
      acciones.append(cancelar, aceptar);
      caja.appendChild(acciones);

      fondo.appendChild(caja);
      document.body.appendChild(fondo);

      // Cierra la ventana y entrega la respuesta (null = canceló)
      function terminar(resultado) {
        document.removeEventListener('keydown', teclaEscape, true);
        fondo.remove();
        resolver(resultado);
      }
      function teclaEscape(e) {
        if (e.key === 'Escape') { e.stopPropagation(); terminar(null); }
      }

      cancelar.addEventListener('click', function () { terminar(null); });
      fondo.addEventListener('click', function (e) { if (e.target === fondo) terminar(null); });
      document.addEventListener('keydown', teclaEscape, true);

      // Guardar: revisa los mínimos y devuelve los valores
      caja.addEventListener('submit', function (e) {
        e.preventDefault();      // no recargar la página
        e.stopPropagation();
        const datos = {};
        for (const nombre in entradas) {
          const valor = entradas[nombre].input.value.trim();
          const minimo = entradas[nombre].campo.minimo || 0;
          if (valor.length < minimo) {
            error.textContent = (entradas[nombre].campo.etiqueta || nombre) +
              ': escribe al menos ' + minimo + ' letras.';
            error.style.display = '';
            entradas[nombre].input.focus();
            return;
          }
          datos[nombre] = valor;
        }
        terminar(datos);
      });

      // Pone el cursor en el primer campo (y selecciona su texto)
      // (de inmediato, para que no se pierda ninguna tecla)
      const primero = caja.querySelector('input, textarea');
      if (primero) { primero.focus(); if (primero.select) primero.select(); }
    });
  };


  /* ===================================================================
     3. FECHAS EN dd/mm/aaaa
     ---------------------------------------------------------------
     Cómo funciona, para cada <input type="date">:
       - El campo original se vuelve OCULTO, pero sigue con su "name",
         así que el formulario envía la fecha igual que antes (aaaa-mm-dd).
       - Al lado ponemos un campo de texto visible donde se escribe
         dd/mm/aaaa (las barras "/" se ponen solas) y un botón con un
         calendario en español.
       - Lo que se escribe en el visible se copia al oculto.
     =================================================================== */
  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
                 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const DIAS = ['lu', 'ma', 'mi', 'ju', 'vi', 'sá', 'do'];   // la semana empieza el lunes

  // Convierte texto a fecha y viceversa ---------------------------------
  function dosCifras(n) { return (n < 10 ? '0' : '') + n; }

  // '2026-10-10' → '10/10/2026'
  function isoATexto(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    return m ? m[3] + '/' + m[2] + '/' + m[1] : '';
  }
  // '10/10/2026' → '2026-10-10'   (o null si la fecha no existe, ej. 31/02)
  function textoAIso(texto) {
    const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec((texto || '').trim());
    if (!m) return null;
    const d = +m[1], mes = +m[2], a = +m[3];
    const f = new Date(a, mes - 1, d);
    // Si JavaScript "corrigió" la fecha (31/02 → 03/03), no existía
    if (f.getFullYear() !== a || f.getMonth() !== mes - 1 || f.getDate() !== d) return null;
    return a + '-' + dosCifras(mes) + '-' + dosCifras(d);
  }
  function fechaAIso(f) {
    return f.getFullYear() + '-' + dosCifras(f.getMonth() + 1) + '-' + dosCifras(f.getDate());
  }
  function hoyIso() { return fechaAIso(new Date()); }

  // Para que el código que hace  campo.value = '2026-01-31'  también
  // actualice lo que se ve, "envolvemos" la propiedad value del campo
  // oculto. Object.getOwnPropertyDescriptor toma el value original del
  // navegador; defineProperty pone uno nuestro que llama al original.
  const valueOriginal = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');

  function mejorarFecha(original) {
    if (original.dataset.fechaPropia) return;     // ya se mejoró
    original.dataset.fechaPropia = '1';

    // --- Campo visible ---
    const visible = document.createElement('input');
    visible.type = 'text';
    visible.inputMode = 'numeric';                // teclado de números en el celular
    visible.placeholder = 'dd/mm/aaaa';
    visible.maxLength = 10;
    visible.autocomplete = 'off';
    visible.className = 'fecha-texto';
    if (original.id) { visible.id = original.id + '-texto'; }
    visible.required = original.required;          // la obligación pasa al visible
    visible.disabled = original.disabled;
    if (original.getAttribute('aria-label')) visible.setAttribute('aria-label', original.getAttribute('aria-label'));

    // --- Botón del calendario ---
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'fecha-boton';
    boton.setAttribute('aria-label', 'Abrir calendario');
    boton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>';

    // --- Envoltorio: [ dd/mm/aaaa | 📅 ] ---
    const envoltorio = document.createElement('span');
    envoltorio.className = 'fecha-campo';
    original.parentNode.insertBefore(envoltorio, original);
    envoltorio.append(visible, boton, original);

    // El original pasa a oculto (sin "required": de eso se encarga el visible)
    original.required = false;
    original.type = 'hidden';

    // value envuelto: al cambiar el oculto por código, se actualiza el visible
    Object.defineProperty(original, 'value', {
      configurable: true,
      get: function () { return valueOriginal.get.call(original); },
      set: function (v) {
        valueOriginal.set.call(original, v);
        visible.value = isoATexto(v);
        visible.setCustomValidity('');
      },
    });
    visible.value = isoATexto(original.value);

    // Revisa lo escrito: formato, fecha real, mínimo y máximo
    function validar() {
      const texto = visible.value.trim();
      if (!texto) {
        visible.setCustomValidity('');
        if (valueOriginal.get.call(original) !== '') {
          valueOriginal.set.call(original, '');
          original.dispatchEvent(new Event('change', { bubbles: true }));
        }
        return true;
      }
      const iso = textoAIso(texto);
      let problema = '';
      if (!iso) problema = 'Fecha no válida. Escríbela como dd/mm/aaaa, ej: 05/03/2027';
      else if (original.min && iso < original.min) problema = 'La fecha no puede ser antes del ' + isoATexto(original.min);
      else if (original.max && iso > original.max) problema = 'La fecha no puede ser después del ' + isoATexto(original.max);
      visible.setCustomValidity(problema);   // el navegador no deja enviar con problema
      if (problema) return false;
      if (valueOriginal.get.call(original) !== iso) {
        valueOriginal.set.call(original, iso);
        // Avisamos a quien esté pendiente del campo original (otros JS)
        original.dispatchEvent(new Event('input', { bubbles: true }));
        original.dispatchEvent(new Event('change', { bubbles: true }));
      }
      return true;
    }

    // Mientras escribe: solo números y las "/" se ponen solas
    visible.addEventListener('input', function (e) {
      if (e.inputType && e.inputType.indexOf('delete') === 0) { validar(); return; }
      let cifras = visible.value.replace(/\D/g, '').slice(0, 8);
      let t = cifras;
      if (cifras.length > 4) t = cifras.slice(0, 2) + '/' + cifras.slice(2, 4) + '/' + cifras.slice(4);
      else if (cifras.length > 2) t = cifras.slice(0, 2) + '/' + cifras.slice(2);
      visible.value = t;
      validar();
    });
    // Al salir del campo: si escribió el año con 2 cifras (05/03/27) → 2027
    visible.addEventListener('blur', function () {
      const m = /^(\d{1,2})\/(\d{1,2})\/(\d{2})$/.exec(visible.value.trim());
      if (m) visible.value = dosCifras(+m[1]) + '/' + dosCifras(+m[2]) + '/20' + m[3];
      if (!validar()) visible.reportValidity();   // muestra el globito con el problema
    });

    boton.addEventListener('click', function () {
      if (visible.disabled) return;
      abrirCalendario(original, visible, boton);
    });
  }

  // --- Calendario emergente (uno solo para toda la página) -------------
  let calendario = null;    // el <div> del calendario
  let calDestino = null;    // { original, visible } que se está editando
  let calMes = null;        // Date con el primer día del mes que se ve

  function cerrarCalendario() {
    if (calendario) calendario.hidden = true;
    calDestino = null;
  }

  function abrirCalendario(original, visible, boton) {
    if (!calendario) {
      calendario = document.createElement('div');
      calendario.className = 'calendario';
      calendario.setAttribute('role', 'dialog');
      calendario.setAttribute('aria-label', 'Calendario');
      document.body.appendChild(calendario);
      // Clic fuera del calendario → se cierra
      document.addEventListener('mousedown', function (e) {
        if (calendario.hidden) return;
        if (!calendario.contains(e.target) && !e.target.closest('.fecha-boton')) cerrarCalendario();
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !calendario.hidden) { e.stopPropagation(); cerrarCalendario(); }
      }, true);
    }
    if (calDestino && calDestino.original === original && !calendario.hidden) {
      cerrarCalendario();          // segundo toque en el botón: cerrar
      return;
    }
    calDestino = { original: original, visible: visible };
    const actual = original.value || hoyIso();
    calMes = new Date(+actual.slice(0, 4), +actual.slice(5, 7) - 1, 1);
    pintarCalendario();
    calendario.hidden = false;

    // Ubicarlo debajo del campo (o encima si no cabe abajo)
    const r = visible.getBoundingClientRect();
    const ancho = calendario.offsetWidth, alto = calendario.offsetHeight;
    let izq = r.left + window.scrollX;
    // Ancho real de la pantalla visible (en el celular la página puede ser más ancha)
    const anchoPantalla = Math.min(window.innerWidth, document.documentElement.clientWidth);
    izq = Math.max(window.scrollX + 8, Math.min(izq, window.scrollX + anchoPantalla - ancho - 8));
    let arriba = r.bottom + window.scrollY + 4;
    if (r.bottom + alto + 8 > window.innerHeight && r.top - alto - 4 > 0) arriba = r.top + window.scrollY - alto - 4;
    calendario.style.left = izq + 'px';
    calendario.style.top = arriba + 'px';
  }

  function pintarCalendario() {
    const o = calDestino.original;
    const elegido = o.value;
    const hoy = hoyIso();
    const anio = calMes.getFullYear(), mes = calMes.getMonth();

    let h = '<div class="cal-cabeza">' +
      '<button type="button" data-mover="-12" aria-label="Año anterior">«</button>' +
      '<button type="button" data-mover="-1" aria-label="Mes anterior">‹</button>' +
      '<strong>' + MESES[mes] + ' ' + anio + '</strong>' +
      '<button type="button" data-mover="1" aria-label="Mes siguiente">›</button>' +
      '<button type="button" data-mover="12" aria-label="Año siguiente">»</button></div>';
    h += '<div class="cal-dias">' + DIAS.map(function (d) { return '<span>' + d + '</span>'; }).join('');

    // Espacios vacíos antes del día 1 (getDay: 0=domingo → lo pasamos a lunes=0)
    const vacios = (new Date(anio, mes, 1).getDay() + 6) % 7;
    for (let i = 0; i < vacios; i++) h += '<span></span>';
    const diasDelMes = new Date(anio, mes + 1, 0).getDate();
    for (let d = 1; d <= diasDelMes; d++) {
      const iso = anio + '-' + dosCifras(mes + 1) + '-' + dosCifras(d);
      const fuera = (o.min && iso < o.min) || (o.max && iso > o.max);
      const clases = [iso === elegido ? 'elegido' : '', iso === hoy ? 'hoy' : ''].join(' ').trim();
      h += '<button type="button" data-dia="' + iso + '" class="' + clases + '"' +
           (fuera ? ' disabled' : '') + '>' + d + '</button>';
    }
    h += '</div><div class="cal-pie">' +
      '<button type="button" data-accion="borrar">Borrar</button>' +
      '<button type="button" data-accion="hoy">Hoy</button></div>';
    calendario.innerHTML = h;

    calendario.querySelectorAll('[data-mover]').forEach(function (b) {
      b.addEventListener('click', function () {
        calMes = new Date(calMes.getFullYear(), calMes.getMonth() + (+b.dataset.mover), 1);
        pintarCalendario();
      });
    });
    calendario.querySelectorAll('[data-dia]').forEach(function (b) {
      b.addEventListener('click', function () { elegirDia(b.dataset.dia); });
    });
    calendario.querySelector('[data-accion="hoy"]').addEventListener('click', function () { elegirDia(hoy); });
    calendario.querySelector('[data-accion="borrar"]').addEventListener('click', function () { elegirDia(''); });
  }

  function elegirDia(iso) {
    const d = calDestino;
    d.visible.value = isoATexto(iso);
    d.visible.dispatchEvent(new Event('input'));   // valida y copia al oculto
    cerrarCalendario();
    d.visible.focus();
  }

  // Mejora todas las fechas que haya dentro de "raiz"
  function mejorarFechas(raiz) {
    if (!raiz.querySelectorAll) return;
    if (raiz.matches && raiz.matches('input[type="date"]')) mejorarFecha(raiz);
    raiz.querySelectorAll('input[type="date"]').forEach(mejorarFecha);
  }
  window.mejorarFechas = mejorarFechas;


  /* ===================================================================
     ARRANQUE: cuando la página terminó de cargar
     =================================================================== */
  function arrancar() {
    // Mensajes que mandó el servidor (flash) → se vuelven toasts
    document.querySelectorAll('.toasts .toast').forEach(activarToast);
    // Fechas que ya están en la página
    mejorarFechas(document.body);
    // Fechas que aparezcan después (ej: filas nuevas en Recepciones).
    // MutationObserver = "vigilante" que avisa cuando se agrega HTML.
    new MutationObserver(function (cambios) {
      cambios.forEach(function (c) { c.addedNodes.forEach(mejorarFechas); });
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
  else arrancar();
})();
