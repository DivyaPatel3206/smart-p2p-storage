"""
AI content understanding — runs ONLY on the node where the file is uploaded.
The result is stored in the DHT under "ai:<file_id>" so every other peer can
read it without re-running the model ("compute once, share everywhere").

Models (loaded lazily, first call takes a while):
  * text  -> sshleifer/distilbart-cnn-12-6  (DistilBART, Shleifer & Rush 2020)
  * image -> Salesforce/blip-image-captioning-base  (BLIP, Li et al. 2022)

If `transformers`/`torch` are not installed, simple fallbacks are used and the
result is clearly labelled  model = "fallback-...".  The rest of the system
works the same way, so you can demo without downloading 1.5 GB of models.

From Paper 4 (ContraSense, Lin et al. 2026):
  * VLM outputs can be confidently wrong and collapse at low resolution
    (Contra-Acc fell to 8.68 % at 64x64). So every caption is stored with
      - confidence  (geometric-mean token probability from BLIP)
      - reliable    (False if the image is smaller than min_caption_side px
                     or confidence is low)
      - verified = False  (captions are shared metadata, NOT ground truth)
"""
import collections
import io
import math
import re
import threading

from PIL import Image

_lock = threading.Lock()
_models = {}


def transformers_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- text
TEXT_EXT = (".txt", ".md", ".py", ".csv", ".json", ".html", ".log", ".tex", ".js", ".java", ".c")


def extract_text(name: str, data: bytes) -> str:
    low = name.lower()
    if low.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages[:20])
        except Exception:
            return ""
    if low.endswith(TEXT_EXT):
        return data.decode("utf-8", errors="ignore")
    return ""


def _fallback_summary(text: str, n_sentences: int = 3) -> str:
    """Extractive fallback: pick the sentences with the most frequent words."""
    sentences = list(dict.fromkeys(                       # keep order, drop repeated sentences
        s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) > 4))
    if not sentences:
        return text[:300]
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    freq = collections.Counter(words)
    scored = sorted(sentences,
                    key=lambda s: -sum(freq[w] for w in re.findall(r"[a-zA-Z]{4,}", s.lower()))
                    / (len(s.split()) + 5))
    top = set(scored[:n_sentences])
    return " ".join(s for s in sentences if s in top)


def summarize(text: str) -> dict:
    text = text.strip()
    if not text:
        return {"summary": "", "model": "none"}
    if transformers_available():
        with _lock:
            if "sum" not in _models:
                from transformers import pipeline
                _models["sum"] = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
            pipe = _models["sum"]
        # DistilBART handles ~1024 tokens; summarise the first ~700 words
        words = text.split()
        snippet = " ".join(words[:700])
        out = pipe(snippet, max_length=130, min_length=min(30, max(5, len(words) // 4)),
                   do_sample=False, truncation=True)
        return {"summary": out[0]["summary_text"].strip(), "model": "sshleifer/distilbart-cnn-12-6"}
    return {"summary": _fallback_summary(text), "model": "fallback-extractive"}


# ---------------------------------------------------------------- images
PALETTE = {"red": (220, 40, 40), "green": (40, 160, 70), "blue": (40, 90, 220), "yellow": (240, 210, 40),
           "orange": (240, 140, 30), "purple": (130, 60, 170), "white": (245, 245, 245),
           "black": (15, 15, 15), "gray": (128, 128, 128), "brown": (130, 90, 50), "sky-blue": (135, 190, 235)}


def _nearest_colour(rgb):
    return min(PALETTE, key=lambda n: sum((a - b) ** 2 for a, b in zip(rgb, PALETTE[n])))


def _fallback_caption(img: Image.Image) -> tuple:
    """No neural model installed: describe the two most common colours.
    Clearly labelled as a heuristic and never marked reliable."""
    small = img.convert("RGB").resize((48, 48))
    counts = collections.Counter(_nearest_colour(px) for px in small.getdata())
    top = [c for c, _ in counts.most_common(2)]
    orient = "landscape" if img.width > img.height else "portrait" if img.height > img.width else "1:1"
    text = f"a {orient} image, mostly {top[0]}" + (f" with {top[1]} areas" if len(top) > 1 else "")
    return text, None


def caption(img: Image.Image) -> tuple:
    """Returns (caption, confidence or None, model_name)."""
    if transformers_available():
        with _lock:
            if "cap" not in _models:
                from transformers import BlipForConditionalGeneration, BlipProcessor
                name = "Salesforce/blip-image-captioning-base"
                _models["cap"] = (BlipProcessor.from_pretrained(name),
                                  BlipForConditionalGeneration.from_pretrained(name))
            proc, model = _models["cap"]
        import torch
        inputs = proc(images=img.convert("RGB"), return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=30, num_beams=1,
                                 output_scores=True, return_dict_in_generate=True)
        seq = out.sequences[0] if hasattr(out, "sequences") else out[0]
        text = proc.decode(seq, skip_special_tokens=True).strip()
        conf = None
        try:
            # confidence = geometric mean of the probability of each generated token
            steps = out.scores                       # one logits tensor per generated token
            gen_tokens = seq[-len(steps):]
            logp = [torch.log_softmax(s[0], dim=-1)[t].item() for s, t in zip(steps, gen_tokens)]
            if logp:
                conf = round(math.exp(sum(logp) / len(logp)), 3)
        except Exception:
            conf = None
        return text, conf, "Salesforce/blip-image-captioning-base"
    text, conf = _fallback_caption(img)
    return text, conf, "fallback-colour-heuristic"


def analyse(name: str, data: bytes, mime: str, min_caption_side: int = 128) -> dict:
    """Run the right model for this file type. Returns the AI metadata record."""
    if mime.startswith("image/"):
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:
            return {"kind": "image", "error": "cannot decode image"}
        text, conf, model = caption(img)
        too_small = min(img.width, img.height) < min_caption_side
        low_conf = conf is not None and conf < 0.25
        fallback = model.startswith("fallback")
        note = ("image smaller than %d px: captions degrade sharply at low resolution (Paper 4)"
                % min_caption_side if too_small else "low model confidence" if low_conf else
                "heuristic fallback - install torch + transformers for BLIP" if fallback else "")
        return {
            "kind": "image", "caption": text, "confidence": conf, "model": model,
            "reliable": not (too_small or low_conf or fallback),
            "reliability_note": note,
            "verified": False,
            "width": img.width, "height": img.height,
        }
    text = extract_text(name, data)
    if text.strip():
        res = summarize(text)
        res.update({"kind": "text", "words": len(text.split()), "verified": False})
        return res
    return {"kind": "binary", "note": "no AI model for this file type"}
