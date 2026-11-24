"""
Evaluation 3 — privacy of the shared near-duplicate index (Paper 3).

Paper 3 (Zhang et al., "More Than You Expect!": Leakage-Abuse Attacks on
Encrypted Vector Search, arXiv:2611.27174) shows that even when contents are
encrypted, a server that sees WHICH record identifiers are returned together
(the access pattern) can build a co-retrieval graph and infer each record's
semantic category (SAGE attack, up to 84.3 % record-label accuracy with 1 %
known labels).

In our system the nodes that hold "band:<i>:<v>" keys play that server role:
they see which image identifiers each near-duplicate query returns.

What this script does
  1. builds a database of images from C categories and a disjoint query pool
  2. answers M near-duplicate queries with the banded dHash index and records
     the access pattern (set of returned identifiers per query)
  3. runs SAGE-Known-lite: Jaccard co-retrieval graph + label propagation from a
     few known labels (the attacker's own uploads), then predicts labels
  4. repeats with OUR DEFENSE: identifier rotation (per-epoch pseudonyms), which
     the paper suggests ("identifier rotation may reduce accumulated leakage")

Metrics (same as the paper): record-label accuracy, macro-F1 (observed records,
known ones excluded), query-category accuracy; mean ± std over runs.

Simplified vs the paper: no spectral grouping / optimal transport (SAGE-Dist
is not implemented), plain label propagation instead of anchor voting.

    python eval/eval_privacy.py                  # synthetic, ~1 min
    python eval/eval_privacy.py --from-nodes 5001,5002,5003   # inspect live query logs
"""
import argparse
import collections
import json
import os
import random
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))
sys.path.insert(0, HERE)

import images  # noqa: E402
from dedup import dhash as dh  # noqa: E402


# ------------------------------------------------------------------ data
def zipf_counts(C, total, s, rnd):
    w = [1 / (i + 1) ** s for i in range(C)]
    rnd.shuffle(w)
    tot = sum(w)
    return [max(5, int(total * x / tot)) for x in w]


def build(C, n_db, s, rnd, reupload_frac):
    counts = zipf_counts(C, n_db, s, rnd)
    db = []                                  # (label, hash)
    for c, n in enumerate(counts):
        for i in range(n):
            db.append((c, dh.dhash(images.base_image(c, i))))
    index = collections.defaultdict(set)
    for rid, (_, h) in enumerate(db):
        for k in dh.band_keys(h):
            index[k].add(rid)
    return db, index, counts


def make_queries(db, C, M, rnd, reupload_frac, counts):
    """Queries = uploads by other users: some are re-uploads (near-dups) of
    existing images, the rest are new photos of the same categories."""
    qs = []
    probs = [n / sum(counts) for n in counts]
    for q in range(M):
        if rnd.random() < reupload_frac:
            rid = rnd.randrange(len(db))
            c = db[rid][0]
            im = images.random_variant(images.base_image(c, rid_local(db, rid)), rnd)
        else:
            c = rnd.choices(range(C), probs)[0]
            im = images.random_variant(images.base_image(c, 10_000 + q), rnd)
        qs.append((c, dh.dhash(im)))
    return qs


_local_cache = {}


def rid_local(db, rid):
    """index of record rid inside its category (to regenerate the same base image)."""
    if not _local_cache:
        seen = collections.Counter()
        for r, (c, _) in enumerate(db):
            _local_cache[r] = seen[c]
            seen[c] += 1
    return _local_cache[rid]


def access_patterns(qs, index, db=None, mode="band", k=10):
    """What an index holder observes for each query.
    band : OUR design - union of the 4 band buckets (exact 16-bit band matches)
    topk : the setting of Paper 3 - the k nearest records by Hamming distance"""
    out = []
    for c, h in qs:
        if mode == "band":
            ids = set()
            for key in dh.band_keys(h):
                ids |= index.get(key, set())
        else:
            ids = set(sorted(range(len(db)), key=lambda r: dh.hamming(h, db[r][1]))[:k])
        out.append(ids)
    return out


