"""
Create a few sample files in samples/ and upload them to different nodes, so the
dashboard has something to show. Nodes must be running (scripts/run_nodes.py).

    python scripts/seed_samples.py
"""
import io
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from demo import sample_image, sample_text  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")


def save(name, data):
    os.makedirs(SAMPLES, exist_ok=True)
    with open(os.path.join(SAMPLES, name), "wb") as fh:
        fh.write(data)
    return data


def up(port, name, data, uid=""):
    r = requests.post(f"http://127.0.0.1:{port}/api/upload", files={"file": (name, data)},
                      data={"object_uid": uid}, timeout=120)
    r.raise_for_status()
    j = r.json()
    print(f"  :{port} {name:28s} -> {j['duplicate']:6s} {j.get('message', '')[:70]}")
    return j


def png(img, fmt="PNG", **kw):
    b = io.BytesIO()
    img.save(b, fmt, **kw)
    return b.getvalue()


def main():
    text = sample_text().encode()
    v2 = text[:6000] + b"\n\nNEW PARAGRAPH: version two adds a section on convergent encryption. " + text[6000:]
    notes = (b"Meeting notes. The team agreed to use AE content-defined chunking with a target of 4 KiB. "
             b"Replication factor k is two, and replicas must be placed in different zones when possible. "
             b"Near-duplicate images are detected with a 64-bit dHash and a Hamming threshold of ten. "
             b"Captions are stored with a confidence value and are never treated as verified facts.")
    house = sample_image(3)
    other = sample_image(42).rotate(180)
    tiny = sample_image(7).resize((96, 72))

    up(5001, "p2p_report.txt", save("p2p_report.txt", text), uid="report")
    up(5002, "p2p_report_v2.txt", save("p2p_report_v2.txt", v2), uid="report")
    up(5003, "p2p_report_copy.txt", text)
    up(5002, "meeting_notes.md", save("meeting_notes.md", notes))
    up(5001, "house.png", save("house.png", png(house)))
    up(5003, "house_small.jpg", save("house_small.jpg", png(house.resize((400, 300)), "JPEG", quality=60)))
    up(5002, "landscape.png", save("landscape.png", png(other)))
    up(5003, "thumbnail.png", save("thumbnail.png", png(tiny)))
    print(f"sample files saved in {SAMPLES}")


if __name__ == "__main__":
    main()
