/* Token detail page: live status, grace countdown, toasts */
(function () {
  const body = document.body;
  const tokenId = parseInt(location.pathname.split("/")[2], 10);
  if (!tokenId) return;

  const graceEl = document.querySelector("[data-grace]");
  let timerId = null;
  function tickGrace() {
    if (!graceEl) return;
    const end = new Date(graceEl.dataset.grace).getTime();
    const left = Math.floor((end - Date.now()) / 1000);
    if (left <= 0) {
      clearInterval(timerId);
      return;
    }
    const m = String(Math.floor(left / 60)).padStart(2, "0");
    const s = String(left % 60).padStart(2, "0");
    graceEl.textContent = `${m}:${s}`;
  }
  if (graceEl) { tickGrace(); timerId = setInterval(tickGrace, 1000); }

  /* ---- Live Location Tracking (user-controlled) ---- */
  const toggle = document.getElementById("track-toggle");
  const panel = document.getElementById("tracking-panel");
  const locId = document.body.dataset.locationId;
  let pollId = null;

  function paintTraffic(t) {
    if (!t || !panel) return;
    panel.querySelector(".bar-fill").style.width = `${t.load_pct}%`;
    panel.querySelector(".bar-fill").className = `bar-fill ${t.traffic_key}`;
    const lvl = panel.querySelector("[data-t-level]");
    lvl.textContent = t.traffic_label;
    lvl.className = `traffic-badge ${t.traffic_key}`;
    panel.querySelector("[data-t-waiting]").textContent = t.waiting;
    panel.querySelector("[data-t-serving]").textContent = t.serving;
    panel.querySelector("[data-t-now]").textContent = t.now_serving || "—";
    panel.querySelector("[data-t-est]").textContent = `${t.est_wait_minutes} min`;
  }

  function pullTraffic() {
    fetch("/api/traffic").then(r => r.json()).then(({ traffic }) => {
      traffic.forEach((t) => { if (String(t.location_id) === String(locId)) paintTraffic(t); });
    }).catch(() => {});
  }

  if (toggle && panel && locId) {
    toggle.addEventListener("click", () => {
      const turningOn = toggle.textContent.includes("ON");
      if (turningOn) {
        panel.classList.remove("hidden");
        toggle.textContent = "Turn OFF tracking";
        toggle.classList.add("ok");
        pullTraffic();
        pollId = setInterval(pullTraffic, 4000);
        subscribe([`location:${locId}`], { token_update: () => setTimeout(pullTraffic, 200) });
      } else {
        panel.classList.add("hidden");
        toggle.textContent = "Turn ON tracking";
        toggle.classList.remove("ok");
        if (pollId) clearInterval(pollId);
      }
    });
  }

  subscribe([`token:${tokenId}`], {
    token_update: (msg) => {
      toast(`<b>${msg.token.code}</b> is now ${msg.token.status}`);
      setTimeout(() => location.reload(), 1200);
    },
    notification: (msg) => {
      if (msg.notification && msg.notification.user_id == body.dataset.userId) {
        toast(`<b>${msg.notification.type}</b> — ${msg.notification.message}`);
      }
    },
  });
})();
