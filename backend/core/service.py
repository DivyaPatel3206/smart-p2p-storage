"""
The "brain" of a node: upload pipeline, download, deduplication, near-duplicate
search, AI jobs and background maintenance (heartbeats, re-replication,
republishing, integrity scrubbing, telemetry).

DHT key layout (everything is content addressed):
  file:<file_id>        manifest of a file                       (set)
  fixity:<sha256>       whole-file SHA-256 -> file_id            (set)  exact file-level dedup
  prov:<chunk_hash>     which nodes hold this chunk              (add)  chunk-level dedup + routing
  band:<i>:<16 bits>    near-duplicate index entries (pseudonyms)(add)
  ai:<file_id>          summary / caption shared with peers      (set)
  obj:<object_uid>      versions of one logical object (Paper 1) (add)
"""
import concurrent.futures
import hashlib
import io
import json
import mimetypes
import random
import statistics
import threading
import time

from ai import engine as ai_engine
from dedup import dhash as dh
from p2p import framing, security
from p2p.dht import node_id_for
from storage import chunking


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class NodeService:
    def __init__(self, cfg, store, dht):
        self.cfg = cfg
        self.store = store
        self.dht = dht
        self.ai_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.stop = threading.Event()
        self.started_at = time.time()

    # =================================================================== upload
    def upload(self, name: str, data: bytes, object_uid: str = "") -> dict:
        t0 = time.time()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        fixity = sha256(data)                               # independent whole-file digest (Paper 1)
        report = {"name": name, "size": len(data), "mime": mime, "fixity": fixity}

        # ---- 1. file-level exact duplicate anywhere in the network?
        existing = self.dht.get(f"fixity:{fixity}")
        if existing:
            fid = existing["file_id"]
            manifest = self.dht.get(f"file:{fid}")
            n_chunks = len(manifest["chunks"]) if manifest else None
            n_unique = len({c["hash"] for c in manifest["chunks"]}) if manifest else None
            report.update({"file_id": fid, "duplicate": "file", "stored_bytes_including_replicas": 0,
                           "chunks_total": n_chunks, "chunks_unique_in_file": n_unique,
                           "chunks_already_in_network": n_unique, "chunks_new": 0,
                           "message": "Exact duplicate: this file already exists in the network. "
                                      "Nothing stored, AI result reused."})
            self._record_upload(fid, name, len(data), mime, fixity, object_uid)
            if object_uid:
                self._link_object(object_uid, fid)
            report["near_duplicates"] = []
            if manifest and manifest.get("dhash"):          # also show visually similar images
                report["dhash"] = manifest["dhash"]
                report["near_duplicates"] = self.find_near_duplicates(int(manifest["dhash"], 16), exclude=fid)
            report["ai"] = self.dht.get(f"ai:{fid}")
            report["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
            self.store.log_event("dedup", f"{name}: file-level duplicate of {fid[:12]}")
            return report

        # ---- 2. content-defined chunking (Paper 2: AE with corrected horizon)
        tc = time.time()
        pieces = chunking.split(data, self.cfg.chunker, self.cfg.target_chunk_size)
        chunk_ms = (time.time() - tc) * 1000

        chunk_records, stored_payloads, keys_wrapped = [], [], []
        for p in pieces:
            if self.cfg.encrypt:
                ct, key = security.ce_encrypt(p)          # convergent: same chunk -> same ciphertext
                h = sha256(ct)
                stored_payloads.append((h, ct))
                keys_wrapped.append(security.wrap_key(self.cfg.swarm_key, key))
            else:
                h = sha256(p)
                stored_payloads.append((h, p))
            chunk_records.append({"hash": h, "size": len(p)})

        # ---- 3. chunk-level dedup: ask the DHT who already has each chunk
        unique = {}
        for h, payload in stored_payloads:
            unique.setdefault(h, payload)
        prov = self.dht.get_many([f"prov:{h}" for h in unique])
        alive = {p.address for p in self.dht.alive_peers()} | {self.cfg.address}
        new_chunks, dup_chunks = {}, 0
        for h, payload in unique.items():
            holders = [e["node"] for e in (prov.get(f"prov:{h}") or {}).get("entries", {}).values()
                       if e["node"] in alive]
            if holders:
                dup_chunks += 1
            else:
                new_chunks[h] = payload
        intra_file_dups = len(stored_payloads) - len(unique)

        # ---- 4. store + replicate new chunks to the k responsible nodes
        stored_bytes = self.replicate_chunks(new_chunks)

        # ---- 5. manifest => content-derived file identity (Paper 1, like an IPFS root CID)
        manifest = {
            "name": name, "size": len(data), "mime": mime,
            "chunks": chunk_records,
            "chunker": chunking.chunker_params(self.cfg.chunker, self.cfg.target_chunk_size),
            "fixity_sha256": fixity,
            "encrypted": self.cfg.encrypt,
        }
        if self.cfg.encrypt:
            manifest["wrapped_keys"] = keys_wrapped
        # The ID covers content + chunking parameters, not the name or the time:
        identity = {k: manifest[k] for k in ("chunks", "chunker", "fixity_sha256", "encrypted")}
        fid = sha256(json.dumps(identity, sort_keys=True).encode())
        manifest["file_id"] = fid
        manifest["origin"] = self.cfg.address
        manifest["uploaded_at"] = time.time()
        if object_uid:
            manifest["object_uid"] = object_uid

        self.dht.store_many([
            (f"file:{fid}", manifest, "set"),
            (f"fixity:{fixity}", {"file_id": fid}, "set"),
        ])
        self._record_upload(fid, name, len(data), mime, fixity, object_uid)
        if object_uid:
            self._link_object(object_uid, fid)

        report.update({
            "file_id": fid, "duplicate": "chunks" if dup_chunks else "none",
            "chunks_total": len(pieces), "chunks_unique_in_file": len(unique),
            "chunks_already_in_network": dup_chunks, "chunks_new": len(new_chunks),
            "intra_file_duplicate_chunks": intra_file_dups,
            "stored_bytes_including_replicas": stored_bytes,
            "chunking_ms": round(chunk_ms, 1),
            "message": (f"{dup_chunks} of {len(unique)} unique chunks already existed in the network "
                        f"(chunk-level dedup)." if dup_chunks else "New content stored and replicated."),
        })

        # ---- 6. near-duplicate image detection
        report["near_duplicates"] = []
        if mime.startswith("image/"):
            try:
                h64 = dh.dhash_file(io.BytesIO(data))
                report["dhash"] = dh.to_hex(h64)
                report["near_duplicates"] = self.find_near_duplicates(h64, exclude=fid)
                self.publish_dhash(fid, h64)
                manifest["dhash"] = dh.to_hex(h64)
                self.dht.store(f"file:{fid}", manifest)
            except Exception as e:
                report["near_dup_error"] = str(e)

        # ---- 7. AI on THIS node only, asynchronously; result shared via DHT
        report["ai"] = {"status": "pending"} if self.cfg.enable_ai else {"status": "disabled"}
        if self.cfg.enable_ai:
            self.ai_pool.submit(self._run_ai, fid, name, data, mime)

        report["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        self.store.log_event("upload", f"{name}: {len(new_chunks)} new / {dup_chunks} dup chunks")
        return report

    def _record_upload(self, fid, name, size, mime, fixity, object_uid):
        # one row per upload, so repeated uploads of the same file are counted as duplicates
        try:
            self.store.x("INSERT INTO uploads VALUES(?,?,?,?,?,?,?)",
                         (fid, name, size, mime, fixity, object_uid or "", time.time()))
        except Exception:      # old database from an earlier version (file_id was a primary key)
            pass

    def _link_object(self, object_uid, fid):
        """Paper 1: a stable object UID (like a museum UID) points to every
        content-derived version (failed, repeated, accepted states stay distinct)."""
        self.dht.store(f"obj:{object_uid}", {"id": fid, "file_id": fid, "ts": time.time()}, "add")

    def _run_ai(self, fid, name, data, mime):
        try:
            res = ai_engine.analyse(name, data, mime, self.cfg.min_caption_side)
        except Exception as e:
            res = {"error": str(e)}
        res.update({"status": "done", "computed_by": self.cfg.address, "ts": time.time()})
        self.dht.store(f"ai:{fid}", res)
        self.store.log_event("ai", f"{name}: {res.get('model', res.get('kind'))}")

    # =================================================================== replication
    def replicate_chunks(self, chunks: dict, skip_holders: dict = None) -> int:
        """Send every chunk to its k responsible nodes (zone-aware), batching all
        chunks that go to the same node into one request, then publish one
        provider record per (chunk, holder). Returns bytes written incl. replicas."""
        skip_holders = skip_holders or {}
        per_node, written = {}, 0
        for h, payload in chunks.items():
            targets = [p for p in self.dht.responsible_for(f"prov:{h}")
                       if p.address not in skip_holders.get(h, ())]
            for p in targets:
                per_node.setdefault(p.address, []).append((h, payload))
        placed = []
        for addr, items in per_node.items():
            for group in framing.batches(items):
                try:
                    if addr == self.cfg.address:
                        with self.store.batch():
                            for h, payload in group:
                                self.store.put_chunk(h, payload, self.cfg.encrypt)
                    else:
                        self.dht.rpc(addr, "/p2p/chunks/put", raw=framing.pack(group), timeout=60)
                    placed += [(h, addr) for h, _ in group]
                    written += sum(len(b) for _, b in group)
                except Exception:
                    continue
        now = time.time()
        self.dht.store_many([(f"prov:{h}", {"id": a, "node": a, "ts": now}, "add") for h, a in placed])
        return written

    # =================================================================== download
    def fetch_chunk(self, h: str, providers=None) -> bytes:
        """Get a chunk from local store or any provider; VERIFY its hash."""
        local = self.store.get_chunk(h)
        if local is not None and sha256(local) == h:
            return local
        if providers is None:
            v = self.dht.get(f"prov:{h}") or {"entries": {}}
            providers = [e["node"] for e in v["entries"].values()]
        random.shuffle(providers)
        for addr in providers:
            if addr == self.cfg.address:
                continue
            try:
                data = self.dht.rpc(addr, f"/p2p/chunk/{h}", method="GET").content
            except Exception:
                continue
            if sha256(data) == h:                     # integrity check on every chunk
                return data
            self.store.log_event("integrity", f"corrupt chunk {h[:12]} from {addr}")
        raise IOError(f"chunk {h[:12]} unavailable")

    def fetch_many(self, hashes: list, prov: dict) -> dict:
        """Fetch many chunks: local first, then ONE batched request per provider.
        Every chunk is verified against its hash; failures fall back to fetch_chunk()."""
        got, missing = {}, []
        for h in set(hashes):
            local = self.store.get_chunk(h)
            if local is not None and sha256(local) == h:
                got[h] = local
            else:
                missing.append(h)
        alive = {p.address for p in self.dht.alive_peers()}
        plan = {}
        for h in missing:
            providers = [e["node"] for e in (prov.get(f"prov:{h}") or {}).get("entries", {}).values()
                         if e["node"] in alive]
            if providers:
                plan.setdefault(random.choice(providers), []).append(h)
        for addr, hs in plan.items():
            for i in range(0, len(hs), 1000):
                try:
                    blob = self.dht.rpc(addr, "/p2p/chunks/get", {"hashes": hs[i:i + 1000]}, timeout=60).content
                    for h, data in framing.unpack(blob):
                        if sha256(data) == h:              # integrity check on every chunk
                            got[h] = data
                except Exception:
                    pass
        for h in missing:
            if h not in got:                              # slow path: try every provider
                providers = [e["node"] for e in (prov.get(f"prov:{h}") or {}).get("entries", {}).values()]
                got[h] = self.fetch_chunk(h, providers)
        return got

    def download(self, fid: str) -> tuple:
        manifest = self.dht.get(f"file:{fid}")
        if not manifest:
            raise KeyError("unknown file id")
        hashes = [c["hash"] for c in manifest["chunks"]]
        prov = self.dht.get_many([f"prov:{h}" for h in set(hashes)])
        got = self.fetch_many(hashes, prov)
        parts = []
        for i, h in enumerate(hashes):
            blob = got[h]
            if manifest.get("encrypted"):
                key = security.unwrap_key(self.cfg.swarm_key, manifest["wrapped_keys"][i])
                blob = security.ce_decrypt(blob, key)
            parts.append(blob)
        data = b"".join(parts)
        if sha256(data) != manifest["fixity_sha256"]:  # end-to-end fixity check (Paper 1)
            raise IOError("fixity check failed")
        return manifest, data

    # =================================================================== near duplicates
    def epoch(self) -> int:
        return int(time.time() // self.cfg.pseudonym_epoch_s)

    def publish_dhash(self, fid: str, h64: int):
        """Put the image in the band index under a per-epoch pseudonym (Paper 3 defense)."""
        ep = self.epoch()
        pid = security.pseudonym(self.cfg.swarm_key + self.cfg.address, fid, ep)
        self.store.x("INSERT OR REPLACE INTO pseudonyms VALUES(?,?,?)", (pid, fid, ep))
        entry = {"id": pid, "pid": pid, "dhash": dh.to_hex(h64), "owner": self.cfg.address,
                 "epoch": ep, "ts": time.time()}
        self.dht.store_many([(k, entry, "add") for k in dh.band_keys(h64, self.cfg.dhash_bands)])

    def find_near_duplicates(self, h64: int, exclude: str = "") -> list:
        keys = dh.band_keys(h64, self.cfg.dhash_bands)
        found = self.dht.get_many(keys)
        candidates = {}
        current = {self.epoch(), self.epoch() - 1}
        for k in keys:
            for e in (found.get(k) or {}).get("entries", {}).values():
                if e.get("epoch") in current:
                    candidates[e["pid"]] = e
        results = []
        for e in candidates.values():
            dist = dh.hamming(h64, int(e["dhash"], 16))      # verify locally
            if dist > self.cfg.hamming_threshold:
                continue
            info = self.resolve_pseudonym(e["owner"], e["pid"])
            if not info or info.get("file_id") == exclude:
                continue
            info["hamming"] = dist
            info["similarity"] = round(1 - dist / 64, 3)
            results.append(info)
        results.sort(key=lambda r: r["hamming"])
        return results

    def resolve_pseudonym(self, owner: str, pid: str):
        """Only the OWNER can turn a pseudonym back into a file id."""
        if owner == self.cfg.address:
            r = self.store.q("SELECT file_id FROM pseudonyms WHERE pid=?", (pid,), one=True)
            if not r:
                return None
            m = self.dht.get(f"file:{r['file_id']}") or {}
            return {"file_id": r["file_id"], "name": m.get("name"), "owner": owner}
        try:
            return self.dht.rpc(owner, f"/p2p/resolve/{pid}", {}).json()
        except Exception:
            return None

    # =================================================================== maintenance
    def heartbeat_loop(self):
        dead = set()
        while not self.stop.is_set():
            for p in self.dht.all_peers():
                self.dht.ping(p.address)
                alive = self.dht.is_alive(p)        # alive = answered within peer_timeout_s
                if not alive and p.address not in dead:
                    dead.add(p.address)
                    self.store.log_event("peer", f"{p.name} ({p.address}) missed heartbeats -> DEAD")
                elif alive and p.address in dead:
                    dead.discard(p.address)
                    self.store.log_event("peer", f"{p.name} ({p.address}) is back online")
            if not self.dht.alive_peers() and self.cfg.bootstrap:
                self.dht.bootstrap()
            self.block_stat_probe()                 # telemetry sample every heartbeat
            self.stop.wait(self.cfg.heartbeat_interval_s)

    def maintenance_loop(self):
        cycle = 0
        while not self.stop.is_set():
            self.stop.wait(self.cfg.maintenance_interval_s)
            cycle += 1
            try:
                self.scrub(sample=20)
                if cycle % 4 == 1:              # Kademlia republish (every ~30 s here)
                    self.republish()
                self.rereplicate()
            except Exception as e:
                self.store.log_event("error", f"maintenance: {e}")

    def block_stat_probe(self):
        """Paper 1 telemetry: time a read+hash of a known local block.
        Measures LOCAL blockstore access, not network latency (same as the paper)."""
        hashes = self.store.chunk_hashes()
        if not hashes:
            return
        h = random.choice(hashes)
        t0 = time.perf_counter()
        data = self.store.get_chunk(h)
        ok = data is not None and sha256(data) == h
        ms = (time.perf_counter() - t0) * 1000
        self.store.add_telemetry("block_stat_ms" if ok else "block_stat_fail", ms)

    def scrub(self, sample=20):
        """Re-hash some stored chunks; delete corrupted ones (re-replication repairs them)."""
        hashes = self.store.chunk_hashes()
        for h in random.sample(hashes, min(sample, len(hashes))):
            data = self.store.get_chunk(h)
            if data is None or sha256(data) != h:
                self.store.delete_chunk(h)
                self.store.log_event("integrity", f"scrub removed corrupt chunk {h[:12]}")

    def republish(self):
        """Kademlia republish: push every DHT record we hold to its CURRENT
        responsible nodes (they change when peers join/leave), and refresh our
        provider records + near-dup index entries (new epoch => new pseudonyms)."""
        items = []
        for key, value in self.store.dht_items():
            if isinstance(value, dict) and "entries" in value:
                if key.startswith("prov:") or key.startswith("band:"):
                    continue                    # refreshed by their owners below
                for e in value["entries"].values():
                    items.append((key, e, "add"))
            else:
                items.append((key, value, "set"))
        now = time.time()
        for h in self.store.chunk_hashes():
            items.append((f"prov:{h}", {"id": self.cfg.address, "node": self.cfg.address, "ts": now}, "add"))
        if items:
            self.dht.store_many(items)
        # refresh near-dup index entries of images uploaded here. In a new epoch
        # publish_dhash() creates a NEW pseudonym; old ones expire (Paper 3 defense)
        for r in self.store.q("SELECT DISTINCT file_id FROM uploads WHERE mime LIKE 'image/%'"):
            m = self.dht.get(f"file:{r['file_id']}")
            if m and m.get("dhash"):
                self.publish_dhash(r["file_id"], int(m["dhash"], 16))

    def rereplicate(self):
        """If a holder died, chunks may have < k live copies. For each local chunk:
        count live providers; the live holder with the smallest node id acts as
        leader and copies the chunk to new responsible nodes."""
        hashes = self.store.chunk_hashes()
        if not hashes:
            return
        alive = {p.address for p in self.dht.alive_peers()} | {self.cfg.address}
        prov = self.dht.get_many([f"prov:{h}" for h in hashes])
        repaired, todo, holders_of = 0, {}, {}
        for h in hashes:
            holders = {e["node"] for e in (prov.get(f"prov:{h}") or {}).get("entries", {}).values()}
            holders.add(self.cfg.address)
            live = sorted(holders & alive, key=node_id_for)   # deterministic leader order
            if len(live) >= self.cfg.replication_k:
                continue
            if live and live[0] != self.cfg.address:
                continue                         # someone else is the leader for this chunk
            data = self.store.get_chunk(h)
            if data is None:
                continue
            todo[h] = data
            holders_of[h] = set(live)
        if todo:                                 # copy to responsible nodes that lack it
            self.replicate_chunks(todo, skip_holders=holders_of)
            repaired = len(todo)
        if repaired:
            self.store.log_event("repair", f"re-replicated {repaired} under-replicated chunks")

    # =================================================================== stats
    def stats(self) -> dict:
        tel = [r["value"] for r in self.store.q(
            "SELECT value FROM telemetry WHERE kind='block_stat_ms' ORDER BY ts DESC LIMIT 500")]
        p50 = p90 = None
        if len(tel) >= 2:
            qs = statistics.quantiles(tel, n=10)
            p50, p90 = statistics.median(tel), qs[8]
        logical = self.store.q("SELECT COALESCE(SUM(size),0) s, COUNT(*) c FROM uploads", one=True)
        n_peers = len(self.dht.alive_peers()) + 1
        raw_cap = self.store.chunk_bytes_total()
        return {
            "node": {"name": self.cfg.name, "address": self.cfg.address, "zone": self.cfg.zone,
                     "id": f"{self.dht.id:064x}", "uptime_s": round(time.time() - self.started_at),
                     "chunker": chunking.chunker_params(self.cfg.chunker, self.cfg.target_chunk_size),
                     "replication_k": self.cfg.replication_k, "encrypt": self.cfg.encrypt,
                     "ai_backend": "transformers" if ai_engine.transformers_available() else "fallback",
                     "hamming_threshold": self.cfg.hamming_threshold},
            "local": {"chunks": len(self.store.chunk_hashes()), "chunk_bytes": raw_cap,
                      "dht_records": self.store.q("SELECT COUNT(*) c FROM dht", one=True)["c"],
                      "uploads": logical["c"], "uploaded_logical_bytes": logical["s"]},
            "telemetry": {"block_stat_p50_ms": p50, "block_stat_p90_ms": p90, "probes": len(tel)},
            "network": {"alive_nodes": n_peers,
                        "capacity_bound_note": "C_unique <= C_raw / r  (Paper 1, Sec. 4.4)"},
        }
