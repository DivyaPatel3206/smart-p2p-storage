"""
Evaluation 1 — reproduces the metrics of the BASE PAPER:
  Gregoriadis et al., "Benchmarking Content-Defined Chunking Algorithms for
  Data Deduplication", arXiv:2610.13704.

Metrics (same definitions as the paper):
  * throughput (MiB/s), median and IQR over n runs, RAND dataset, µ = 2 KiB,
    chunking only (no SHA fingerprinting)                         -> paper Table VII
  * empirical mean chunk size c̄ and standard deviation s          -> paper Table VIII
  * Max. Err = max |c̄ − µ| / µ ,  Max. CV = max s / c̄  over datasets -> paper Table IX
  * dedup ratio      = 1 − S_dedup / S_original                    -> paper Fig. 7
  * storage savings  = 1 − (S_dedup + β·N) / S_original, β = 64 B  -> paper Fig. 8
  * the AE parameterisation error: legacy h = µ/(e−1) vs corrected h = µ − 256

Run:   python eval/eval_chunking.py            (≈1–2 min)
       python eval/eval_chunking.py --quick    (fewer targets)
       python eval/eval_chunking.py --dir path/to/my/versions
Writes eval/results/chunking.json and chunking.md (+ PNG plots if matplotlib is installed).
"""
import argparse
import hashlib
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))
sys.path.insert(0, HERE)

import datasets  # noqa: E402
from storage import chunking  # noqa: E402

BETA = 64                       # metadata bytes per emitted chunk (paper Sec. VII, after Debnath et al.)
ALGS = ["fsc", "ae", "ae_legacy", "gear"]

# Paper reference values (Table VII / VIII / IX, µ = 2 KiB unless noted)
PAPER = {
    "throughput_mib_s": {"fsc": 1820, "ae": 650, "gear": 652},
    "rand_2048": {"ae": {"mean": 2048, "sd": 252}, "gear": {"mean": 2047, "sd": 2045}},
    "table_ix": {"ae": {"max_err": 0.12, "max_cv": 0.31, "min_sav": 0.71, "max_sav": 0.89},
                 "gear": {"max_err": 0.47, "max_cv": 30.79, "min_sav": 0.66, "max_sav": 0.84}},
    "ae_legacy_shrink": "13-39 % smaller than target",
}


def chunk_stats(files: list, alg: str, target: int) -> dict:
    sizes, seen, unique_bytes, original = [], set(), 0, 0
    for data in files:
        original += len(data)
        cuts = chunking.CHUNKERS[alg](data, target)
        prev = 0
        for c in cuts:
            piece = data[prev:c]
            prev = c
            sizes.append(len(piece))
            h = hashlib.sha256(piece).digest()
            if h not in seen:
                seen.add(h)
                unique_bytes += len(piece)
    n = len(sizes)
    mean = statistics.fmean(sizes) if sizes else 0
    sd = statistics.pstdev(sizes) if n > 1 else 0
    return {
        "chunks": n, "unique_chunks": len(seen), "mean": round(mean, 1), "sd": round(sd, 1),
        "err": round(abs(mean - target) / target, 3), "cv": round(sd / mean, 3) if mean else None,
        "dedup_ratio": round(1 - unique_bytes / original, 4),
        "storage_savings": round(1 - (unique_bytes + BETA * n) / original, 4),
    }


