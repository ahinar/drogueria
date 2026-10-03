// Alarma de temperaturas: consulta el endpoint cada 30 s y dispara sonido + pantalla roja.
(function () {
  const contenedor = document.getElementById('alarma-temp');
  if (!contenedor) return;

  const lista = document.getElementById('alarma-lista');
  const btnSilenciar = document.getElementById('alarma-silenciar');
  const btnCerrar = document.getElementById('alarma-cerrar');
  const INTERVALO = 30 * 1000; // 30 segundos

  let audioCtx = null;
  let sonando = false;
  let intervaloBeep = null;

  // --- Sonido con Web Audio API ---
  function beep() {
    if (!audioCtx) {
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      } catch (e) {
        return; // navegador sin soporte: se ignora el sonido
      }
    }
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'square';
    osc.frequency.value = 880;
    gain.gain.value = 0.15;
    osc.connect(gain).connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.25);
  }

  function iniciarSonido() {
    if (sonando) return;
    sonando = true;
    beep();
    intervaloBeep = setInterval(beep, 800);
  }

  function detenerSonido() {
    sonando = false;
    if (intervaloBeep) {
      clearInterval(intervaloBeep);
      intervaloBeep = null;
    }
  }

  // --- Mostrar la pantalla roja ---
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
      li.appendChild(a);
      lista.appendChild(li);
    });

    contenedor.classList.remove('alarma-oculta');
    iniciarSonido();

    // Notificación nativa del navegador (si el usuario la autorizó)
    if (window.Notification && Notification.permission === 'granted') {
      new Notification('Droguería — temperatura pendiente', {
        body: pendientes.map(function (p) { return p.zona + ' a las ' + p.hora; }).join('\n'),
      });
    }
  }

  function ocultar() {
    contenedor.classList.add('alarma-oculta');
    detenerSonido();
  }

  // --- Consultar pendientes ---
  function consultar() {
    fetch('/temperaturas/api/pendientes', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { pendientes: [] }; })
      .then(function (data) {
        const pendientes = (data && data.pendientes) || [];
        if (pendientes.length) {
          mostrar(pendientes);
        } else {
          ocultar();
        }
      })
      .catch(function () { /* silencio: si falla, se reintenta en 30 s */ });
  }

  // --- Botones ---
  if (btnSilenciar) {
    btnSilenciar.addEventListener('click', function () {
      detenerSonido();
      btnSilenciar.textContent = '🔇 Silencio';
    });
  }

  if (btnCerrar) {
    btnCerrar.addEventListener('click', function () {
      ocultar();
      // Vuelve a aparecer si siguen pendientes.
      setTimeout(consultar, 5000);
    });
  }

  // --- Pedir permiso de notificaciones (una sola vez) ---
  if (window.Notification && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  // --- Primer chequeo y luego cada 30 s ---
  consultar();
  setInterval(consultar, INTERVALO);
})();