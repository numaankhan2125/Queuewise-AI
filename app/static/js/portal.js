/* Student portal: refresh queue cards from /api/queues/live */
(function () {
  function refresh() {
    fetch("/api/queues/live").then(r => r.json()).then(({ queues }) => {
      queues.forEach((q) => {
        const card = document.querySelector(`[data-location-card="${q.location_id}"]`);
        if (!card) return;
        card.querySelector("[data-waiting]").textContent = q.waiting;
        card.querySelector("[data-now-serving]").textContent = q.now_serving || "-";
      });
    }).catch(() => {});
  }
  setInterval(refresh, 5000);
})();

subscribe(["cqdcc"], {
  notification: (msg) => {
    if (msg.notification && msg.notification.user_id == document.body.dataset.userId) {
      toast(`<b>${msg.notification.type}</b> — ${msg.notification.message}`);
    }
  },
});
