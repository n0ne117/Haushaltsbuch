"use strict";

(function () {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const eur = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
  const eurAxis = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
  const data = (id) => JSON.parse(document.getElementById(id).textContent);
  const go = (links) => (_event, elements) => {
    if (elements.length) location.href = links[elements[0].index];
  };

  function donut(canvas) {
    const d = data(canvas.dataset.source);
    new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: d.labels,
        datasets: [{ data: d.values, backgroundColor: d.colors, borderColor: css("--surface"), borderWidth: 2 }],
      },
      options: {
        cutout: "66%",
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => " " + eur.format(c.raw / 100) } },
        },
        onClick: go(d.links),
      },
    });
  }

  function bars(canvas) {
    const d = data(canvas.dataset.source);
    const series = (label, values, color) => ({
      label, data: values.map((v) => v / 100), backgroundColor: color, borderRadius: 3,
    });
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: d.labels,
        datasets: [
          series("Einnahmen", d.einnahmen, css("--income")),
          series("Ausgaben", d.ausgaben, css("--expense")),
          series("Gespart", d.gespart, css("--saved")),
        ],
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { grid: { display: false }, ticks: { color: css("--muted"), maxRotation: 0, autoSkip: false, font: { size: 10 } } },
          y: { grid: { color: css("--border") }, ticks: { color: css("--muted"), callback: (v) => eurAxis.format(v) } },
        },
        plugins: {
          legend: { labels: { color: css("--text"), boxWidth: 12, boxHeight: 12 } },
          tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${eur.format(c.raw)}` } },
        },
        onClick: go(d.links),
      },
    });
  }

  if (window.Chart) {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    document.querySelectorAll('canvas[data-chart="donut"]').forEach(donut);
    document.querySelectorAll('canvas[data-chart="bars"]').forEach(bars);
  }

  // Horizontal swipe switches to the previous/next period.
  const nav = document.querySelector("[data-swipe-prev]");
  if (!nav) return;
  let start = null;
  document.addEventListener("touchstart", (e) => {
    const t = e.touches[0];
    start = e.target.closest(".chips, .table-scroll, canvas") ? null : { x: t.clientX, y: t.clientY };
  }, { passive: true });
  document.addEventListener("touchend", (e) => {
    if (!start) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;
    start = null;
    if (Math.abs(dx) > 70 && Math.abs(dy) < 50) {
      location.href = dx < 0 ? nav.dataset.swipeNext : nav.dataset.swipePrev;
    }
  }, { passive: true });
})();
