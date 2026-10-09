// Alarma de temperaturas: consulta el endpoint cada 30 s y dispara sonido + pantalla roja.
(function () {
  const contenedor = document.getElementById('alarma-temp');
  if (!contenedor) return;

  const lista = document.getElementById('alarma-lista');
  const btnSilenciar = document.getElementById('alarma-silenciar');
  const btnCerrar = document.getElementById('alarma-cerrar');
  const INTERVALO = 30 * 1000;              // consultar cada 30 s
  const DURACION_APLAZO = 10 * 60 * 1000;   // 10 minutos
  const DURACION_SILENCIO = 10 * 60 * 1000; // 10 minutos

  // En la pantalla de registrar la lectura NO mostramos la alarma: taparía el formulario
  // justo cuando la persona está haciendo lo que la alarma le pide.
  const enPantallaDeRegistro = window.location.pathname.indexOf('/temperaturas/registrar/') === 0;

  // El "aplazar" y el "silenciar" se guardan en el navegador (localStorage) para que
  // sigan valiendo al cambiar de pantalla. Antes se perdían en cada página nueva y la
  // alarma volvía a aparecer de inmediato.
  const CLAVE_APLAZO = 'alarmaTemp.aplazadoHasta';
  const CLAVE_SILENCIO = 'alarmaTemp.silenciadoHasta';
  function leerTiempo(clave) {
    try { return parseInt(window.localStorage.getItem(clave), 10) || 0; } catch (e) { return 0; }
  }
  function guardarTiempo(clave, valor) {
    try { window.localStorage.setItem(clave, String(valor)); } catch (e) { /* sin almacenamiento */ }
  }

  let audioCtx = null;
  let sonando = false;
  let intervaloBeep = null;
  let aplazadoHasta = leerTiempo(CLAVE_APLAZO);
  let silenciadoHasta = leerTiempo(CLAVE_SILENCIO);
  let suspendido = false; // true cuando el usuario está saliendo a registrar

  // ===== Sonido suave =====
  function beep() {
    if (!audioCtx) {
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      } catch (e) { return; }
    }
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 660;
    gain.gain.value = 0.08;
    osc.connect(gain).connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.15);
  }

  function iniciarSonido() {
    if (sonando) return;
    sonando = true;
    beep();
    intervaloBeep = setInterval(beep, 3000);
  }

  function detenerSonido() {
    sonando = false;
    if (intervaloBeep) { clearInterval(intervaloBeep); intervaloBeep = null; }
  }

  function ocultar() {
    contenedor.classList.add('alarma-oculta');
    detenerSonido();
  }

  // ===== Mostrar pantalla roja =====
  function mostrar(pendientes) {
    if (!pendientes.length) return;

    lista.innerHTML = '';
    pendientes.forEach(function (p) {
      const li = document.createElement('li');
      li.textContent = p.zona + ' — lectura programada para las ' + p.hora;

      const a = document.createElement('a');
      a.href = '/temperaturas/registrar/' + p.zona_id + '?programada_para=' + encodeURIComponent(p.programada_para);
      a.textContent = ' Registrar ahora';
      a.style.marginLeft = '.5rem';

      // Al hacer clic: silenciar, ocultar y suspender la alarma antes de navegar
      a.addEventListener('click', function (e) {
        e.preventDefault();
        suspendido = true;
        detenerSonido();
        ocultar();
        // Pequeña pausa para que se vea que se cerró, y luego navega
        setTimeout(function () {
          window.location.href = a.href;
        }, 100);
      });

      li.appendChild(a);
      lista.appendChild(li);
    });

    contenedor.classList.remove('alarma-oculta');
    if (Date.now() >= silenciadoHasta) iniciarSonido();

    if (window.Notification && Notification.permission === 'granted') {
      new Notification('Droguería — temperatura pendiente', {
        body: pendientes.map(function (p) { return p.zona + ' a las ' + p.hora; }).join('\n'),
      });
    }
  }

  // ===== Consultar pendientes =====
  function consultar() {
    // En la pantalla de registro no se muestra la alarma.
    if (enPantallaDeRegistro) { ocultar(); return; }
    // Si el usuario aplazó o está saliendo a registrar, no consultar nada
    if (suspendido) return;
    aplazadoHasta = leerTiempo(CLAVE_APLAZO);       // por si se aplazó desde otra pestaña
    silenciadoHasta = leerTiempo(CLAVE_SILENCIO);
    if (Date.now() < aplazadoHasta) { ocultar(); return; }

    fetch('/temperaturas/api/pendientes', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { pendientes: [] }; })
      .then(function (data) {
        if (suspendido) return;
        const pendientes = (data && data.pendientes) || [];
        if (!pendientes.length) {
          ocultar();
          return;
        }
        mostrar(pendientes);
      })
      .catch(function () { /* silencio */ });
  }

  // ===== Botones =====
  if (btnSilenciar) {
    btnSilenciar.addEventListener('click', function () {
      detenerSonido();
      silenciadoHasta = Date.now() + DURACION_SILENCIO;
      guardarTiempo(CLAVE_SILENCIO, silenciadoHasta);
      btnSilenciar.textContent = '🔇 Sonido silenciado 10 min';
      setTimeout(function () {
        btnSilenciar.textContent = '🔇 Silenciar sonido';
      }, DURACION_SILENCIO);
    });
  }

  if (btnCerrar) {
    btnCerrar.addEventListener('click', function () {
      aplazadoHasta = Date.now() + DURACION_APLAZO;
      guardarTiempo(CLAVE_APLAZO, aplazadoHasta);
      ocultar();
    });
  }

  // ===== Pedir permiso de notificaciones =====
  if (window.Notification && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  // ===== Primer chequeo y luego cada 30 s =====
  consultar();
  setInterval(consultar, INTERVALO);
})();