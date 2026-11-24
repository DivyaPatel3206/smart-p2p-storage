import { useEffect, useState } from "react";
import { ago, fmtBytes, short } from "../api";
import { Icon } from "../components/ui";

// Files: every manifest known in the network + a detail panel for one file
// (manifest, replica map of every chunk, AI metadata, versions, near-duplicates).
export default function Files({ api, selected, onSelect, tick }) {
  const [files, setFiles] = useState([]);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.files().then((f) => { setFiles(f); setErr(""); }).catch((e) => setErr(e.message));
  }, [api, tick]);

  const shown = files.filter((f) => !q || f.name?.toLowerCase().includes(q.toLowerCase()) || f.file_id.startsWith(q));

  return (
    <div className="grid g-main">
      <div className="card">
        <h3><Icon name="files" size={16} /> Network files <span className="muted">· {files.length} manifests</span>
          <span className="right" style={{ width: 220 }}>
            <input className="field" placeholder="filter by name or id" value={q} onChange={(e) => setQ(e.target.value)} />
          </span>
        </h3>
        {err && <div className="err">{err}</div>}
        <table>
          <thead><tr><th>Name</th><th>Content ID</th><th>Size</th><th>Chunks</th><th>Object</th><th>AI</th><th>When</th></tr></thead>
          <tbody>
            {shown.map((f) => (
              <tr key={f.file_id} className="click" onClick={() => onSelect(f.file_id)}
                style={selected === f.file_id ? { background: "var(--blue-soft)" } : null}>
                <td><b>{f.name}</b></td>
                <td className="mono">{short(f.file_id, 12)}</td>
                <td>{fmtBytes(f.size)}</td>
                <td>{f.chunks}</td>
                <td>{f.object_uid ? <span className="badge blue">{f.object_uid}</span> : "–"}</td>
                <td>{f.ai?.status === "done" ? <span className="badge green">{f.ai.kind}</span> : <span className="badge">{f.ai?.status || "–"}</span>}</td>
                <td className="muted">{ago(f.uploaded_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <div className="empty">nothing here yet</div>}
      </div>
      <FileDetail api={api} id={selected} onSelect={onSelect} tick={tick} />
    </div>
  );
}

function FileDetail({ api, id, onSelect, tick }) {
  const [d, setD] = useState(null);
  const [versions, setVersions] = useState([]);
  const [near, setNear] = useState([]);

  useEffect(() => {
    if (!id) return;
    api.file(id).then((x) => {
      setD(x);
      if (x.manifest.object_uid) api.object(x.manifest.object_uid).then(setVersions);
      else setVersions([]);
      if (x.manifest.dhash) api.neardup(id).then(setNear); else setNear([]);
    }).catch(() => setD(null));
  }, [api, id, tick]);

  if (!id) return <div className="card"><div className="empty">Select a file to see its chunk map.</div></div>;
  if (!d) return <div className="card"><div className="empty">loading…</div></div>;
  const m = d.manifest;
  const k = d.replication.k;

  return (
    <div className="card">
      <h3>{m.name} <span className="right"><a className="link" href={api.downloadUrl(m.file_id)}>
        <Icon name="download" size={14} /> download</a></span></h3>
      <div className="kv">
        <div>Content ID</div><div className="mono">{short(m.file_id, 28)}</div>
        <div>SHA-256 fixity</div><div className="mono">{short(m.fixity_sha256, 28)}</div>
        <div>Size</div><div>{fmtBytes(m.size)} · {m.mime}</div>
        <div>Chunker</div><div>{m.chunker.algorithm.toUpperCase()} µ={m.chunker.target}
          {m.chunker.horizon ? ` · h=${m.chunker.horizon}` : ""}{m.encrypted ? " · convergent-encrypted" : ""}</div>
        <div>Uploaded via</div><div className="mono">{m.origin}</div>
        {m.dhash && <><div>dHash</div><div className="mono">{m.dhash}</div></>}
      </div>

      <h3 className="mt">Replica map <span className="muted">· {d.replication.healthy}/{d.replication.unique_chunks} chunks with ≥ {k} live copies</span></h3>
      <div className="chunkmap">
        {Object.entries(d.replicas).map(([h, r]) => (
          <span key={h} className={r.live.length >= k ? "" : r.live.length >= 1 ? "l1" : "l0"}
            title={`${h.slice(0, 16)}… on ${r.live.join(", ") || "no live node"}`} />
        ))}
      </div>
      <div className="muted" style={{ marginTop: 6 }}>green = k copies · amber = fewer · red = none alive (hover a square)</div>

      {d.ai && (
        <>
          <h3 className="mt"><Icon name="spark" size={16} /> AI metadata</h3>
          {d.ai.summary && <p style={{ marginTop: 0, lineHeight: 1.5 }}>{d.ai.summary}</p>}
          {d.ai.caption && <p style={{ marginTop: 0 }}>“{d.ai.caption}” {" "}
            <span className={`badge ${d.ai.reliable ? "green" : "amber"}`}>{d.ai.reliable ? "reliable" : "low reliability"}</span></p>}
          <div className="muted">{d.ai.model} · computed once by {d.ai.computed_by}</div>
        </>
      )}

      {versions.length > 1 && (
        <>
          <h3 className="mt">Versions of “{m.object_uid}”</h3>
          {versions.map((v, i) => (
            <div key={v.file_id} className="peer" style={{ cursor: "pointer" }} onClick={() => onSelect(v.file_id)}>
              <div className="avatar">v{i + 1}</div>
              <div><b>{v.name}</b><div className="muted mono">{short(v.file_id, 16)} · {fmtBytes(v.size)}</div></div>
            </div>
          ))}
        </>
      )}

      {near.length > 0 && (
        <>
          <h3 className="mt">Near-duplicates</h3>
          {near.map((n) => (
            <div key={n.file_id} className="peer" style={{ cursor: "pointer" }} onClick={() => onSelect(n.file_id)}>
              <div className="avatar b">{n.hamming}</div>
              <div><b>{n.name}</b><div className="muted">Hamming distance {n.hamming} · similarity {Math.round(n.similarity * 100)}%</div></div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
