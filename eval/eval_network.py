"""
Evaluation 5 — the running P2P network, with the metrics of Paper 1
(Snellings et al., "A Private IPFS Data Sanctuary ...", arXiv:2610.07970).

Needs the nodes running:  python scripts/run_nodes.py --fresh

  * ingest rate      R = S / t  for uploads                     (paper Table 2: model-weight ingest)
  * recovery rate    R_logical = S / t  for download on ANOTHER node (paper Eq. 1, Table 2)
  * block-stat probe latency P50 / P90 per node                 (paper Table 3)
  * replication health (chunks with >= k live copies) and capacity:
        C_unique <= C_raw / r                                  (paper Sec. 4.4)
  * network-wide dedup ratio = 1 - unique stored bytes / logical bytes uploaded

The paper's numbers come from Raspberry Pi 5 + NVMe over LAN/WLAN with Kubo (Go);
ours are Python on one laptop over localhost, so compare trends, not absolutes.

    python eval/eval_network.py --ports 5001,5002,5003 --sizes 1,4,16 --telemetry-wait 60
"""
import argparse
import json
import os
import random
import statistics
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
U = "http://127.0.0.1:{}".format

PAPER = {"recovery": [{"workload": "Raw acquisition A", "size_gb": 6.20, "rate_mb_s": 182},
                      {"workload": "Raw acquisition B", "size_gb": 5.19, "rate_mb_s": 368}],
         "ingest": {"workload": "Model weights", "size_gb": 156.1, "rate_mb_s": 520},
         "block_stat_ms": {"Edge-01": [28.2, 87.8], "Edge-04": [30.0, 35.6],
                           "Archive-01": [15.5, 18.5], "Archive-02": [14.3, 14.9]}}


def payload(mb, kind, seed):
    rnd = random.Random(seed)
    n = int(mb * 1024 * 1024)
    if kind == "random":
        return rnd.randbytes(n)
    words = ("data chunk replica node peer storage hash network file system archive museum "
             "measurement scan object version").split()
    out, size = [], 0
    while size < n:
        line = " ".join(rnd.choice(words) for _ in range(14)) + ".\n"
        out.append(line)
        size += len(line)
    return "".join(out).encode()[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", default="5001,5002,5003")
    ap.add_argument("--sizes", default="1,4,16", help="MB per workload")
    ap.add_argument("--telemetry-wait", type=int, default=45, help="seconds to collect block-stat probes")
    a = ap.parse_args()
    ports = [int(p) for p in a.ports.split(",")]
    sizes = [float(s) for s in a.sizes.split(",")]
    src, dst = ports[0], ports[-1]

    res = {"paper": PAPER, "workloads": []}
    logical = 0
    for i, mb in enumerate(sizes):
        for kind in ("text", "random"):
            data = payload(mb, kind, seed=1000 + i * 10 + (kind == "random"))
            name = f"eval_{kind}_{mb:g}MB.bin"
            t0 = time.time()
            r = requests.post(U(src) + "/api/upload", files={"file": (name, data)}, timeout=600).json()
            t_up = time.time() - t0
            logical += len(data)
            t0 = time.time()
            d = requests.get(U(dst) + f"/api/download/{r['file_id']}", timeout=600)
            t_down = time.time() - t0
            ok = d.status_code == 200 and d.content == data
            row = {"workload": name, "size_mb": round(len(data) / 1e6, 2),
                   "ingest_s": round(t_up, 3), "ingest_mb_s": round(len(data) / 1e6 / t_up, 2),
                   "recovery_s": round(t_down, 3), "recovery_mb_s": round(len(data) / 1e6 / t_down, 2),
                   "recovered_on": dst, "verified": ok, "chunks": r.get("chunks_total")}
            res["workloads"].append(row)
            print(row)

    print(f"collecting block-stat probes for {a.telemetry_wait}s ...")
    time.sleep(a.telemetry_wait)
    res["telemetry"] = {}
    raw_total = 0
    for p in ports:
        st = requests.get(U(p) + "/api/stats").json()
        tel = [x["ms"] for x in requests.get(U(p) + "/api/telemetry").json()]
        raw_total += st["local"]["chunk_bytes"]
        row = {"node": st["node"]["name"], "zone": st["node"]["zone"], "probes": len(tel),
               "window_h": round(st["node"]["uptime_s"] / 3600, 3),
               "p50_ms": round(statistics.median(tel), 3) if tel else None,
               "p90_ms": round(statistics.quantiles(tel, n=10)[8], 3) if len(tel) >= 2 else None,
               "chunk_bytes": st["local"]["chunk_bytes"]}
        res["telemetry"][p] = row
        print(row)

    files = requests.get(U(src) + "/api/files").json()
    healthy = total = 0
    for f in files:
        rep = requests.get(U(src) + f"/api/files/{f['file_id']}").json()["replication"]
        healthy += rep["healthy"]
        total += rep["unique_chunks"]
    k = requests.get(U(src) + "/api/stats").json()["node"]["replication_k"]
    unique_stored = raw_total / k
    res["capacity"] = {"raw_bytes_all_nodes": raw_total, "replication_k": k,
                       "unique_bytes_estimate": int(unique_stored),
                       "logical_bytes_uploaded_by_eval": logical,
                       "replication_health": f"{healthy}/{total} chunks with >= k live copies",
                       "rule": "C_unique <= C_raw / r (Paper 1, Sec. 4.4)"}
    print(res["capacity"])

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "network.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    with open(os.path.join(HERE, "results", "network.md"), "w") as fh:
        fh.write("# P2P network evaluation (Paper 1 metrics)\n\n## Ingest and recovery (R = S / t)\n\n")
        fh.write("| Workload | Size MB | Ingest MB/s | Recovery on other node MB/s | Verified |\n|---|---|---|---|---|\n")
        for w in res["workloads"]:
            fh.write(f"| {w['workload']} | {w['size_mb']} | {w['ingest_mb_s']} | {w['recovery_mb_s']} | {w['verified']} |\n")
        fh.write("\nPaper: recovery 182 and 368 MB/s (6.20 / 5.19 GB), ingest ≈520 MB/s (156.1 GB).\n\n")
        fh.write("## Block-stat probes (local blockstore access)\n\n| Node | Zone | Probes | P50 ms | P90 ms |\n|---|---|---|---|---|\n")
        for t in res["telemetry"].values():
            fh.write(f"| {t['node']} | {t['zone']} | {t['probes']} | {t['p50_ms']} | {t['p90_ms']} |\n")
        fh.write("\nPaper P50/P90 ms: Edge-01 28.2/87.8, Edge-04 30.0/35.6, Archive-01 15.5/18.5, Archive-02 14.3/14.9.\n\n")
        fh.write(f"## Capacity\n\n{res['capacity']}\n")
    print("written: eval/results/network.json, network.md")


if __name__ == "__main__":
    main()
