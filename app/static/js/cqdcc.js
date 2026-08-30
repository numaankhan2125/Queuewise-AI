/* CQ-DCC: charts + live KPI refresh over WebSocket */
(function () {
  let volumeChart, peakChart, utilChart, csatChart, missedChart;

  const palette = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#8b5cf6", "#0ea5e9"];

  async function loadCharts() {
    try {
      const res = await fetch("/admin/analytics-data");
      if (!res.ok) return;
      const d = await res.json();

      volumeChart ??= makeChart("ch-volume");
      peakChart ??= makeChart("ch-peak");
      utilChart ??= makeChart("ch-util");
      csatChart ??= makeChart("ch-csat");
      missedChart ??= makeChart("ch-missed");

      volumeChart.data.labels = d.volume_by_location.map(r => r.location);
      volumeChart.data.datasets[0].data = d.volume_by_location.map(r => r.tokens);
      volumeChart.update();

      peakChart.data.labels = d.peak_hours.map(r => r.hour);
      peakChart.data.datasets[0].data = d.peak_hours.map(r => r.tokens);
      peakChart.update();

      utilChart.data.labels = d.utilization.map(r => `${r.counter}`);
      utilChart.data.datasets[0].data = d.utilization.map(r => r.served_total);
      utilChart.update();

      csatChart.data.labels = d.satisfaction.map(r => r.date);
      csatChart.data.datasets[0].data = d.satisfaction.map(r => r.csat);
      csatChart.update();

      missedChart.data.labels = d.missed_rate.map(r => r.date);
      missedChart.data.datasets[0].data = d.missed_rate.map(r => r.rate_pct);
      missedChart.update();
    } catch (e) { /* offline */ }
  }

  function makeChart(id) {
    const ctx = document.getElementById(id);
    if (!ctx) return { data: { labels: [], datasets: [{ data: [] }] }, update() {} };
    return new Chart(ctx, {
      type: "bar",
      data: { labels: [], datasets: [{ label: id, data: [], backgroundColor: palette[0] }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });
  }

  function refreshKpis() {
    fetch("/api/cqdcc/kpis").then(r => r.json()).then((k) => {
      document.getElementById("k-tokens").textContent = k.tokens_today;
      document.getElementById("k-served").textContent = k.served_today;
      document.getElementById("k-waiting").textContent = k.waiting_now;
      document.getElementById("k-serving").textContent = k.serving_now;
      document.getElementById("k-missed").textContent = k.missed_today;
      document.getElementById("k-waitavg").innerHTML = `${k.avg_wait_minutes}<small> min</small>`;
      document.getElementById("k-csat").innerHTML = `${k.csat}<small> /5</small>`;
      document.getElementById("k-counters").textContent = k.open_counters;
    }).catch(() => {});
  }

  function prependNotif(n) {
    const feed = document.getElementById("notif-feed");
    if (!feed || !n) return;
    const tr = document.createElement("tr");
    const now = new Date().toLocaleTimeString();
    tr.innerHTML = `<td class="mono muted">${now}</td>
      <td><span class="badge ${n.type}">${n.type}</span></td>
      <td style="font-size:.82rem">${n.message}</td>`;
    feed.prepend(tr);
    while (feed.rows.length > 15) feed.deleteRow(-1);
  }

  loadCharts();
  setInterval(() => { refreshKpis(); loadCharts(); }, 15000);

  subscribe(["cqdcc"], {
    notification: (msg) => prependNotif(msg.notification),
    feedback: () => { refreshKpis(); },
    token_update: () => { refreshKpis(); },
  });
})();
