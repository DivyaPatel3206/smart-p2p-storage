"""
Evaluation 4 — quality of the AI metadata (Paper 4 metrics + ROUGE for summaries).

Paper 4 (Lin et al., "Can Vision-Language Models Truly Understand Images?",
arXiv:2611.22360) evaluates VLM text with ROUGE-1/2/L and METEOR, and proposes
Contra-Acc: for each image, a correctness vector over several question
dimensions; the image only scores as well as its WORST dimension.
They also show that accuracy collapses on tiny images (8.68 % at 64x64).

This script measures, for OUR captioner (BLIP, or the fallback):
  A. captions   : ROUGE-1/2/L + METEOR vs reference captions
  B. Contra-Acc : 6 dimensions (shape, colour, count, background, position, size).
                  Default: "caption-grounded" - a dimension is correct if the caption
                  states the right value. With --vqa and transformers installed it
                  asks BLIP-VQA (Salesforce/blip-vqa-base) the 6 questions instead.
  C. resolution : the same images at 64x64 (Paper 4's stress test)
  D. summaries  : ROUGE-1/2/L of the text summariser vs reference summaries

    python eval/eval_ai.py                      # synthetic images with known ground truth
    python eval/eval_ai.py --images my_imgs --captions my_imgs/captions.json
        (captions.json = {"file.jpg": ["reference caption", ...], ...})
"""
import argparse
import json
import os
import random
import statistics
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))

from ai import engine  # noqa: E402
from metrics.text_metrics import best_over_refs, contra_acc, meteor, rouge_l, rouge_n  # noqa: E402

COLORS = {"red": (220, 30, 30), "green": (30, 170, 60), "blue": (30, 70, 220), "yellow": (240, 210, 30)}
BGS = {"white": (250, 250, 250), "black": (15, 15, 15), "gray": (128, 128, 128)}
NUM = {1: "one", 2: "two", 3: "three"}


def synth(i: int):
    """Image with 6 known attributes + its reference caption."""
    rnd = random.Random(i)
    shape = rnd.choice(["circle", "square", "triangle"])
    color = rnd.choice(list(COLORS))
    count = rnd.randint(1, 3)
    bg = rnd.choice(list(BGS))
    pos = rnd.choice(["left", "center", "right"])
    size = rnd.choice(["small", "large"])
    img = Image.new("RGB", (384, 384), BGS[bg])
    d = ImageDraw.Draw(img)
    r = 28 if size == "small" else 60
    cx = {"left": 90, "center": 192, "right": 294}[pos]
    for k in range(count):
        cy = 192 + (k - (count - 1) / 2) * (2.3 * r)
        box = [cx - r, cy - r, cx + r, cy + r]
        if shape == "circle":
            d.ellipse(box, fill=COLORS[color])
        elif shape == "square":
            d.rectangle(box, fill=COLORS[color])
        else:
            d.polygon([(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)], fill=COLORS[color])
    plural = shape + ("s" if count > 1 else "")
    ref = f"{NUM[count]} {size} {color} {plural} on the {pos} of a {bg} background"
    attrs = {"shape": shape, "color": color, "count": count, "background": bg, "position": pos, "size": size}
    return img, [ref, f"a picture of {NUM[count]} {color} {plural} on a {bg} background"], attrs


QUESTIONS = {
    "shape": "what shape is shown?", "color": "what color are the shapes?",
    "count": "how many shapes are there?", "background": "what color is the background?",
    "position": "are the shapes on the left, center or right?", "size": "are the shapes small or large?",
}


def dimension_correct(dim, truth, text: str) -> float:
    t = text.lower()
    if dim == "count":
        return float(NUM[truth] in t.split() or str(truth) in t.split()
                     or (truth == 1 and (" a " in f" {t} " or "single" in t)))
    if dim == "background":
        return float(truth in t and ("background" in t or "on a" in t or "on " in t))
    if dim == "position" and truth == "center":
        return float("center" in t or "middle" in t)
    if dim == "shape":
        syn = {"circle": ["circle", "ball", "dot", "round"], "square": ["square", "block", "box"],
               "triangle": ["triangle", "pyramid"]}
        return float(any(s in t for s in syn[truth]))
    return float(str(truth) in t)


