import { useEffect, useMemo, useState } from "react";
import { CLUSTER, DEFAULT_NODES, makeApi, shortAddr } from "./api";
import { Icon } from "./components/ui";
import Evaluation from "./pages/Evaluation";
import Files from "./pages/Files";
import Network from "./pages/Network";
import Overview from "./pages/Overview";
import Upload from "./pages/Upload";

const PAGES = [
  ["overview", "home", "Overview"],
  ["upload", "upload", "Upload"],
  ["files", "files", "Files"],
  ["network", "network", "Network"],
  ["eval", "chart", "Evaluation"],
];

const greeting = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
};

export default function App() {
  // ?node=http://127.0.0.1:5002 lets you open one browser tab per node
  const initial = new URLSearchParams(window.location.search).get("node") || DEFAULT_NODES[0];
  const [node, setNode] = useState(initial);
  const [page, setPage] = useState("overview");
  const [selected, setSelected] = useState(null);
  const [tick, setTick] = useState(0);
  const [info, setInfo] = useState(null);
  const [online, setOnline] = useState(null);
  const [known, setKnown] = useState(DEFAULT_NODES);   // grows with peers discovered from the DHT
  const api = useMemo(() => makeApi(node.replace(/\/$/, "")), [node]);

  // refresh every 4 s so heartbeats / repairs show up live
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 4000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    api.stats().then((s) => { setInfo(s.node); setOnline(true); }).catch(() => setOnline(false));
    if (!CLUSTER) api.peers().then((p) => setKnown((k) => {
      const all = [...k];
      [p.self.address, ...p.peers.map((x) => x.address)].forEach((a) => { if (a && !all.includes(a)) all.push(a); });
      return all.length === k.length ? k : all;
    })).catch(() => {});
  }, [api, tick]);

  const openFile = (id) => { setSelected(id); setPage("files"); };
  const title = PAGES.find((p) => p[0] === page)[2];

  return (
    <div className="stage">
      <div className="window">
        <nav className="rail">
          <div className="logo">P2</div>
          {PAGES.map(([key, icon, label]) => (
            <button key={key} className={page === key ? "active" : ""} onClick={() => setPage(key)} aria-label={label}>
              <Icon name={icon} size={20} /><span className="tip">{label}</span>
            </button>
          ))}
          <div className="spacer" />
          <button aria-label="Security"><Icon name="shield" size={20} /><span className="tip">Private swarm key on</span></button>
        </nav>

        <main className="main">
          <div className="topbar">
            <div>
              <h1>{page === "overview" ? `${greeting()}, ${info?.name ?? "node"}` : title}</h1>
              <div className="sub">
                Smart P2P Storage · AI duplicate detection & summarisation
                {info && <> · {info.zone} · AI backend: <b>{info.ai_backend}</b></>}
              </div>
            </div>
            <div className="grow" />
            <div className="search">
              <Icon name="search" size={15} />
              <input placeholder="Jump to file id…" onKeyDown={(e) => {
                if (e.key === "Enter" && e.target.value.trim()) openFile(e.target.value.trim());
              }} />
            </div>
            <div className="node-pick">
              <span className={`dot ${online ? "ok" : online === false ? "bad" : ""}`} />
              <select value={known.includes(node) ? node : "custom"}
                onChange={(e) => setNode(e.target.value === "custom" ? "https://" : e.target.value)}>
                {known.map((n) => <option key={n} value={n}>{shortAddr(n)}</option>)}
                <option value="custom">custom…</option>
              </select>
              {!known.includes(node) && (
                <input style={{ width: 230 }} value={node} placeholder="https://your-node.onrender.com"
                  onChange={(e) => setNode(e.target.value.trim())} />
              )}
            </div>
          </div>

          {online === false && (
            <div className="err" style={{ marginBottom: 16 }}>
              {node} is not answering. Start the nodes with <span className="mono">python scripts/run_nodes.py</span> or pick another node.
            </div>
          )}

          {page === "overview" && <Overview api={api} onOpenFile={openFile} tick={tick} />}
          {page === "upload" && <Upload api={api} onOpenFile={openFile} />}
          {page === "files" && <Files api={api} selected={selected} onSelect={setSelected} tick={tick} />}
          {page === "network" && <Network api={api} tick={tick} />}
          {page === "eval" && <Evaluation api={api} />}
        </main>
      </div>
    </div>
  );
}
