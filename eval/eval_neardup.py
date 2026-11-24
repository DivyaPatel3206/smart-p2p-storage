"""
Evaluation 2 — near-duplicate image detection (dHash + Hamming threshold + LSH bands).

For N base images and every transformation (resize, JPEG, crop, brightness,
blur, rotation, flip) we measure:
  * mean Hamming distance between original and transformed copy
  * recall@T          : fraction of copies with distance <= T
  * band-recall@T     : fraction found by the DHT lookup (>= 1 identical band AND
                        distance <= T)  -> the price of making it work on a DHT
  * false-positive rate: fraction of pairs of DIFFERENT images with distance <= T

    python eval/eval_neardup.py               # synthetic images
    python eval/eval_neardup.py --dir photos  # your own photos
"""
import argparse
import itertools
import json
import os
import random
import statistics
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))
sys.path.insert(0, HERE)

import images  # noqa: E402
from dedup import dhash as dh  # noqa: E402


def load_bases(a):
    if a.dir:
        out = []
        for fn in sorted(os.listdir(a.dir)):
            try:
                out.append(Image.open(os.path.join(a.dir, fn)).convert("RGB"))
            except Exception:
                pass
        return out[: a.n]
    return [images.base_image(cat=i % 40, idx=i) for i in range(a.n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--thresholds", default="4,6,8,10,12,16")
    a = ap.parse_args()
    thresholds = [int(x) for x in a.thresholds.split(",")]

    bases = load_bases(a)
    hashes = [dh.dhash(im) for im in bases]
    res = {"n_images": len(bases), "thresholds": thresholds, "transforms": {}}
    for name, fn in images.TRANSFORMS.items():
        dists, band_hit = [], []
        for im, h in zip(bases, hashes):
            h2 = dh.dhash(fn(im))
            dists.append(dh.hamming(h, h2))
            band_hit.append(any(x == y for x, y in zip(dh.bands(h), dh.bands(h2))))
        row = {"mean_hamming": round(statistics.fmean(dists), 2)}
        for t in thresholds:
            row[f"recall@{t}"] = round(sum(d <= t for d in dists) / len(dists), 3)
            row[f"band_recall@{t}"] = round(sum(d <= t and b for d, b in zip(dists, band_hit)) / len(dists), 3)
        res["transforms"][name] = row
        print(f"{name:15s} mean Hamming {row['mean_hamming']:5.2f}  recall@10 {row.get('recall@10')}  "
              f"band_recall@10 {row.get('band_recall@10')}")

    rnd = random.Random(0)
    pairs = list(itertools.combinations(range(len(hashes)), 2))
    pairs = rnd.sample(pairs, min(20000, len(pairs)))
    fp = {}
    for t in thresholds:
        fp[str(t)] = round(sum(dh.hamming(hashes[i], hashes[j]) <= t for i, j in pairs) / len(pairs), 4)
    res["false_positive_rate"] = fp
    print("false-positive rate (different images):", fp)

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "neardup.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    with open(os.path.join(HERE, "results", "neardup.md"), "w") as fh:
        fh.write("# Near-duplicate detection (dHash, 64 bit, 4 bands)\n\n")
        fh.write("| Transform | mean Hamming | " + " | ".join(f"recall@{t} / band@{t}" for t in thresholds) + " |\n")
        fh.write("|---|---|" + "---|" * len(thresholds) + "\n")
        for name, row in res["transforms"].items():
            fh.write(f"| {name} | {row['mean_hamming']} | " + " | ".join(
                f"{row[f'recall@{t}']} / {row[f'band_recall@{t}']}" for t in thresholds) + " |\n")
        fh.write(f"\nFalse-positive rate on pairs of different images: {fp}\n")
    print("written: eval/results/neardup.json, neardup.md")


if __name__ == "__main__":
    main()
