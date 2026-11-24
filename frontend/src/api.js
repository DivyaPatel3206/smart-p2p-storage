// Tiny API client. Every node exposes the same /api/* routes, so switching node
// = switching the base URL. The dashboard never talks to a central server.

// Node list: set VITE_NODES="https://node1.onrender.com,..." when deploying.
// Only ONE node is really needed - the others are discovered from its routing table.
// One-service cloud mode (scripts/cloud_start.py): nodes are reached through /n/1, /n/2, /n/3
export const CLUSTER = import.meta.env.VITE_CLUSTER === "1";
const fromEnv = (import.meta.env.VITE_NODES || "").split(",").map((s) => s.trim().replace(/\/$/, "")).filter(Boolean);
export const DEFAULT_NODES = CLUSTER ? ["/n/1", "/n/2", "/n/3"] : fromEnv.length ? fromEnv
  : ["http://127.0.0.1:5001", "http://127.0.0.1:5002", "http://127.0.0.1:5003"];

// failure simulation in one-service mode
export const cluster = {
  status: () => fetch("/cluster/status").then((r) => r.json()),
  stop: (i) => fetch(`/cluster/stop/${i}`, { method: "POST" }).then((r) => r.json()),
  start: (i) => fetch(`/cluster/start/${i}`, { method: "POST" }).then((r) => r.json()),
};

// "https://p2p-node1-ab12.onrender.com" -> "p2p-node1-ab12" ; "http://127.0.0.1:5001" -> "127.0.0.1:5001"
export const shortAddr = (url) => {
  if (!url) return "–";
  if (/^\/n\/\d+$/.test(url)) return `node${url.split("/")[2]}`;
  const local = url.match(/^http:\/\/127\.0\.0\.1:500(\d)$/);
  if (CLUSTER && local) return `node${local[1]}`;
  const h = url.replace(/^https?:\/\//, "");
  return h.endsWith(".onrender.com") ? h.replace(".onrender.com", "") : h;
};

export function makeApi(base) {
  const get = async (path) => {
    const r = await fetch(base + path);
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  };
  return {
    base,
    stats: () => get("/api/stats"),
    peers: () => get("/api/peers"),
    files: () => get("/api/files"),
    file: (id) => get(`/api/files/${id}`),
    health: () => get("/api/health"),
    telemetry: () => get("/api/telemetry"),
    events: () => get("/api/events"),
    summary: () => get("/api/network_summary"),
    neardup: (id) => get(`/api/neardup/${id}`),
    object: (uid) => get(`/api/objects/${encodeURIComponent(uid)}`),
    whereis: (key) => get(`/api/dht/whereis/${encodeURIComponent(key)}`),
    evals: () => get("/api/eval"),
    downloadUrl: (id) => `${base}/api/download/${id}`,
    upload: async (file, objectUid) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("object_uid", objectUid || "");
      const r = await fetch(base + "/api/upload", { method: "POST", body: fd });
      if (!r.ok) throw new Error(`upload failed (${r.status})`);
      return r.json();
    },
  };
}

export const fmtBytes = (n) => {
  if (n == null) return "–";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i ? 1 : 0)} ${u[i]}`;
};

export const short = (h, n = 10) => (h ? `${h.slice(0, n)}…` : "–");

export const ago = (ts) => {
  if (!ts) return "–";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
};
