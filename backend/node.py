"""
Entry point of one P2P node:  python node.py --port 5001 --zone zone-A

Two groups of HTTP routes:
  /p2p/*   node-to-node protocol. Every request must be signed with the swarm
           key (Paper 1, private swarm). Used for DHT, chunk transfer, heartbeats.
  /api/*   local API used by the React dashboard running on the same laptop.
  /gateway/<file_id>  read-only download "gateway" (Paper 1 exposes a read-only
           HTTP gateway so users can fetch content without admin access).
"""
import json
import logging
import os
import sys
import threading
import time

from flask import Flask, Response, abort, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import PROJECT_DIR, parse_args  # noqa: E402
from core.service import NodeService  # noqa: E402
from p2p import framing, security  # noqa: E402
from p2p.dht import DHT, key_id  # noqa: E402
from storage.store import LocalStore  # noqa: E402

cfg = parse_args()
store = LocalStore(cfg.data_dir)
dht = DHT(cfg, store)
svc = NodeService(cfg, store, dht)
app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.WARNING)   # no log line per heartbeat
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
app.json.sort_keys = False                         # keep result order for the dashboard


# --------------------------------------------------------------------------- middleware
@app.before_request
def check_swarm_signature():
    if not request.path.startswith("/p2p/"):
        return None
    if request.method == "OPTIONS":
        return None
    body = request.get_data(cache=True)
    if not security.verify(cfg.swarm_key, request.method, request.path, body,
                           request.headers.get("X-Swarm-Ts"), request.headers.get("X-Swarm-Sig")):
        abort(403, "bad swarm signature")
    sender = request.headers.get("X-Node-Addr")
    if sender and sender.startswith(("http://", "https://")):   # Kademlia: learn peers from incoming RPCs
        dht.add_peer(sender, request.headers.get("X-Node-Zone", "?"),
                     request.headers.get("X-Node-Name", "?"))
    return None


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,OPTIONS"
    return resp


# --------------------------------------------------------------------------- P2P protocol
@app.post("/p2p/ping")
def p2p_ping():
    return jsonify({"name": cfg.name, "zone": cfg.zone, "address": cfg.address, "ts": time.time()})


@app.post("/p2p/find_node")
def p2p_find_node():
    target = int(request.json["target"], 16)
    nodes = dht.closest(target, cfg.k_bucket_size, include_self=True)
    return jsonify({"nodes": [p.to_dict() for p in nodes]})


@app.post("/p2p/store")
def p2p_store():
    dht.local_store_batch(request.json["items"])
    return jsonify({"ok": True})


@app.post("/p2p/get")
def p2p_get():
    return jsonify({"values": dht.local_get_batch(request.json["keys"],
                                                  observer=request.headers.get("X-Node-Addr", "?"))})


@app.put("/p2p/chunk/<h>")
def p2p_put_chunk(h):
    if not store.put_chunk(h, request.get_data(), cfg.encrypt):
        abort(400, "hash mismatch")
    return jsonify({"ok": True})


@app.get("/p2p/chunk/<h>")
def p2p_get_chunk(h):
    data = store.get_chunk(h)
    if data is None:
        abort(404)
    return Response(data, mimetype="application/octet-stream")


@app.post("/p2p/chunks/put")
def p2p_put_chunks():
    """Batch upload of many chunks in one request (see p2p/framing.py)."""
    with store.batch():
        bad = [h for h, data in framing.unpack(request.get_data()) if not store.put_chunk(h, data, cfg.encrypt)]
    return jsonify({"ok": not bad, "rejected": bad})


@app.post("/p2p/chunks/get")
def p2p_get_chunks():
    items = [(h, store.get_chunk(h)) for h in request.json["hashes"]]
    return Response(framing.pack([(h, d) for h, d in items if d is not None]),
                    mimetype="application/octet-stream")


@app.post("/p2p/resolve/<pid>")
def p2p_resolve(pid):
    r = store.q("SELECT file_id FROM pseudonyms WHERE pid=?", (pid,), one=True)
    if not r:
        abort(404)
    m = store.dht_get(f"file:{r['file_id']}") or dht.get(f"file:{r['file_id']}") or {}
    return jsonify({"file_id": r["file_id"], "name": m.get("name"), "owner": cfg.address})


@app.post("/p2p/list_files")
def p2p_list_files():
    return jsonify({"files": _local_manifests()})


@app.post("/p2p/summary")
def p2p_summary():
    return jsonify(_local_summary())


