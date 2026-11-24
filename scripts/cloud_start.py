"""
ONE-SERVICE cloud mode (for Render when your workspace has no room for 3 services).

What runs inside the single Render service:
  * 3 real, independent node processes (node.py) on internal ports 5001-5003,
    each with its own SQLite database, blockstore, zone and DHT routing table.
    They talk to each other over HTTP exactly like on a laptop.
  * a small "gateway" Flask app on Render's public $PORT that
      - serves the prebuilt React dashboard            ->  /
      - forwards dashboard calls to node i              ->  /n/<i>/api/...
      - can stop / start a node to simulate a failure   ->  /cluster/stop/<i>, /cluster/start/<i>

Start command on Render:   python scripts/cloud_start.py
Locally you can try it too: python scripts/cloud_start.py   (then open http://localhost:10000)
"""
import os
import secrets
import subprocess
import sys
import threading
import time

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(ROOT, "backend", "node.py")
DIST = os.path.join(ROOT, "backend", "dashboard_dist")       # prebuilt React app
N_NODES = int(os.environ.get("CLUSTER_NODES", "3"))
BASE_PORT = 5001
SWARM_KEY = os.environ.get("SWARM_KEY") or secrets.token_hex(16)
ZONES = ["zone-A", "zone-B", "zone-A", "zone-B", "zone-A"]

procs = {}
lock = threading.Lock()


def node_url(i: int) -> str:
    return f"http://127.0.0.1:{BASE_PORT + i - 1}"


def start_node(i: int):
    """Launch node i as a separate OS process."""
    with lock:
        if i in procs and procs[i].poll() is None:
            return
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("RENDER_EXTERNAL") and k not in ("PORT", "ADVERTISE_URL", "BOOTSTRAP",
                                                                    "BOOTSTRAP_HOST", "NODE_NAME", "NODE_ZONE")}
        port = BASE_PORT + i - 1
        args = [sys.executable, NODE, "--host", "127.0.0.1", "--port", str(port),
                "--advertise", node_url(i), "--name", f"node{i}", "--zone", ZONES[(i - 1) % len(ZONES)],
                "--swarm-key", SWARM_KEY, "--data-dir", os.path.join(ROOT, "data", f"node{i}-{port}")]
        if i > 1:
            args += ["--bootstrap", node_url(1)]
        procs[i] = subprocess.Popen(args, env=env)
    print(f"[cluster] started node{i} on {node_url(i)}", flush=True)


def stop_node(i: int):
    with lock:
        p = procs.get(i)
        if p and p.poll() is None:
            p.terminate()
            p.wait(timeout=10)
    print(f"[cluster] stopped node{i}", flush=True)


app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
HOP = {"content-encoding", "transfer-encoding", "connection", "content-length", "keep-alive"}


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "nodes": {i: procs[i].poll() is None for i in procs}})


@app.route("/n/<int:i>/<path:path>", methods=["GET", "POST", "PUT"])
def forward(i, path):
    """Forward a dashboard request to node i (same request, same response)."""
    if not 1 <= i <= N_NODES:
        return jsonify({"error": "no such node"}), 404
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("content-type", "accept")}
    try:
        r = requests.request(request.method, f"{node_url(i)}/{path}", params=request.args,
                             data=request.get_data(), headers=headers, timeout=300)
    except requests.RequestException:
        return jsonify({"error": f"node{i} is down"}), 502
    return Response(r.content, r.status_code, [(k, v) for k, v in r.headers.items() if k.lower() not in HOP])


@app.get("/cluster/status")
def cluster_status():
    return jsonify([{"node": i, "url": f"/n/{i}", "running": procs[i].poll() is None} for i in sorted(procs)])


@app.post("/cluster/stop/<int:i>")
def cluster_stop(i):
    if i == 1:
        return jsonify({"error": "node1 is the bootstrap node; stop node2 or node3 for the demo"}), 400
    stop_node(i)
    return cluster_status()


@app.post("/cluster/start/<int:i>")
def cluster_start(i):
    start_node(i)
    return cluster_status()


@app.get("/")
@app.get("/<path:path>")
def dashboard(path="index.html"):
    if not os.path.exists(os.path.join(DIST, path)):
        path = "index.html"
    return send_from_directory(DIST, path)


def main():
    for i in range(1, N_NODES + 1):
        start_node(i)
        time.sleep(1.0)
    port = int(os.environ.get("PORT", "10000"))
    print(f"[cluster] gateway + dashboard on http://0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
