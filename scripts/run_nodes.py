"""
Start N nodes on one laptop (default 3) — each is a separate process with its
own port, data folder and SQLite database. Ctrl+C stops all of them.

    python scripts/run_nodes.py                # 3 nodes, ports 5001-5003
    python scripts/run_nodes.py --nodes 4 --fresh

Zones: node1 -> zone-A, node2 -> zone-B, node3 -> zone-A, ... so replicas are
spread over two failure domains (Paper 1).
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(ROOT, "backend", "node.py")


def start_node(i, base_port, extra, swarm_key):
    port = base_port + i
    zone = "zone-A" if i % 2 == 0 else "zone-B"
    args = [sys.executable, NODE, "--port", str(port), "--name", f"node{i + 1}", "--zone", zone,
            "--swarm-key", swarm_key, "--data-dir", os.path.join(ROOT, "data", f"node{i + 1}-{port}")] + extra
    if i > 0:
        args += ["--bootstrap", f"127.0.0.1:{base_port}"]
    log = open(os.path.join(ROOT, "data", f"node{i + 1}-{port}.log"), "w")
    return subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=3)
    ap.add_argument("--base-port", type=int, default=5001)
    ap.add_argument("--fresh", action="store_true", help="delete data/ before starting")
    ap.add_argument("--swarm-key", default=os.environ.get("SWARM_KEY", "change-me-shared-swarm-secret"))
    ap.add_argument("extra", nargs=argparse.REMAINDER,
                    help="extra args for every node after --, e.g. -- --encrypt --chunker gear")
    a = ap.parse_args()
    extra = [x for x in a.extra if x != "--"]

    if a.fresh and os.path.isdir(os.path.join(ROOT, "data")):
        shutil.rmtree(os.path.join(ROOT, "data"))
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

    procs = []
    for i in range(a.nodes):
        procs.append(start_node(i, a.base_port, extra, a.swarm_key))
        print(f"started node{i + 1} on http://127.0.0.1:{a.base_port + i}  (log: data/node{i + 1}-{a.base_port + i}.log)")
        time.sleep(0.8)
    print("All nodes running. Open the React dashboard (frontend) and pick a node. Ctrl+C to stop.")

    def stop(*_):
        for p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    reported = set()
    while True:
        time.sleep(2)
        for i, p in enumerate(procs):
            if p.poll() is not None and i not in reported:
                reported.add(i)
                print(f"node{i + 1} exited with code {p.returncode} (see data/node{i + 1}-{a.base_port + i}.log)")


if __name__ == "__main__":
    main()