def _local_summary():
    ups = store.q("SELECT file_id, size FROM uploads")
    return {"node": cfg.name, "uploads": [[r["file_id"], r["size"]] for r in ups],
            "chunks": {r["hash"]: r["size"] for r in store.q("SELECT hash, size FROM chunks")}}


@app.get("/api/network_summary")
def api_network_summary():
    """Network-wide dedup numbers, aggregated from every live node."""
    parts = [_local_summary()]
    for p in dht.alive_peers():
        try:
            parts.append(dht.rpc(p.address, "/p2p/summary", {}).json())
        except Exception:
            pass
    logical = sum(s for part in parts for _, s in part["uploads"])
    upload_count = sum(len(part["uploads"]) for part in parts)
    distinct_files = len({fid for part in parts for fid, _ in part["uploads"]})
    unique_chunks = {}
    raw = 0
    for part in parts:
        for h, s in part["chunks"].items():
            unique_chunks[h] = s
            raw += s
    unique = sum(unique_chunks.values())
    return jsonify({
        "nodes_reporting": len(parts), "uploads": upload_count, "distinct_files": distinct_files,
        "file_level_duplicates": upload_count - distinct_files,
        "logical_bytes": logical, "unique_bytes": unique, "raw_bytes_with_replicas": raw,
        "dedup_saving": round(1 - unique / logical, 4) if logical else 0,
        "replication_factor_observed": round(raw / unique, 2) if unique else 0,
    })


def _local_manifests():
    out = []
    for key, m in store.dht_items():
        if key.startswith("file:"):
            out.append({k: m.get(k) for k in ("file_id", "name", "size", "mime", "origin",
                                               "uploaded_at", "dhash", "object_uid")}
                       | {"chunks": len(m.get("chunks", []))})
    return out


# --------------------------------------------------------------------------- dashboard API
@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "node": cfg.name})


@app.get("/api/stats")
def api_stats():
    return jsonify(svc.stats())


@app.get("/api/peers")
def api_peers():
    now = time.time()
    rows = []
    for p in dht.all_peers():
        rows.append({**p.to_dict(), "alive": dht.is_alive(p),
                     "last_seen_s": None if not p.last_seen else round(now - p.last_seen, 1),
                     "rtt_ms": None if p.rtt_ms is None else round(p.rtt_ms, 1),
                     "bucket": dht.bucket_index(p.id),
                     "id": f"{p.id:064x}"})
    return jsonify({"self": {**dht.self_peer.to_dict(), "id": f"{dht.id:064x}"}, "peers": rows})


@app.post("/api/upload")
def api_upload():
    f = request.files.get("file")
    if f is None:
        abort(400, "no file")
    data = f.read()
    return jsonify(svc.upload(f.filename, data, request.form.get("object_uid", "").strip()))


@app.get("/api/files")
def api_files():
    """All files known in the network: ask every live peer which manifests it holds."""
    files = {m["file_id"]: m for m in _local_manifests()}
    for p in dht.alive_peers():
        try:
            for m in dht.rpc(p.address, "/p2p/list_files", {}).json()["files"]:
                files.setdefault(m["file_id"], m)
        except Exception:
            pass
    keys = [f"ai:{fid}" for fid in files]
    ai = dht.get_many(keys) if keys else {}
    for fid, m in files.items():
        m["ai"] = ai.get(f"ai:{fid}")
    return jsonify(sorted(files.values(), key=lambda m: -(m.get("uploaded_at") or 0)))


@app.get("/api/files/<fid>")
def api_file(fid):
    m = dht.get(f"file:{fid}")
    if not m:
        abort(404)
    hashes = sorted({c["hash"] for c in m["chunks"]})
    prov = dht.get_many([f"prov:{h}" for h in hashes])
    alive = {p.address for p in dht.alive_peers()} | {cfg.address}
    replicas = {}
    for h in hashes:
        nodes = [e["node"] for e in (prov.get(f"prov:{h}") or {}).get("entries", {}).values()]
        replicas[h] = {"nodes": nodes, "live": [n for n in nodes if n in alive]}
    healthy = sum(1 for r in replicas.values() if len(r["live"]) >= cfg.replication_k)
    m = dict(m)
    m.pop("wrapped_keys", None)
    return jsonify({"manifest": m, "ai": dht.get(f"ai:{fid}"), "replicas": replicas,
                    "replication": {"unique_chunks": len(hashes), "healthy": healthy,
                                    "k": cfg.replication_k}})