def vqa_answers(img, questions):
    from transformers import BlipForQuestionAnswering, BlipProcessor
    if "vqa" not in engine._models:
        name = "Salesforce/blip-vqa-base"
        engine._models["vqa"] = (BlipProcessor.from_pretrained(name), BlipForQuestionAnswering.from_pretrained(name))
    proc, model = engine._models["vqa"]
    out = {}
    for dim, q in questions.items():
        inputs = proc(img.convert("RGB"), q, return_tensors="pt")
        out[dim] = proc.decode(model.generate(**inputs, max_new_tokens=10)[0], skip_special_tokens=True)
    return out


def evaluate_captions(samples, use_vqa):
    rows = {"full": [], "64x64": []}
    contra = {"full": [], "64x64": []}
    per_dim = {"full": {}, "64x64": {}}
    examples = []
    for img, refs, attrs in samples:
        for res_name, im in (("full", img), ("64x64", img.resize((64, 64)).resize(img.size))):
            cap, conf, model = engine.caption(im)
            rows[res_name].append({
                "rouge1": best_over_refs(lambda c, r: rouge_n(c, r, 1), cap, refs),
                "rouge2": best_over_refs(lambda c, r: rouge_n(c, r, 2), cap, refs),
                "rougeL": best_over_refs(rouge_l, cap, refs),
                "meteor": best_over_refs(meteor, cap, refs)})
            if attrs:
                answers = vqa_answers(im, QUESTIONS) if use_vqa else {d: cap for d in QUESTIONS}
                vec = [dimension_correct(d, attrs[d], answers[d]) for d in QUESTIONS]
                contra[res_name].append(vec)
                for d, v in zip(QUESTIONS, vec):
                    per_dim[res_name].setdefault(d, []).append(v)
            if res_name == "full" and len(examples) < 5:
                examples.append({"reference": refs[0], "caption": cap, "confidence": conf})
    out = {"model": model, "examples": examples}
    for res_name in rows:
        agg = {k: round(statistics.fmean(r[k] for r in rows[res_name]), 4) for k in rows[res_name][0]}
        if contra[res_name]:
            agg["contra_acc"] = round(contra_acc(contra[res_name]), 4)
            agg["mean_accuracy"] = round(statistics.fmean(v for vec in contra[res_name] for v in vec), 4)
            agg["per_dimension"] = {d: round(statistics.fmean(v), 3) for d, v in per_dim[res_name].items()}
        out[res_name] = agg
    return out


SUMMARY_SET = [
    ("Peer-to-peer storage systems remove the need for a central server. Each participating computer "
     "contributes disk space and bandwidth, and files are split into chunks that are spread across many "
     "machines. Because every chunk is named by a cryptographic hash, any node can check that the data it "
     "receives has not been modified. Replication keeps several copies of every chunk so that the network "
     "survives when individual machines go offline. The main challenges are finding data quickly, keeping "
     "enough copies alive, and avoiding wasted space when many users store the same files.",
     ["Peer-to-peer storage splits files into hash-named chunks spread over many computers, uses replication "
      "to survive failures, and must solve lookup, availability and duplicate-data problems."]),
    ("Deduplication saves storage by keeping only one copy of repeated data. Systems first cut files into "
     "chunks, compute a fingerprint for each chunk and store only chunks whose fingerprint has not been seen "
     "before. Fixed-size chunking is fast but a single inserted byte shifts every later boundary, so almost "
     "nothing matches afterwards. Content-defined chunking chooses boundaries from the data itself, so the "
     "boundaries re-synchronise after an edit and most chunks are still recognised as duplicates.",
     ["Deduplication stores repeated chunks once; content-defined chunking survives insertions much better "
      "than fixed-size chunking because boundaries depend on the data."]),
    ("Image captioning models such as BLIP describe a picture in a short sentence. They are trained on "
     "millions of image and text pairs collected from the web. Recent studies show that these models often "
     "rely on common patterns from their training data instead of looking carefully at the picture, and "
     "their accuracy falls sharply when images are small or show unusual scenes. Captions should therefore "
     "be treated as helpful hints rather than verified facts.",
     ["Captioning models like BLIP learn from web image-text pairs but can rely on training patterns and fail "
      "on small or unusual images, so captions are hints, not facts."]),
]


