"""
End-to-end viva demo. Starts 3 fresh nodes, then walks through every feature:

  1. peers discover each other (Kademlia join)
  2. text upload  -> AE chunking + replication + AI summary on the uploading node
  3. same file at another node -> network-wide FILE-level duplicate
  4. edited file  -> CHUNK-level duplicate (and why CDC beats fixed-size chunks)
  5. resized/JPEG image -> NEAR-duplicate via dHash + Hamming distance
  6. where a chunk lives (XOR-closest nodes, zone-aware)
  7. kill a node -> heartbeat timeout -> re-replication -> download still works
  8. corrupt a chunk on disk -> hash verification catches it
  9. bring the node back

    python scripts/demo.py          # pauses between steps (press Enter)
    python scripts/demo.py --auto   # no pauses

Leave it running at the end and explore the React dashboard.
"""
import argparse
import io
import os
import random
import shutil
import signal
import subprocess
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from storage import chunking  # noqa: E402

PORTS = [5001, 5002, 5003]
URL = "http://127.0.0.1:{}".format
procs = {}
AUTO = False


def step(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)
    if not AUTO:
        input("  [Enter] to run this step ... ")


def start(i):
    port = PORTS[i]
    args = [sys.executable, os.path.join(ROOT, "backend", "node.py"), "--port", str(port),
            "--name", f"node{i + 1}", "--zone", "zone-A" if i % 2 == 0 else "zone-B",
            "--data-dir", os.path.join(ROOT, "data", f"node{i + 1}-{port}")]
    if i:
        args += ["--bootstrap", f"127.0.0.1:{PORTS[0]}"]
    log = open(os.path.join(ROOT, "data", f"node{i + 1}-{port}.log"), "a")
    procs[i] = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)


