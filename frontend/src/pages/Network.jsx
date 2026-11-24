import { useEffect, useState } from "react";
import { ago, CLUSTER, cluster } from "../api";
import { Icon } from "../components/ui";

// Network: who this node knows (k-buckets), liveness from heartbeats,
// and a "where would this key be stored?" tool to explain XOR distance.
export default function Network({ api, tick }) {
  const [p, setP] = useState(null);
  const [events, setEvents] = useState([]);
  const [key, setKey] = useState("file:example");
  const [where, setWhere] = useState(null);

  useEffect(() => {
    api.peers().then(setP).catch(() => setP(null));
    api.events().then(setEvents).catch(() => {});
  }, [api, tick]);

  const [cl, setCl] = useState([]);
  useEffect(() => { if (CLUSTER) cluster.status().then(setCl).catch(() => {}); }, [tick]);
  const toggle = async (n) => setCl(await (n.running ? cluster.stop(n.node) : cluster.start(n.node)));

  const lookup = () => api.whereis(key).then(setWhere).catch(() => setWhere(null));

  return (
    <div className="grid g-main">
      <div>
        <div className="card">
          <h3><Icon name="network" size={16} /> Routing table <span className="muted">· Kademlia k-buckets</span></h3>
          {p && (
            <div className="note" style={{ marginBottom: 10 }}>
              This node: <b>{p.self.name}</b> ({p.self.zone}) · id <span className="mono">{p.self.id.slice(0, 20)}…</span>
            </div>
          )}
          {!p && <div className="err">Node not reachable.</div>}
          {p?.peers.map((x) => (
            <div className="peer" key={x.address}>
              <div className={`avatar ${x.zone === "zone-B" ? "b" : ""}`}>{x.name.replace("node", "N")}</div>
              <div style={{ flex: 1 }}>
                <b>{x.name}</b> <span className="muted mono">{x.address}</span>
                <div className="muted">zone {x.zone} · bucket {x.bucket} (XOR distance 2^{x.bucket}…2^{x.bucket + 1})
                  · id {x.id.slice(0, 12)}…</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <span className={`dot ${x.alive ? "ok" : "bad"}`} /> <b>{x.alive ? "alive" : "dead"}</b>
                <div className="muted">seen {x.last_seen_s ?? "–"}s ago · rtt {x.rtt_ms ?? "–"} ms</div>
              </div>
            </div>
          ))}
          {p && !p.peers.length && <div className="empty">No peers yet. Start more nodes with --bootstrap.</div>}
        </div>

        {CLUSTER && (
          <div className="card mt">
            <h3><Icon name="shield" size={16} /> Simulate a node failure</h3>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {cl.map((n) => (
                <button key={n.node} className={`btn ${n.running ? "ghost" : ""}`} disabled={n.node === 1}
                  onClick={() => toggle(n)}>
                  <span className={`dot ${n.running ? "ok" : "bad"}`} /> node{n.node} · {n.running ? "stop" : "start"}
                </button>
              ))}
            </div>
            <div className="muted mt">Stop node2 or node3, wait ~20 s: heartbeats mark it dead and the
              under-replicated chunks are copied again. Downloads keep working. node1 is the bootstrap node.</div>
          </div>
        )}

        <div className="card mt">
          <h3><Icon name="search" size={16} /> Where is a key stored?</h3>
          <div style={{ display: "flex", gap: 10 }}>
            <input className="field" value={key} onChange={(e) => setKey(e.target.value)} />
            <button className="btn" onClick={lookup}>Locate</button>
          </div>
          {where && (
            <div className="kv mt">
              <div>key id (SHA-256)</div><div className="mono">{where.key_id.slice(0, 32)}…</div>
              <div>responsible nodes</div>
              <div>{where.responsible.map((r) => <span key={r.address} className="badge blue" style={{ marginRight: 6 }}>
                {r.name} · {r.zone}</span>)}</div>
            </div>
          )}
          <div className="muted mt">The k nodes with the smallest XOR(node id, key id) hold the key; we prefer
            different zones so one failure domain cannot hold every replica (Paper 1).</div>
        </div>
      </div>

      <div className="card">
        <h3>Event log <span className="muted">· heartbeats, repairs, integrity</span></h3>
        <ul className="events" style={{ maxHeight: 620 }}>
          {events.map((e, i) => (
            <li key={i}>
              <span className="when">{ago(e.ts)}</span>
              <span><span className={`badge ${e.kind === "peer" ? "blue" : e.kind === "repair" ? "amber" :
                e.kind === "integrity" || e.kind === "error" ? "red" : "green"}`}>{e.kind}</span> {e.message}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