# ------------------------------------------------------------------ attack
def sage_known_lite(patterns, known: dict, C: int, alpha=0.9, iters=40):
    """patterns: list of sets of observed identifiers. known: id -> label.
    Returns (pred_label per observed id, pred category per query)."""
    V = sorted(set().union(*patterns)) if patterns else []
    pos = {v: i for i, v in enumerate(V)}
    n = len(V)
    if n == 0:
        return {}, []
    X = np.zeros((len(patterns), n))
    for i, p in enumerate(patterns):
        for v in p:
            X[i, pos[v]] = 1
    O = X.T @ X                                            # co-retrieval counts
    freq = np.diag(O).copy()
    W = O / (freq[:, None] + freq[None, :] - O + 1e-9)     # Jaccard weights
    np.fill_diagonal(W, 0)
    d = W.sum(1)
    dinv = np.where(d > 0, 1 / np.sqrt(d + 1e-12), 0)
    S = dinv[:, None] * W * dinv[None, :]
    Y = np.zeros((n, C))
    for v, lab in known.items():
        if v in pos:
            Y[pos[v], lab] = 1
    F = Y.copy()
    for _ in range(iters):                                 # label propagation
        F = alpha * S @ F + (1 - alpha) * Y
    col = F.sum(0)
    F = F / np.where(col > 0, col, 1)                      # per-category normalisation (as in SAGE)
    prior = collections.Counter(known.values()).most_common(1)
    fallback = prior[0][0] if prior else 0
    pred, reached = {}, set()
    for v in V:
        row = F[pos[v]]
        if row.max() > 0:
            reached.add(v)                                 # connected to at least one known label
        pred[v] = int(row.argmax()) if row.max() > 0 else fallback
        if v in known:
            pred[v] = known[v]
    sage_known_lite.reached = reached
    qpred = []
    for p in patterns:
        votes = collections.Counter(pred[v] for v in p)
        qpred.append(votes.most_common(1)[0][0] if votes else fallback)
    return pred, qpred


def macro_f1(y, yhat, C):
    f1s = []
    for c in range(C):
        tp = sum(1 for a, b in zip(y, yhat) if a == c and b == c)
        fp = sum(1 for a, b in zip(y, yhat) if a != c and b == c)
        fn = sum(1 for a, b in zip(y, yhat) if a == c and b != c)
        if tp + fp + fn == 0:
            continue
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        f1s.append(2 * p * r / (p + r) if p + r else 0)
    return statistics.fmean(f1s) if f1s else 0


def prepare(seed, a):
    rnd = random.Random(seed)
    _local_cache.clear()
    db, index, counts = build(a.C, a.n_db, a.zipf, rnd, a.reupload)
    qs = make_queries(db, a.C, a.M, rnd, a.reupload, counts)
    pats = {"band": access_patterns(qs, index, db, "band"),
            "topk": access_patterns(qs, index, db, "topk", a.topk)}
    return {"db": db, "qs": qs, "pats": pats, "counts": counts, "rnd": rnd}