def wait_up(port, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            requests.get(URL(port) + "/api/stats", timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def upload(port, name, data, uid=""):
    r = requests.post(URL(port) + "/api/upload", files={"file": (name, data)}, data={"object_uid": uid})
    r.raise_for_status()
    return r.json()


def wait_ai(port, fid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        ai = requests.get(URL(port) + f"/api/files/{fid}").json().get("ai")
        if ai and ai.get("status") == "done":
            return ai
        time.sleep(1)
    return None


def sample_text():
    random.seed(7)
    para = ("Peer-to-peer storage removes the central server. Every node stores chunks that are "
            "addressed by their SHA-256 hash, so identical data always gets the same name. "
            "A distributed hash table tells each node which peers are responsible for a key. "
            "Content-defined chunking places chunk boundaries using the bytes themselves, so an "
            "insertion only changes the chunks around the edit. Replication keeps k copies of every "
            "chunk on different nodes so that the failure of one laptop does not lose data. ")
    extra = ["Heartbeats detect failed peers within seconds.",
             "Near-duplicate images are found with a 64-bit difference hash.",
             "AI summaries are computed once and shared with every peer.",
             "Every chunk is verified against its hash when it is read."]
    body = []
    for i in range(60):
        body.append(f"Section {i + 1}. " + para + random.choice(extra))
    return "\n\n".join(body)


def sample_image(seed=3):
    rnd = random.Random(seed)
    img = Image.new("RGB", (800, 600), (135, 190, 235))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 420, 800, 600], fill=(70, 150, 80))                    # grass
    d.ellipse([600, 50, 720, 170], fill=(255, 220, 80))                     # sun
    for _ in range(6):                                                      # clouds
        x, y = rnd.randint(0, 700), rnd.randint(30, 200)
        d.ellipse([x, y, x + 140, y + 60], fill=(250, 250, 255))
    d.polygon([(200, 420), (320, 250), (440, 420)], fill=(120, 80, 60))     # house roof
    d.rectangle([230, 420, 410, 520], fill=(200, 170, 120))
    return img.filter(ImageFilter.SMOOTH)


def main():
    global AUTO
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true")
    AUTO = ap.parse_args().auto

    if os.path.isdir(os.path.join(ROOT, "data")):
        shutil.rmtree(os.path.join(ROOT, "data"))
    os.makedirs(os.path.join(ROOT, "data"))

    def cleanup(*_):
        for p in procs.values():
            p.terminate()
        sys.exit(0)
    signal.signal(signal.SIGINT, cleanup)

    # ------------------------------------------------------------------ 1
    step("STEP 1  Start 3 nodes; node2/node3 bootstrap from node1 (Kademlia join)")
    for i in range(3):
        start(i)
        wait_up(PORTS[i])
    time.sleep(3)
    for port in PORTS:
        d = requests.get(URL(port) + "/api/peers").json()
        print(f"  {d['self']['name']} id={d['self']['id'][:12]}...  knows: " +
              ", ".join(f"{p['name']}({p['zone']}, bucket {p['bucket']})" for p in d["peers"]))

    # ------------------------------------------------------------------ 2
    step("STEP 2  Upload a text file at node1 -> AE chunking, replication (k=2), AI summary")
    text = sample_text().encode()
    r1 = upload(5001, "p2p_notes.txt", text, uid="notes")
    print(f"  file_id (content-derived) = {r1['file_id'][:16]}...")
    print(f"  chunks: {r1['chunks_total']} total, {r1['chunks_new']} new; {r1['message']}")
    ai = wait_ai(5001, r1["file_id"])
    print(f"  AI ({ai.get('model')}) computed by {ai.get('computed_by')}:\n    {ai.get('summary', '')[:300]}")

    # ------------------------------------------------------------------ 3
    step("STEP 3  Upload the SAME file at node3 -> exact duplicate found through the DHT")
    r2 = upload(5003, "copy_of_notes.txt", text)
    print(f"  duplicate = {r2['duplicate']!r}; {r2['message']}")
    print(f"  same file_id? {r2['file_id'] == r1['file_id']}; AI reused: {bool(r2.get('ai'))}")

    # ------------------------------------------------------------------ 4
    step("STEP 4  Upload an EDITED version at node2 -> chunk-level dedup (Paper 2: CDC vs FSC)")
    edited = text[:5000] + b"A NEW SENTENCE INSERTED BY THE STUDENT. " + text[5000:]
    r3 = upload(5002, "p2p_notes_v2.txt", edited, uid="notes")
    print(f"  {r3['message']}  (new chunks: {r3['chunks_new']})")
    for alg in ("fsc", "ae"):
        a = set(chunking.split(text, alg, 4096))
        b = chunking.split(edited, alg, 4096)
        reused = sum(1 for c in b if c in a)
        print(f"  {alg.upper():4s}: {reused}/{len(b)} chunks of v2 reused from v1")
    print("  -> fixed-size chunks all shift after the insertion; AE boundaries re-synchronise.")
    versions = requests.get(URL(5001) + "/api/objects/notes").json()
    print(f"  object 'notes' has {len(versions)} content-derived versions (Paper 1 lineage)")

    # ------------------------------------------------------------------ 5
    step("STEP 5  Image at node1, then a resized + JPEG-compressed copy at node2 -> near-duplicate")
    img = sample_image()
    b = io.BytesIO()
    img.save(b, "PNG")
    p1 = upload(5001, "house.png", b.getvalue())
    small = img.resize((400, 300))
    b2 = io.BytesIO()
    small.save(b2, "JPEG", quality=60)
    p2 = upload(5002, "house_small.jpg", b2.getvalue())
    print(f"  dHash original={p1.get('dhash')}  copy={p2.get('dhash')}")
    for nd in p2["near_duplicates"]:
        print(f"  NEAR-DUPLICATE of {nd['name']} (owner {nd['owner']}), Hamming={nd['hamming']}, "
              f"similarity={nd['similarity']}")
    other = sample_image(seed=99).rotate(180)
    b3 = io.BytesIO()
    other.save(b3, "PNG")
    p3 = upload(5003, "different.png", b3.getvalue())
    print(f"  unrelated image near-duplicates: {p3['near_duplicates'] or 'none'}")
    cap = wait_ai(5002, p2["file_id"])
    print(f"  caption ({cap.get('model')}): {cap.get('caption')}  reliable={cap.get('reliable')}")

    # ------------------------------------------------------------------ 6
    step("STEP 6  Where does a chunk live? (XOR-closest nodes, preferring different zones)")
    man = requests.get(URL(5001) + f"/api/files/{r1['file_id']}").json()
    h = man["manifest"]["chunks"][0]["hash"]
    w = requests.get(URL(5001) + f"/api/dht/whereis/prov:{h}").json()
    print(f"  chunk {h[:16]}... responsible: " + ", ".join(f"{p['name']}({p['zone']})" for p in w["responsible"]))
    print(f"  replication health: {man['replication']}")

    # ------------------------------------------------------------------ 7
    step("STEP 7  Kill node2 -> heartbeats time out -> re-replication -> download still works")
    procs[1].terminate()
    procs[1].wait()
    print("  node2 stopped. Waiting ~25 s for detection + repair ...")
    time.sleep(25)
    for port in (5001, 5003):
        print(f"  {port} health: {requests.get(URL(port) + '/api/health').json()}")
    t0 = time.time()
    r = requests.get(URL(5003) + f"/api/download/{r3['file_id']}")
    dt = time.time() - t0
    print(f"  download of v2 from node3: HTTP {r.status_code}, correct={r.content == edited}, "
          f"R_logical = S/t = {len(edited) / dt / 1e6:.2f} MB/s (Paper 1 metric)")

    # ------------------------------------------------------------------ 8
    step("STEP 8  Corrupt a chunk on node1's disk -> hash verification refuses it")
    blocks = os.path.join(ROOT, "data", "node1-5001", "blocks")
    victim = None
    for dp, _, files in os.walk(blocks):
        for f in files:
            if f in {c["hash"] for c in man["manifest"]["chunks"]}:
                victim = os.path.join(dp, f)
                break
        if victim:
            break
    if victim:
        with open(victim, "r+b") as fh:
            fh.write(b"XXXX")
        print(f"  overwrote 4 bytes of {os.path.basename(victim)[:16]}...")
        r = requests.get(URL(5001) + f"/api/download/{r1['file_id']}")
        print(f"  download from node1: HTTP {r.status_code}, correct={r.content == text} "
              f"(bad local copy ignored, good replica fetched from a peer)")

    # ------------------------------------------------------------------ 9
    step("STEP 9  Restart node2 -> it rejoins and its chunks count again")
    start(1)
    wait_up(5002)
    time.sleep(6)
    print("  " + ", ".join(f"{p['name']}:{'up' if p['alive'] else 'down'}"
                           for p in requests.get(URL(5001) + "/api/peers").json()["peers"]))
    print("\nDemo finished. Nodes keep running - open the React dashboard. Ctrl+C to stop.")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