def throughput(data: bytes, alg: str, target: int, runs: int) -> dict:
    """Time to cut the data into chunk byte-strings (no hashing, like the paper).
    We include the slicing so that FSC is also measured doing real memory work."""
    chunking.split(data[: 64 * 1024], alg, target)                    # warm-up run (paper Sec. III-B)
    rates = []
    for _ in range(runs):
        t0 = time.perf_counter()
        chunking.split(data, alg, target)
        rates.append(len(data) / (time.perf_counter() - t0) / 2 ** 20)
    q = statistics.quantiles(rates, n=4) if len(rates) >= 2 else [rates[0]] * 3
    return {"median": round(statistics.median(rates), 2), "iqr": round(q[2] - q[0], 2), "runs": runs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--dir", default=None, help="extra dataset: a folder of your own files/versions")
    a = ap.parse_args()
    targets = [1024, 2048, 4096] if a.quick else [512, 1024, 2048, 4096, 8192]

    print("building datasets ...")
    ds = {"RAND": datasets.rand_dataset(1.0 if a.quick else 2.0),
          "CODE": datasets.code_dataset(4 if a.quick else 6),
          "DB": datasets.db_dataset(5 if a.quick else 8)}
    if a.dir:
        ds["DIR"] = datasets.dir_dataset(a.dir)
    info = {k: {"files": len(v), "mb": round(sum(map(len, v)) / 2 ** 20, 2)} for k, v in ds.items()}
    print(info)

    results = {"datasets": info, "targets": targets, "beta": BETA, "paper": PAPER, "stats": {}}
    for name, files in ds.items():
        for alg in ALGS:
            for t in targets:
                st = chunk_stats(files, alg, t)
                results["stats"].setdefault(name, {}).setdefault(alg, {})[str(t)] = st
                print(f"{name:5s} {alg:10s} µ={t:5d}  c̄={st['mean']:8.1f}  s={st['sd']:8.1f}  "
                      f"dedup={st['dedup_ratio']:.3f}  savings={st['storage_savings']:.3f}")

    print("throughput on RAND, µ = 2048 ...")
    results["throughput"] = {alg: throughput(ds["RAND"][0], alg, 2048, a.runs) for alg in ALGS}
    print(results["throughput"])

    # ---- Table IX style summary at µ = 2 KiB over the realistic datasets
    real = [d for d in ds if d != "RAND"]
    summary = {}
    for alg in ALGS:
        rows = [results["stats"][d][alg]["2048"] for d in real]
        summary[alg] = {
            "throughput": results["throughput"][alg]["median"],
            "max_err": max(r["err"] for r in rows), "max_cv": max(r["cv"] for r in rows),
            "min_savings": min(r["storage_savings"] for r in rows),
            "max_savings": max(r["storage_savings"] for r in rows),
        }
    results["table_ix"] = summary

    # ---- AE parameterisation finding
    shrink = {}
    for t in targets:
        m = results["stats"]["RAND"]["ae_legacy"][str(t)]["mean"]
        shrink[str(t)] = round(1 - m / t, 3)
    results["ae_legacy_shrink_on_rand"] = shrink

    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "chunking.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    write_markdown(results, os.path.join(out_dir, "chunking.md"))
    try:
        plot(results, out_dir)
    except Exception as e:                       # matplotlib optional
        print("plots skipped:", e)
    print("\nwritten: eval/results/chunking.json, chunking.md")


def write_markdown(r, path):
    L = ["# Chunking evaluation (metrics of Paper 2)\n",
         f"Datasets: {r['datasets']}  •  β = {r['beta']} B metadata per chunk\n",
         "## Table IX equivalent (µ = 2 KiB, realistic datasets)\n",
         "| Algorithm | Throughput MiB/s (ours, Python) | Max Err ↓ | Max CV ↓ | Min savings ↑ | Max savings ↑ | Paper (AE/Gear) |",
         "|---|---|---|---|---|---|---|"]
    for alg, s in r["table_ix"].items():
        p = r["paper"]["table_ix"].get(alg)
        ref = (f"{r['paper']['throughput_mib_s'].get(alg, '-')} MiB/s, err {p['max_err']}, CV {p['max_cv']}, "
               f"sav {p['min_sav']}–{p['max_sav']}") if p else (
            f"{r['paper']['throughput_mib_s'].get(alg, '-')} MiB/s" if alg in r['paper']['throughput_mib_s'] else "-")
        L.append(f"| {alg} | {s['throughput']} (IQR {r['throughput'][alg]['iqr']}) | {s['max_err']} | "
                 f"{s['max_cv']} | {s['min_savings']} | {s['max_savings']} | {ref} |")
    L += ["\n## Mean chunk size c̄ / std s per dataset (Table VIII equivalent)\n"]
    for d, algs in r["stats"].items():
        L.append(f"\n### {d}\n")
        L.append("| Algorithm | " + " | ".join(f"µ={t}: c̄ / s" for t in r["targets"]) + " |")
        L.append("|---|" + "---|" * len(r["targets"]))
        for alg, per in algs.items():
            L.append(f"| {alg} | " + " | ".join(f"{per[str(t)]['mean']:.0f} / {per[str(t)]['sd']:.0f}"
                                               for t in r["targets"]) + " |")
    L += ["\n## Dedup ratio and storage savings (Fig. 7 / Fig. 8 equivalent)\n",
          "| Dataset | Algorithm | " + " | ".join(f"µ={t}" for t in r["targets"]) + " |",
          "|---|---|" + "---|" * len(r["targets"])]
    for d, algs in r["stats"].items():
        if d == "RAND":
            continue
        for alg, per in algs.items():
            L.append(f"| {d} | {alg} | " + " | ".join(
                f"{per[str(t)]['dedup_ratio']:.3f} / {per[str(t)]['storage_savings']:.3f}" for t in r["targets"]) + " |")
    L += ["\nEach cell: dedup ratio / storage savings.\n",
          "\n## AE parameterisation error (paper Sec. IV-B)\n",
          "Legacy rule h = µ/(e−1) gives chunks this much SMALLER than the target on RAND "
          f"(paper reports 13–39 %): {r['ae_legacy_shrink_on_rand']}\n"]
    with open(path, "w") as fh:
        fh.write("\n".join(L))


def plot(r, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    real = [d for d in r["stats"] if d != "RAND"]
    fig, axes = plt.subplots(1, len(real), figsize=(5 * len(real), 3.6))
    if len(real) == 1:
        axes = [axes]
    for ax, d in zip(axes, real):
        for alg in ALGS:
            ys = [r["stats"][d][alg][str(t)]["dedup_ratio"] for t in r["targets"]]
            ax.plot(r["targets"], ys, marker="o", label=alg)
        ax.set_xscale("log", base=2)
        ax.set_title(d)
        ax.set_xlabel("target chunk size µ (B)")
        ax.set_ylabel("dedup ratio")
        ax.grid(alpha=0.3)
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "dedup_ratio.png"), dpi=130)
    print("plot: eval/results/dedup_ratio.png")


if __name__ == "__main__":
    main()
