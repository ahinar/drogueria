// =====================================================================
// GRÁFICOS DEL RESUMEN CONTABLE (flujo de caja, gastos, 12 meses) — contabilidad/index.html
// Versión 1.1.15: antes estaba escrito dentro de la página; ahora tiene su archivo.
// Los datos del servidor llegan en un bloque <script type="application/json">.
// =====================================================================
(function () {
  // Colores del tema del usuario (temas.css) y unos fijos para entradas, salidas, etc.
  const css = getComputedStyle(document.documentElement);
  const acento = css.getPropertyValue('--acento').trim() || '#0f766e';
  const VERDE = '#16a34a', ROJO = '#ef4444', AZUL = '#3b82f6';
  const PALETA = [AZUL, VERDE, '#f59e0b', '#a855f7', '#f97316', '#06b6d4', '#ec4899', '#84cc16', '#64748b'];
  const pesos = (v) => '$' + Math.round(v).toLocaleString('es-CO');
  if (!window.Chart) return;                    // sin la librería, la página sigue mostrando las tablas
  Chart.defaults.font.family = css.getPropertyValue('font-family');

  // ---- Flujo de caja: barras de entradas y salidas + línea de saldo ----
  const DATOS = JSON.parse(document.getElementById('contabilidad-datos').textContent);
  const flujo = DATOS.flujo;
  new Chart(document.getElementById('g-flujo'), {
    data: {
      labels: flujo.map((f) => f.dia),
      datasets: [
        { type: 'bar', label: 'Entradas', data: flujo.map((f) => f.entradas), backgroundColor: VERDE, borderRadius: 3 },
        { type: 'bar', label: 'Salidas', data: flujo.map((f) => f.salidas), backgroundColor: ROJO, borderRadius: 3 },
        { type: 'line', label: 'Saldo', data: flujo.map((f) => f.saldo), borderColor: AZUL, backgroundColor: AZUL,
          tension: .3, pointRadius: 2, yAxisID: 'y' },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { tooltip: { callbacks: { label: (c) => c.dataset.label + ': ' + pesos(c.parsed.y) } } },
      scales: { y: { ticks: { callback: (v) => pesos(v) } } },
    },
  });

  // ---- Distribución de gastos (dona) ----
  const gastos = DATOS.gastos;
  if (gastos.length && document.getElementById('g-gastos')) {
    new Chart(document.getElementById('g-gastos'), {
      type: 'doughnut',
      data: { labels: gastos.map((g) => g.categoria),
              datasets: [{ data: gastos.map((g) => g.total), backgroundColor: PALETA, borderWidth: 2 }] },
      options: { cutout: '68%', maintainAspectRatio: false, plugins: { legend: { display: false },
                 tooltip: { callbacks: { label: (c) => c.label + ': ' + pesos(c.parsed) } } } },
    });
    // Los puntos de la leyenda, del mismo color de cada pedazo
    document.querySelectorAll('#leyenda-gastos .punto').forEach((p) => {
      p.style.background = PALETA[+p.dataset.i % PALETA.length];
    });
  }

  // ---- Ventas vs. gastos (últimos 6 meses) ----
  const meses = DATOS.meses;
  new Chart(document.getElementById('g-meses'), {
    type: 'bar',
    data: { labels: meses.map((m) => m.mes),
            datasets: [{ label: 'Ventas', data: meses.map((m) => m.ventas), backgroundColor: VERDE, borderRadius: 4 },
                       { label: 'Gastos', data: meses.map((m) => m.gastos), backgroundColor: AZUL, borderRadius: 4 }] },
    options: { maintainAspectRatio: false,
               plugins: { tooltip: { callbacks: { label: (c) => c.dataset.label + ': ' + pesos(c.parsed.y) } } },
               scales: { y: { ticks: { callback: (v) => pesos(v) } } } },
  });
})();
