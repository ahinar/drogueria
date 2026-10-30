// =====================================================================
// REPORTE DE TEMPERATURAS: gráfico y filtros — reportes/temperaturas.html
// Versión 1.1.15: antes estaba escrito dentro de la página; ahora tiene su archivo.
// =====================================================================
(function () {
  const canvas = document.getElementById('grafico-temp');
  if (!canvas) return;

  const datos = JSON.parse(document.getElementById('datos-temp').textContent);
  if (!datos.length) {
    canvas.parentElement.innerHTML = '<p class="suave" style="text-align:center;padding:2rem">Sin datos para graficar.</p>';
    return;
  }

  // Etiquetas del eje X (fechas como texto)
  const etiquetas = datos.map(d => d.fecha);

  // Agrupar por zona
  const zonasSet = {};
  datos.forEach((d) => {
    if (!zonasSet[d.zona]) zonasSet[d.zona] = { valores: [], colores: [] };
    zonasSet[d.zona].valores.push(d.temperatura);
    zonasSet[d.zona].colores.push(d.en_rango ? null : '#b3261e');
  });

  const paleta = ['#0a6ebd', '#2e8b57', '#c9812c', '#8a2d8a', '#b3261e'];

  const datasets = Object.keys(zonasSet).map((zona, i) => {
    const color = paleta[i % paleta.length];
    return {
      label: zona,
      data: zonasSet[zona].valores,
      borderColor: color,
      backgroundColor: color + '33',
      tension: 0.25,
      pointRadius: 4,
      pointBackgroundColor: zonasSet[zona].colores.map(c => c || color),
      pointBorderColor: zonasSet[zona].colores.map(c => c || color),
      pointBorderWidth: 2,
    };
  });

  new Chart(canvas, {
    type: 'line',
    data: { labels: etiquetas, datasets: datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          title: { display: true, text: 'Registros' },
          ticks: { maxRotation: 60, minRotation: 0, autoSkip: true, maxTicksLimit: 15 },
        },
        y: {
          title: { display: true, text: 'Temperatura (°C)' },
        },
      },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            title: (items) => etiquetas[items[0].dataIndex],
            afterLabel: (ctx) => {
              const original = datos[ctx.dataIndex];
              return original && !original.en_rango ? '⚠ Fuera de rango' : '';
            },
          },
        },
      },
    },
  });
})();
