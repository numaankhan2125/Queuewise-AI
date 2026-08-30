/* Shared helpers: WebSocket topic subscription + toast notifications */
function qs(sel) { return document.querySelector(sel); }

function toast(html, ms = 6000) {
  const stack = document.getElementById("toast-stack");
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = html;
  stack.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function subscribe(topics, handlers) {
  topics.forEach((topic) => {
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const sock = new WebSocket(`${proto}${location.host}/ws?topic=${encodeURIComponent(topic)}`);
    sock.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        (handlers[msg.type] || handlers["*"] || (() => {}))(msg);
      } catch (e) { /* ignore malformed */ }
    };
  });
}

function fmtAgo(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}