def evaluate_summaries():
    rows = []
    for text, refs in SUMMARY_SET:
        s = engine.summarize(text)
        rows.append({"rouge1": best_over_refs(lambda c, r: rouge_n(c, r, 1), s["summary"], refs),
                     "rouge2": best_over_refs(lambda c, r: rouge_n(c, r, 2), s["summary"], refs),
                     "rougeL": best_over_refs(rouge_l, s["summary"], refs), "model": s["model"],
                     "summary": s["summary"]})
    return {"model": rows[0]["model"],
            **{k: round(statistics.fmean(r[k] for r in rows), 4) for k in ("rouge1", "rouge2", "rougeL")},
            "examples": [r["summary"] for r in rows]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--images", default=None)
    ap.add_argument("--captions", default=None)
    ap.add_argument("--vqa", action="store_true", help="use BLIP-VQA for Contra-Acc (needs transformers)")
    a = ap.parse_args()

    if a.images:
        refs = json.load(open(a.captions))
        samples = [(Image.open(os.path.join(a.images, fn)).convert("RGB"), r, None) for fn, r in refs.items()]
    else:
        samples = [synth(i) for i in range(a.n)]
    use_vqa = a.vqa and engine.transformers_available()
    print(f"captioning {len(samples)} images with backend: "
          f"{'transformers' if engine.transformers_available() else 'fallback'}; Contra-Acc via "
          f"{'BLIP-VQA' if use_vqa else 'caption-grounded answers'}")
    res = {"captions": evaluate_captions(samples, use_vqa), "summaries": evaluate_summaries(),
           "contra_acc_mode": "blip-vqa" if use_vqa else "caption-grounded",
           "paper_reference": {"strongest closed-source MLLM Contra-Acc": "~60 %", "humans": "96.04 %",
                               "open-source MLLMs": "35-37 %", "at 64x64 resolution": "8.68 %"}}
    print(json.dumps({k: v for k, v in res["captions"].items() if k != "examples"}, indent=1))
    print("summaries:", {k: v for k, v in res["summaries"].items() if k != "examples"})

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "ai.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    c = res["captions"]
    with open(os.path.join(HERE, "results", "ai.md"), "w") as fh:
        fh.write(f"# AI metadata quality (Paper 4 metrics)\n\nCaption model: `{c['model']}`, "
                 f"Contra-Acc mode: {res['contra_acc_mode']}\n\n")
        fh.write("| Resolution | ROUGE-1 | ROUGE-2 | ROUGE-L | METEOR* | Contra-Acc | Mean acc |\n|---|---|---|---|---|---|---|\n")
        for r in ("full", "64x64"):
            fh.write(f"| {r} | {c[r]['rouge1']} | {c[r]['rouge2']} | {c[r]['rougeL']} | {c[r]['meteor']} | "
                     f"{c[r].get('contra_acc', '-')} | {c[r].get('mean_accuracy', '-')} |\n")
        s = res["summaries"]
        fh.write(f"\nSummariser `{s['model']}`: ROUGE-1 {s['rouge1']}, ROUGE-2 {s['rouge2']}, ROUGE-L {s['rougeL']}\n")
        fh.write("\n*METEOR simplified: exact matches only (no stemming/synonyms).\n"
                 "\nPaper 4 reference: strongest closed-source model ≈60 % Contra-Acc, humans 96.04 %, "
                 "8.68 % at 64×64.\n")
    print("written: eval/results/ai.json, ai.md")


if __name__ == "__main__":
    main()