def attack(data, mode, known_frac, epochs, a, seed):
    db, qs, counts = data["db"], data["qs"], data["counts"]
    pats_all = data["pats"][mode]
    rnd = random.Random(seed * 7 + int(known_frac * 1000))
    # attacker's known labels = its own uploads; it knows their pseudonyms in EVERY epoch
    known_ids = rnd.sample(range(len(db)), max(1, int(known_frac * len(db))))
    known = {i: db[i][0] for i in known_ids}
    # identifier rotation: every epoch the holder sees NEW identifiers for other
    # people's images, so it can only build a graph from one epoch's queries.
    per = max(1, len(qs) // epochs)
    y, yhat, conn_y, conn_yhat, qy, qyhat = [], [], [], [], [], []
    for e in range(epochs):
        sl = slice(e * per, (e + 1) * per if e < epochs - 1 else len(qs))
        pairs = [(p, c) for p, (c, _) in zip(pats_all[sl], qs[sl]) if p]
        pats = [p for p, _ in pairs]
        pred, qpred = sage_known_lite(pats, known, a.C)
        reached = getattr(sage_known_lite, "reached", set())
        for v, lab in pred.items():
            if v in known:
                continue
            y.append(db[v][0])
            yhat.append(lab)
            if v in reached:
                conn_y.append(db[v][0])
                conn_yhat.append(lab)
        qy += [c for _, c in pairs]
        qyhat += qpred
    acc = lambda t, p: sum(x == z for x, z in zip(t, p)) / len(t) if t else 0  # noqa: E731
    return {"record_acc": acc(y, yhat), "macro_f1": macro_f1(y, yhat, a.C), "query_acc": acc(qy, qyhat),
            "coverage": len(conn_y) / len(y) if y else 0, "acc_on_reached": acc(conn_y, conn_yhat),
            "nonempty_queries": sum(1 for p in pats_all if p) / len(pats_all),
            "majority_baseline": max(counts) / sum(counts)}


def summarise(rows):
    out = {}
    for k in rows[0]:
        vals = [r[k] for r in rows]
        out[k] = {"mean": round(statistics.fmean(vals), 4),
                  "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0}
    return out


def from_nodes(ports):
    import requests
    print("What each node (as index holder) observed:")
    for p in ports:
        log = requests.get(f"http://127.0.0.1:{p}/api/query_log").json()
        edges = set()
        for row in log:
            ids = row["returned"]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    edges.add((ids[i], ids[j]))
        print(f"  node :{p}: {len(log)} band lookups observed, "
              f"{len(set(i for r in log for i in r['returned']))} distinct pseudonyms, {len(edges)} co-retrieval edges")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--C", type=int, default=10, help="number of categories")
    ap.add_argument("--n-db", type=int, default=400)
    ap.add_argument("--M", type=int, default=1500, help="observed queries (paper: 2,000)")
    ap.add_argument("--known", type=float, default=0.05, help="fraction of known labels")
    ap.add_argument("--zipf", type=float, default=1.0)
    ap.add_argument("--reupload", type=float, default=0.5, help="fraction of queries that re-upload a stored image")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--from-nodes", default=None)
    a = ap.parse_args()
    if a.from_nodes:
        from_nodes([int(x) for x in a.from_nodes.split(",")])
        return

    results = {"config": vars(a), "paper_reference": {
        "SAGE-Known record-label accuracy (1% known labels)": "up to 84.3 %",
        "SAGE-Dist AG News record / query accuracy": "66.9 % / 68.1 %"}, "settings": {}}
    print("generating images and queries ...")
    data = [prepare(seed, a) for seed in range(a.runs)]
    for mode in ("topk", "band"):
        for known in sorted({0.01, a.known}):
            for epochs in (1, 4, 16):
                rows = [attack(d, mode, known, epochs, a, seed) for seed, d in enumerate(data)]
                s = summarise(rows)
                name = (f"{'top-%d (Paper 3 setting)' % a.topk if mode == 'topk' else 'band index (ours)'}, "
                        f"known={int(known * 100)}%, " + ("no rotation" if epochs == 1 else f"rotation x{epochs}"))
                results["settings"][name] = s
                print(f"{name:58s} rec-acc {s['record_acc']['mean']:.3f}±{s['record_acc']['std']:.3f} "
                      f"F1 {s['macro_f1']['mean']:.3f} q-acc {s['query_acc']['mean']:.3f} "
                      f"coverage {s['coverage']['mean']:.2f} acc@reached {s['acc_on_reached']['mean']:.3f} "
                      f"(majority {s['majority_baseline']['mean']:.3f})")

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "privacy.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    with open(os.path.join(HERE, "results", "privacy.md"), "w") as fh:
        fh.write("# Leakage of the near-duplicate index (Paper 3 metrics)\n\n")
        fh.write("| Setting | Record-label acc | Macro-F1 | Query-category acc | Coverage | Acc on reached | Majority baseline |\n"
                 "|---|---|---|---|---|---|---|\n")
        for name, s in results["settings"].items():
            fh.write(f"| {name} | {s['record_acc']['mean']:.3f} ± {s['record_acc']['std']:.3f} | "
                     f"{s['macro_f1']['mean']:.3f} | {s['query_acc']['mean']:.3f} | {s['coverage']['mean']:.2f} | "
                     f"{s['acc_on_reached']['mean']:.3f} | {s['majority_baseline']['mean']:.3f} |\n")
        fh.write("\nCoverage = share of observed records connected (through co-retrieval) to at least one "
                 "known label. Records that are not reached get the majority guess.\n")
        fh.write("\nPaper 3 reference: SAGE-Known up to 84.3 % record-label accuracy with 1 % known labels "
                 "on top-k encrypted vector search.\n")
    print("written: eval/results/privacy.json, privacy.md")


if __name__ == "__main__":
    main()
