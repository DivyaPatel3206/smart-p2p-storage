import { useEffect, useState } from "react";
import { Icon, Meter } from "../components/ui";

// Evaluation: shows the JSON written by the scripts in eval/ next to the
// numbers reported in the papers, so results can be compared in the viva.
export default function Evaluation({ api }) {
  const [ev, setEv] = useState(null);
  const [tab, setTab] = useState("chunking");
  useEffect(() => { api.evals().then(setEv).catch(() => setEv({})); }, [api]);

  if (!ev) return <div className="empty">loading…</div>;
  const tabs = [["chunking", "Chunking · Paper 2"], ["network", "Network · Paper 1"],
    ["neardup", "Near-duplicates"], ["privacy", "Privacy · Paper 3"], ["ai", "AI · Paper 4"]];

  return (
    <>
      <div className="pill-tabs" style={{ marginBottom: 16 }}>
        {tabs.map(([k, label]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {!ev[tab] ? (
        <div className="card"><div className="empty">
          No results yet. Run <span className="mono">python eval/eval_{tab === "ai" ? "ai" : tab}.py</span> and refresh.
        </div></div>
      ) : tab === "chunking" ? <Chunking r={ev.chunking} />
        : tab === "network" ? <NetworkEval r={ev.network} />
          : tab === "neardup" ? <NearDup r={ev.neardup} />
            : tab === "privacy" ? <Privacy r={ev.privacy} /> : <AI r={ev.ai} />}
    </>
  );
}

function Chunking({ r }) {
  const p = r.paper;
  return (
    <>
      <div className="grid g-3">
        <div className="card feature">
          <h3><Icon name="chunk" size={16} /> AE calibration on RAND (µ = 2048)</h3>
          <div className="split">
            <div><div className="big">{Math.round(r.stats.RAND.ae["2048"].mean)}</div><div className="muted">our mean c̄ (paper 2048)</div></div>
            <div><div className="big">{Math.round(r.stats.RAND.ae["2048"].sd)}</div><div className="muted">our std s (paper 252)</div></div>
          </div>
        </div>
        <div className="card">
          <h3>Legacy AE formula error</h3>
          {Object.entries(r.ae_legacy_shrink_on_rand).map(([t, v]) => (
            <div key={t} style={{ display: "flex", gap: 10, alignItems: "center", margin: "6px 0" }}>
              <span className="mono" style={{ width: 52 }}>µ={t}</span><Meter value={v / 0.45} />
              <b style={{ width: 52, textAlign: "right" }}>{(v * 100).toFixed(1)}%</b>
            </div>
          ))}
          <div className="muted">chunks smaller than target with h = µ/(e−1). Paper: 13–39 %.</div>
        </div>
        <div className="card">
          <h3>Datasets</h3>
          {Object.entries(r.datasets).map(([k, v]) => <div key={k} className="kv"><div>{k}</div><div>{v.files} files · {v.mb} MB</div></div>)}
          <div className="muted mt">β = {r.beta} B metadata per chunk</div>
        </div>
      </div>
      <div className="card mt">
        <h3>Table IX equivalent (µ = 2 KiB, realistic datasets) vs paper</h3>
        <table>
          <thead><tr><th>Algorithm</th><th>Throughput MiB/s (ours, Python)</th><th>Paper MiB/s (Rust)</th>
            <th>Max Err ↓</th><th>Max CV ↓</th><th>Savings min–max ↑</th><th>Paper err / CV / savings</th></tr></thead>
          <tbody>
            {Object.entries(r.table_ix).map(([alg, s]) => {
              const pp = p.table_ix[alg];
              return (
                <tr key={alg}>
                  <td><b>{alg}</b></td><td>{s.throughput}</td><td>{p.throughput_mib_s[alg] ?? "–"}</td>
                  <td>{s.max_err}</td><td>{s.max_cv}</td><td>{s.min_savings} – {s.max_savings}</td>
                  <td className="muted">{pp ? `${pp.max_err} / ${pp.max_cv} / ${pp.min_sav}–${pp.max_sav}` : "–"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="card mt">
        <h3>Dedup ratio / storage savings by target chunk size</h3>
        <table>
          <thead><tr><th>Dataset</th><th>Algorithm</th>{r.targets.map((t) => <th key={t}>µ={t}</th>)}</tr></thead>
          <tbody>
            {Object.entries(r.stats).filter(([d]) => d !== "RAND").flatMap(([d, algs]) =>
              Object.entries(algs).map(([alg, per]) => (
                <tr key={d + alg}><td>{d}</td><td><b>{alg}</b></td>
                  {r.targets.map((t) => <td key={t}>{per[t].dedup_ratio.toFixed(3)} / {per[t].storage_savings.toFixed(3)}</td>)}</tr>
              )))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function NetworkEval({ r }) {
  return (
    <div className="grid g-2">
      <div className="card">
        <h3>Ingest and recovery rate R = S / t</h3>
        <table>
          <thead><tr><th>Workload</th><th>MB</th><th>Ingest MB/s</th><th>Recovery MB/s</th><th>OK</th></tr></thead>
          <tbody>{r.workloads.map((w) => (
            <tr key={w.workload}><td>{w.workload}</td><td>{w.size_mb}</td><td>{w.ingest_mb_s}</td><td>{w.recovery_mb_s}</td>
              <td>{w.verified ? <span className="badge green">✓</span> : <span className="badge red">✗</span>}</td></tr>))}</tbody>
        </table>
        <div className="muted mt">Paper 1: recovery 182 / 368 MB/s, ingest ≈ 520 MB/s (Pi 5 + NVMe, Go).</div>
      </div>
      <div className="card">
        <h3>Block-stat probes (P50 / P90)</h3>
        <table>
          <thead><tr><th>Node</th><th>Zone</th><th>Probes</th><th>P50 ms</th><th>P90 ms</th></tr></thead>
          <tbody>{Object.values(r.telemetry).map((t) => (
            <tr key={t.node}><td>{t.node}</td><td>{t.zone}</td><td>{t.probes}</td><td>{t.p50_ms}</td><td>{t.p90_ms}</td></tr>))}</tbody>
        </table>
        <div className="muted mt">Paper 1: Edge 28.2/87.8 and 30.0/35.6 ms, Archive 15.5/18.5 and 14.3/14.9 ms.</div>
        <div className="note mt">{r.capacity.replication_health} · raw {Math.round(r.capacity.raw_bytes_all_nodes / 1e6)} MB
          → unique ≈ {Math.round(r.capacity.unique_bytes_estimate / 1e6)} MB (C_unique ≤ C_raw / r)</div>
      </div>
    </div>
  );
}

function NearDup({ r }) {
  const ts = r.thresholds;
  return (
    <div className="card">
      <h3>dHash robustness ({r.n_images} images) — recall / band-recall</h3>
      <table>
        <thead><tr><th>Transform</th><th>mean Hamming</th>{ts.map((t) => <th key={t}>T={t}</th>)}</tr></thead>
        <tbody>{Object.entries(r.transforms).map(([n, row]) => (
          <tr key={n}><td><b>{n}</b></td><td>{row.mean_hamming}</td>
            {ts.map((t) => <td key={t}>{row[`recall@${t}`]} / {row[`band_recall@${t}`]}</td>)}</tr>))}</tbody>
      </table>
      <div className="note mt">False positives between different images: {JSON.stringify(r.false_positive_rate)}.
        Band-recall is what the DHT lookup actually finds (≥ 1 identical 16-bit band).</div>
    </div>
  );
}

function Privacy({ r }) {
  return (
    <div className="card">
      <h3>SAGE-Known-lite attack on the near-duplicate index</h3>
      <table>
        <thead><tr><th>Setting</th><th>Record-label acc</th><th>Macro-F1</th><th>Query acc</th><th>Coverage</th><th>Majority</th></tr></thead>
        <tbody>{Object.entries(r.settings).map(([n, s]) => (
          <tr key={n}><td>{n}</td><td><b>{(s.record_acc.mean * 100).toFixed(1)}%</b> ± {(s.record_acc.std * 100).toFixed(1)}</td>
            <td>{s.macro_f1.mean.toFixed(3)}</td><td>{(s.query_acc.mean * 100).toFixed(1)}%</td>
            <td>{s.coverage ? `${Math.round(s.coverage.mean * 100)}%` : "–"}</td>
            <td className="muted">{(s.majority_baseline.mean * 100).toFixed(1)}%</td></tr>))}</tbody>
      </table>
      <div className="muted mt">Paper 3 reference: SAGE-Known up to 84.3 % record-label accuracy (top-k encrypted vector search).</div>
    </div>
  );
}

function AI({ r }) {
  const c = r.captions;
  return (
    <div className="grid g-2">
      <div className="card">
        <h3>Captions <span className="muted">· {c.model} · Contra-Acc: {r.contra_acc_mode}</span></h3>
        <table>
          <thead><tr><th>Resolution</th><th>ROUGE-1</th><th>ROUGE-2</th><th>ROUGE-L</th><th>METEOR*</th><th>Contra-Acc</th></tr></thead>
          <tbody>{["full", "64x64"].map((k) => (
            <tr key={k}><td>{k}</td><td>{c[k].rouge1}</td><td>{c[k].rouge2}</td><td>{c[k].rougeL}</td><td>{c[k].meteor}</td>
              <td><b>{c[k].contra_acc ?? "–"}</b></td></tr>))}</tbody>
        </table>
        <div className="muted mt">Paper 4: best closed-source ≈ 60 % Contra-Acc, humans 96.04 %, 8.68 % at 64×64. *METEOR without synonyms.</div>
        {c.examples?.slice(0, 3).map((e, i) => (
          <div key={i} className="note mt"><b>ref:</b> {e.reference}<br /><b>ours:</b> {e.caption}</div>
        ))}
      </div>
      <div className="card">
        <h3>Summaries <span className="muted">· {r.summaries.model}</span></h3>
        <div className="kv"><div>ROUGE-1</div><div>{r.summaries.rouge1}</div><div>ROUGE-2</div><div>{r.summaries.rouge2}</div>
          <div>ROUGE-L</div><div>{r.summaries.rougeL}</div></div>
        {r.summaries.examples?.map((e, i) => <div key={i} className="note mt">{e}</div>)}
      </div>
    </div>
  );
}
