/* Staff workspace: live queue + now-serving updates */
(function () {
  const cid = document.body.dataset.counterId;
  const lid = document.body.dataset.locationId;
  if (!cid) return;
  subscribe([`counter:${cid}`, lid ? `display:${lid}` : "", "cqdcc"].filter(Boolean), {
    token_update: (msg) => {
      toast(`<b>${msg.token.code}</b> ${msg.event}`);
      setTimeout(() => location.reload(), 900);
    },
    notification: (msg) => {
      if (msg.notification && msg.notification.type === "supervisor") return;
    },
  });
})();
