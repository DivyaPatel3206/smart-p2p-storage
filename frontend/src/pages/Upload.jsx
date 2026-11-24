import { useEffect, useRef, useState } from "react";
import { fmtBytes, short, shortAddr } from "../api";
import { DupBadge, Icon, Meter } from "../components/ui";

// Upload → shows exactly what the node did: dedup decision, chunks reused,
// near-duplicates found through the DHT and the AI result (polled until ready).
export default function Upload({ api, onOpenFile }) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uid, setUid] = useState("");
  const [res, setRes] = useState(null);
  const [ai, setAi] = useState(null);
  const [err, setErr] = useState("");
  const input = useRef();

  const send = async (file) => {
    if (!file) return;
    setBusy(true); setErr(""); setRes(null); setAi(null);
    try {
      const r = await api.upload(file, uid);
      setRes(r);
      setAi(r.ai);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  // poll the AI result (it is computed in the background on THIS node, then shared via the DHT)
  useEffect(() => {
    if (!res || (ai && ai.status === "done") || ai?.status === "disabled") return;
    const t = setInterval(async () => {
      try {
        const d = await api.file(res.file_id);
        if (d.ai) setAi(d.ai);
      } catch { /* node busy */ }
    }, 1500);
    return () => clearInterval(t);
  }, [res, ai, api]);

  const kind = res ? (res.near_duplicates?.length && res.duplicate === "none" ? "near" : res.duplicate) : null;
  const reused = res?.chunks_already_in_network ?? 0;
  const uniqueInFile = res?.chunks_unique_in_file ?? res?.chunks_total ?? 0;

  return (
    <div className="grid g-side">
      <div>
        <div className="card">
          <h3><Icon name="upload" size={16} /> Upload to <span className="mono">{shortAddr(api.base)}</span></h3>
          <div className={`drop ${over ? "over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files[0]); }}
            onClick={() => input.current.click()}>
            <Icon name="upload" size={28} />
            <p><strong>Drop a file here</strong> or click to choose</p>
            <p className="muted">Text/PDF → DistilBART summary · Images → BLIP caption + dHash near-duplicate search</p>
            <input ref={input} type="file" hidden onChange={(e) => send(e.target.files[0])} />
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 12, alignItems: "center" }}>
            <input className="field" placeholder="Optional object UID (groups versions of the same document, e.g. report-1)"
              value={uid} onChange={(e) => setUid(e.target.value)} />
          </div>
          {busy && <div className="note mt">Chunking, hashing, asking the DHT who already has each chunk…</div>}
          {err && <div className="err mt">{err}</div>}
        </div>

        {res && (
          <div className="card mt">
            <h3>Result <DupBadge kind={kind} /><span className="right muted">{res.elapsed_ms} ms</span></h3>
            <p style={{ marginTop: 0 }}>{res.message}</p>
            <div className="kv">
              <div>File</div><div><b>{res.name}</b> · {fmtBytes(res.size)} · {res.mime}</div>
              <div>Content ID</div><div className="mono">{res.file_id}</div>
              <div>SHA-256 fixity</div><div className="mono">{short(res.fixity, 32)}</div>
              {res.chunks_total != null && <>
                <div>Chunks</div>
                <div>{res.chunks_total} total · {uniqueInFile} unique · <b>{reused}</b> already in network ·{" "}
                  <b>{res.chunks_new}</b> new</div>
                <div>Reused share</div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <Meter tone="green" value={uniqueInFile ? reused / uniqueInFile : res.duplicate === "file" ? 1 : 0} />
                  <span className="muted">{uniqueInFile ? Math.round((reused / uniqueInFile) * 100) : 100}%</span>
                </div>
              </>}
              {res.stored_bytes_including_replicas != null && <>
                <div>Bytes written</div><div>{fmtBytes(res.stored_bytes_including_replicas)} (incl. replicas)</div>
              </>}
              {res.dhash && <><div>dHash</div><div className="mono">{res.dhash}</div></>}
            </div>
            <div style={{ marginTop: 14 }}>
              <button className="btn ghost" onClick={() => onOpenFile(res.file_id)}>Open file details</button>
            </div>
          </div>
        )}
      </div>

      <div>
        <div className="card">
          <h3><Icon name="image" size={16} /> Near-duplicates</h3>
          {!res && <div className="empty">Upload an image to search the shared dHash index.</div>}
          {res && !res.dhash && <div className="empty">Not an image.</div>}
          {res?.dhash && !res.near_duplicates?.length && <div className="empty">No similar image in the network.</div>}
          {res?.near_duplicates?.map((n) => (
            <div key={n.file_id} className="peer" style={{ cursor: "pointer" }} onClick={() => onOpenFile(n.file_id)}>
              <div className="avatar">{Math.round(n.similarity * 100)}%</div>
              <div style={{ flex: 1 }}>
                <b>{n.name}</b>
                <div className="muted">Hamming {n.hamming}/64 · owner {shortAddr(n.owner)}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="card mt">
          <h3><Icon name="spark" size={16} /> AI result <span className="right">
            {ai?.status === "done" ? <span className="badge green">done</span> : ai ? <span className="badge">{ai.status}</span> : null}
          </span></h3>
          {!ai && <div className="empty">Runs once on the uploading node, then shared with all peers.</div>}
          {ai?.status === "pending" && <div className="note">Model running on this node… (first run downloads the model)</div>}
          {ai?.summary && <p style={{ marginTop: 0, lineHeight: 1.5 }}>{ai.summary}</p>}
          {ai?.caption && (
            <>
              <p style={{ marginTop: 0, fontSize: 16 }}>“{ai.caption}”</p>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <span className={`badge ${ai.reliable ? "green" : "amber"}`}>{ai.reliable ? "reliable" : "low reliability"}</span>
                {ai.confidence != null && <span className="badge blue">confidence {ai.confidence}</span>}
                <span className="badge">not verified</span>
              </div>
              {ai.reliability_note && <div className="note mt">{ai.reliability_note}</div>}
            </>
          )}
          {ai?.model && <div className="muted mt">model: {ai.model} · computed by {ai.computed_by}</div>}
        </div>
      </div>
    </div>
  );
}
