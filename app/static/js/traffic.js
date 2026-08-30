/* Campus Traffic Board: live refresh via WebSocket + polling fallback */
(function () {
  function applyRow(card, t) {
    card.querySelector("[data-level]").textContent = t.traffic_label;
    const badge = card.querySelector("[data-level]");
    badge.className = `traffic-badge ${t.traffic_key}`;
    card.querySelector("[data-waiting]").textContent = t.waiting;
    card.querySelector("[data-now-serving]").textContent = t.now_serving || "—";
    card.querySelector("[data-estwait]").textContent = `${t.est_wait_minutes} min`;
    card.querySelector("[data-suggestion]").textContent = t.suggestion;
    const fill = card.querySelector(".bar-fill");
    fill.style.width = `${t.load_pct}%`;
    fill.className = `bar-fill ${t.traffic_key}`;
  }

  function refresh() {
    fetch("/api/traffic").then(r => r.json()).then(({ traffic, updated_at }) => {
      traffic.forEach((t) => {
        const card = document.querySelector(`[data-traffic-card="${t.location_id}"]`);
        if (card) applyRow(card, t);
      });
      const up = document.getElementById("updated-at");
      if (up) up.textContent = "updated " + new Date(updated_at).toLocaleTimeString();
    }).catch(() => {});
  }

  setInterval(refresh, 4000);

  subscribe(["cqdcc"], { token_update: () => setTimeout(refresh, 300) });
})();