@app.get("/api/download/<fid>")
@app.get("/gateway/<fid>")
def api_download(fid):
    t0 = time.time()
    try:
        m, data = svc.download(fid)
    except KeyError:
        abort(404)
    except IOError as e:
        abort(503, str(e))
    dt = time.time() - t0
    resp = Response(data, mimetype=m.get("mime") or "application/octet-stream")
    resp.headers["Content-Disposition"] = f'attachment; filename="{m.get("name", fid)}"'
    resp.headers["X-Recovery-Seconds"] = f"{dt:.4f}"           # used for R_logical = S/t (Paper 1)
    resp.headers["Access-Control-Expose-Headers"] = "X-Recovery-Seconds"
    return resp


@app.get("/api/neardup/<fid>")
def api_neardup(fid):
    m = dht.get(f"file:{fid}")
    if not m or not m.get("dhash"):
        return jsonify([])
    return jsonify(svc.find_near_duplicates(int(m["dhash"], 16), exclude=fid))


@app.get("/api/objects/<uid>")
def api_object(uid):
    v = dht.get(f"obj:{uid}") or {"entries": {}}
    ids = [e["file_id"] for e in sorted(v["entries"].values(), key=lambda e: e["ts"])]
    mans = dht.get_many([f"file:{i}" for i in ids]) if ids else {}
    return jsonify([{"file_id": i, "name": (mans.get(f"file:{i}") or {}).get("name"),
                     "size": (mans.get(f"file:{i}") or {}).get("size")} for i in ids])


@app.get("/api/health")
def api_health():
    """Replication health of the chunks this node stores (for the donut chart)."""
    hashes = store.chunk_hashes()
    prov = dht.get_many([f"prov:{h}" for h in hashes]) if hashes else {}
    alive = {p.address for p in dht.alive_peers()} | {cfg.address}
    buckets = {"healthy": 0, "under_replicated": 0}
    for h in hashes:
        live = {e["node"] for e in (prov.get(f"prov:{h}") or {}).get("entries", {}).values()} & alive
        buckets["healthy" if len(live) >= cfg.replication_k else "under_replicated"] += 1
    return jsonify(buckets | {"total": len(hashes), "k": cfg.replication_k})


@app.get("/api/telemetry")
def api_telemetry():
    rows = store.q("SELECT ts, value FROM telemetry WHERE kind='block_stat_ms' ORDER BY ts DESC LIMIT 120")
    return jsonify([{"ts": r["ts"], "ms": round(r["value"], 3)} for r in reversed(rows)])


@app.get("/api/events")
def api_events():
    rows = store.q("SELECT ts, kind, message FROM events ORDER BY ts DESC LIMIT 60")
    return jsonify([dict(r) for r in rows])


@app.get("/api/query_log")
def api_query_log():
    rows = store.q("SELECT ts, query_key, returned FROM query_log ORDER BY ts")
    return jsonify([{"ts": r["ts"], "key": r["query_key"], "returned": json.loads(r["returned"])}
                    for r in rows])


@app.get("/api/eval")
def api_eval():
    """Serve evaluation results written by the scripts in eval/ (for the dashboard)."""
    d = os.path.join(PROJECT_DIR, "eval", "results")
    out = {}
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                with open(os.path.join(d, fn)) as fh:
                    out[fn[:-5]] = json.load(fh)
    return jsonify(out)


@app.get("/api/dht/whereis/<path:key>")
def api_whereis(key):
    return jsonify({"key": key, "key_id": f"{key_id(key):064x}",
                    "responsible": [p.to_dict() for p in dht.responsible_for(key)]})


# --------------------------------------------------------------------------- start-up
def background():
    time.sleep(1.0)                    # let the HTTP server start first
    dht.bootstrap()
    store.log_event("peer", f"{cfg.name} joined; knows {len(dht.alive_peers())} peers")
    threading.Thread(target=svc.heartbeat_loop, daemon=True).start()
    threading.Thread(target=svc.maintenance_loop, daemon=True).start()


if __name__ == "__main__":
    print(f"[{cfg.name}] {cfg.address} zone={cfg.zone} id={dht.id:064x}"[:120], flush=True)
    print(f"[{cfg.name}] listening on {cfg.host}:{cfg.port}  bootstrap={cfg.bootstrap}", flush=True)
    print(f"[{cfg.name}] data dir: {cfg.data_dir}  chunker={cfg.chunker} target={cfg.target_chunk_size} "
          f"k={cfg.replication_k}", flush=True)
    threading.Thread(target=background, daemon=True).start()
    app.run(host=cfg.host, port=cfg.port, threaded=True, debug=False, use_reloader=False)
