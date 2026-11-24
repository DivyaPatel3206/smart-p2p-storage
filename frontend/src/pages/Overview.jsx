import { useEffect, useState } from "react";
import { ago, fmtBytes, shortAddr } from "../api";
import { Bars, Donut, Icon, Meter, Stat } from "../components/ui";

// Overview: the "home" screen. Layout mirrors the reference dashboard:
// stat row, a table card + donut card, then a bar chart + gradient card + feed.
export default function Overview({ api, onOpenFile, tick }) {
  const [s, setS] = useState(null);
  const [net, setNet] = useState(null);
  const [health, setHealth] = useState(null);
  const [files, setFiles] = useState([]);
  const [tel, setTel] = useState([]);
  const [events, setEvents] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([api.stats(), api.summary(), api.health(), api.files(), api.telemetry(), api.events()])
      .then(([a, b, c, d, e, f]) => {
        if (!live) return;
        setS(a); setNet(b); setHealth(c); setFiles(d); setTel(e); setEvents(f); setErr("");
      })
      .catch((e) => live && setErr(`Cannot reach ${api.base} — is the node running? (${e.message})`));
    return () => { live = false; };
  }, [api, tick]);

  if (err) return <div className="err">{err}</div>;
  if (!s || !net) return <div className="empty">loading…</div>;

  const saving = net.dedup_saving || 0;
  const fileDupShare = net.uploads ? net.file_level_duplicates / net.uploads : 0;

  return (
    <>
      <div className="grid g-4">
        <Stat icon="files" label="Files in network" value={net.distinct_files}
          foot={`${net.uploads} uploads · ${net.file_level_duplicates} were exact duplicates`} />
        <Stat icon="chunk" tone="amber" label="Chunks on this node" value={s.local.chunks}
          foot={`${fmtBytes(s.local.chunk_bytes)} in the blockstore`} />
        <Stat icon="copy" tone="green" label="Space saved by dedup" value={`${(saving * 100).toFixed(1)}%`}
          foot={`${fmtBytes(net.logical_bytes)} uploaded → ${fmtBytes(net.unique_bytes)} unique`} />
        <Stat icon="peers" tone={s.network.alive_nodes >= 3 ? "" : "red"} label="Nodes alive"
          value={s.network.alive_nodes} foot={`k = ${s.node.replication_k} replicas per chunk`} />
      </div>

      <div className="grid g-main mt">
        <div className="card">
          <h3>Recent files <span className="muted">· click a row for chunk map & AI result</span></h3>
          {files.length === 0 ? <div className="empty">No files yet — upload one from the Upload tab.</div> : (
            <table>
              <thead><tr><th>Name</th><th>Size</th><th>Chunks</th><th>Origin</th><th>AI</th><th>Uploaded</th></tr></thead>
              <tbody>
                {files.slice(0, 7).map((f) => (
                  <tr key={f.file_id} className="click" onClick={() => onOpenFile(f.file_id)}>
                    <td><b>{f.name}</b>{f.dhash && <span className="badge blue" style={{ marginLeft: 6 }}>image</span>}</td>
                    <td>{fmtBytes(f.size)}</td>
                    <td><div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {f.chunks}<Meter value={Math.min(1, f.chunks / 80)} /></div></td>
                    <td className="mono">{shortAddr(f.origin)}</td>
                    <td>{f.ai?.status === "done" ? <span className="badge green">{f.ai.kind}</span>
                      : <span className="badge">{f.ai?.status || "–"}</span>}</td>
                    <td className="muted">{ago(f.uploaded_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3>Replication health <span className="muted">· chunks stored here</span></h3>
          <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
            <Donut center={health?.total ?? 0} caption="chunks" segments={[
              { value: health?.healthy || 0, color: "#2f6bff" },
              { value: health?.under_replicated || 0, color: "#f5a524" },
              { value: health?.total ? 0 : 1, color: "#eef2f8" },
            ]} />
            <div className="legend">
              <div><i style={{ background: "#2f6bff" }} /> ≥ k live copies <b>{health?.healthy}</b></div>
              <div><i style={{ background: "#f5a524" }} /> under-replicated <b>{health?.under_replicated}</b></div>
              <div className="muted" style={{ maxWidth: 170 }}>
                Heartbeats every 3 s; a peer silent for 10 s is dead and its chunks are re-copied.
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid g-3 mt">
        <div className="card">
          <h3>Block-stat latency <span className="muted">· local read + hash (Paper 1 probe)</span></h3>
          <Bars values={tel.slice(-40).map((t) => t.ms)} labelFn={(v) => `${v.toFixed(2)} ms`} />
          <div className="muted" style={{ marginTop: 8 }}>
            P50 {s.telemetry.block_stat_p50_ms?.toFixed(3) ?? "–"} ms · P90 {s.telemetry.block_stat_p90_ms?.toFixed(3) ?? "–"} ms
            · {s.telemetry.probes} probes
          </div>
        </div>

        <div className="card feature">
          <h3><Icon name="copy" size={16} /> Deduplication rate</h3>
          <div className="split">
            <div>
              <div className="big">{(saving * 100).toFixed(0)}%</div>
              <div className="muted">bytes never stored twice</div>
              <div className="meter"><span style={{ width: `${saving * 100}%` }} /></div>
            </div>
            <div>
              <div className="big">{(fileDupShare * 100).toFixed(0)}%</div>
              <div className="muted">uploads that were whole-file copies</div>
              <div className="meter"><span style={{ width: `${fileDupShare * 100}%` }} /></div>
            </div>
          </div>
          <div className="muted" style={{ marginTop: 14 }}>
            Chunker: {s.node.chunker.algorithm.toUpperCase()} µ={s.node.chunker.target} B
            {s.node.chunker.horizon ? ` (h = ${s.node.chunker.horizon})` : ""} · replicas observed ×{net.replication_factor_observed}
          </div>
        </div>

        <div className="card">
          <h3>Activity</h3>
          <ul className="events">
            {events.slice(0, 9).map((e, i) => (
              <li key={i}><span className="when">{ago(e.ts)}</span><span><b>{e.kind}</b> {e.message}</span></li>
            ))}
            {!events.length && <li className="empty">quiet so far</li>}
          </ul>
        </div>
      </div>
    </>
  );
}
