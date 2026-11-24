"""
Kademlia-style Distributed Hash Table (Maymounkov & Mazieres, IPTPS 2002).

Core ideas you should be able to explain:
  * Every node and every key gets a 256-bit ID = SHA-256(...).
  * Distance between two IDs = XOR of the IDs, read as an integer.
  * A key is stored on the k nodes whose IDs are XOR-closest to the key.
  * The routing table has one "k-bucket" per distance range [2^i, 2^(i+1)).
  * To find a node/key we repeatedly ask the closest nodes we know for nodes
    that are even closer (iterative lookup) until nobody closer is returned.

Simplifications (stated for the report):
  * Lookups are sequential instead of alpha-parallel.
  * In small networks the routing table already contains every peer, so
    candidates_for() resolves keys in one hop from the local table.
  * Zone-aware placement (Paper 1): among the closest candidates we prefer
    nodes in different failure zones, so one zone failing cannot remove all
    replicas.
"""
import hashlib
import json
import threading
import time

import requests

from . import security


def node_id_for(address: str) -> int:
    return int(hashlib.sha256(address.encode()).hexdigest(), 16)


def key_id(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest(), 16)


class Peer:
    def __init__(self, address: str, zone: str = "?", name: str = "?"):
        self.address = address
        self.id = node_id_for(address)
        self.zone = zone
        self.name = name
        self.last_seen = 0.0
        self.rtt_ms = None

    def to_dict(self):
        return {"address": self.address, "zone": self.zone, "name": self.name}


class DHT:
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.local = store
        self.self_peer = Peer(cfg.address, cfg.zone, cfg.name)
        self.self_peer.last_seen = float("inf")
        self.id = self.self_peer.id
        self.buckets = [[] for _ in range(256)]
        self.lock = threading.RLock()
        self.http = requests.Session()

    # ------------------------------------------------------------ routing table
    def bucket_index(self, other_id: int) -> int:
        d = self.id ^ other_id
        return max(0, d.bit_length() - 1)

    def add_peer(self, address: str, zone: str = "?", name: str = "?", seen: bool = True):
        if address == self.cfg.address:
            return
        with self.lock:
            p = self.get_peer(address)
            if p is None:
                p = Peer(address, zone, name)
                bucket = self.buckets[self.bucket_index(p.id)]
                if len(bucket) >= self.cfg.k_bucket_size:
                    # Kademlia policy: keep old live peers; evict only a dead one
                    dead = [x for x in bucket if not self.is_alive(x)]
                    if not dead:
                        return
                    bucket.remove(dead[0])
                bucket.append(p)
            if zone != "?":
                p.zone = zone
            if name != "?":
                p.name = name
            if seen:
                p.last_seen = time.time()

    def get_peer(self, address: str):
        with self.lock:
            for b in self.buckets:
                for p in b:
                    if p.address == address:
                        return p
        return None

    def all_peers(self) -> list:
        with self.lock:
            return [p for b in self.buckets for p in b]

    def is_alive(self, p: Peer) -> bool:
        return (time.time() - p.last_seen) < self.cfg.peer_timeout_s

    def alive_peers(self) -> list:
        return [p for p in self.all_peers() if self.is_alive(p)]

    def closest(self, target: int, n: int, include_self=True, alive_only=True) -> list:
        peers = self.alive_peers() if alive_only else self.all_peers()
        if include_self:
            peers = peers + [self.self_peer]
        return sorted(peers, key=lambda p: p.id ^ target)[:n]

    def responsible_for(self, key: str, k: int = None) -> list:
        """The k nodes that should hold `key`, zone-aware (Paper 1)."""
        k = k or self.cfg.replication_k
        cands = self.closest(key_id(key), max(2 * k, k + 2))
        chosen, zones = [], set()
        for p in cands:                      # pass 1: closest node of each new zone
            if len(chosen) == k:
                break
            if p.zone not in zones:
                chosen.append(p)
                zones.add(p.zone)
        for p in cands:                      # pass 2: fill up with closest remaining
            if len(chosen) == k:
                break
            if p not in chosen:
                chosen.append(p)
        return chosen

    def candidates_for(self, key: str) -> list:
        """Where to LOOK for a key: a superset of responsible_for()."""
        k = self.cfg.replication_k
        return self.closest(key_id(key), max(2 * k, k + 2))

    # ------------------------------------------------------------ RPC
    def rpc(self, address: str, path: str, payload=None, method="POST", raw: bytes = None,
            timeout=5.0):
        """Signed request to another node (swarm key, Paper 1)."""
        body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else b"")
        headers = security.sign(self.cfg.swarm_key, method, path, body)
        headers.update({"X-Node-Addr": self.cfg.address, "X-Node-Zone": self.cfg.zone,
                        "X-Node-Name": self.cfg.name,
                        "Content-Type": "application/octet-stream" if raw is not None else "application/json"})
        url = f"{address}{path}"                    # address is a full base URL
        t0 = time.time()
        r = self.http.request(method, url, data=body, headers=headers, timeout=timeout)
        p = self.get_peer(address)
        if p is not None and r.status_code < 500:
            p.last_seen = time.time()
            p.rtt_ms = (time.time() - t0) * 1000
        r.raise_for_status()
        return r

    def ping(self, address: str) -> bool:
        try:
            r = self.rpc(address, "/p2p/ping", {}, timeout=2.0)
            info = r.json()
            self.add_peer(address, info.get("zone", "?"), info.get("name", "?"))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ iterative lookup
    def iterative_find_node(self, target: int) -> list:
        """Kademlia node lookup: keep asking the closest unqueried nodes."""
        k = self.cfg.k_bucket_size
        shortlist = {p.address: p for p in self.closest(target, k, include_self=False)}
        queried = set()
        while True:
            # stop when the k closest nodes we know have all been asked
            top_k = sorted(shortlist.values(), key=lambda p: p.id ^ target)[:k]
            pending = [p for p in top_k if p.address not in queried][: self.cfg.alpha]
            if not pending:
                break
            for p in pending:
                queried.add(p.address)
                try:
                    r = self.rpc(p.address, "/p2p/find_node", {"target": hex(target)}, timeout=3)
                    for info in r.json()["nodes"]:
                        if info["address"] == self.cfg.address:
                            continue
                        self.add_peer(info["address"], info.get("zone", "?"), info.get("name", "?"),
                                      seen=False)
                        np_ = self.get_peer(info["address"])
                        if np_ is not None:
                            shortlist[np_.address] = np_
                except Exception:
                    shortlist.pop(p.address, None)
        return sorted(shortlist.values(), key=lambda p: p.id ^ target)[:k]

    def bootstrap(self):
        """Join the network: contact a known peer, then look up our own ID
        (standard Kademlia join), which fills our k-buckets."""
        for addr in self.cfg.bootstrap:
            if self.ping(addr):
                self.iterative_find_node(self.id)
        # ping everyone we learned about so they learn us too
        for p in self.all_peers():
            self.ping(p.address)

    # ------------------------------------------------------------ key/value API
    def store_many(self, items: list):
        """items: list of (key, value, mode). mode 'set' overwrites, 'add' merges
        an entry into a set (used for provider lists and the near-dup index)."""
        by_node = {}
        for key, value, mode in items:
            for p in self.responsible_for(key):
                by_node.setdefault(p.address, []).append({"key": key, "value": value, "mode": mode})
        ok = 0
        for addr, batch in by_node.items():
            try:
                if addr == self.cfg.address:
                    self.local_store_batch(batch)
                else:
                    self.rpc(addr, "/p2p/store", {"items": batch})
                ok += 1
            except Exception:
                pass
        return ok

    def store(self, key, value, mode="set"):
        return self.store_many([(key, value, mode)])

    def get_many(self, keys: list) -> dict:
        """Look up many keys at once. 'add'-type values are merged across nodes."""
        by_node = {}
        for key in keys:
            for p in self.candidates_for(key):
                by_node.setdefault(p.address, []).append(key)
        merged = {}
        for addr, ks in by_node.items():
            try:
                if addr == self.cfg.address:
                    res = self.local_get_batch(ks, observer="local")
                else:
                    res = self.rpc(addr, "/p2p/get", {"keys": ks}).json()["values"]
            except Exception:
                continue
            for k, v in res.items():
                if v is None:
                    continue
                if isinstance(v, dict) and "entries" in v:
                    cur = merged.setdefault(k, {"entries": {}})
                    for eid, e in v["entries"].items():
                        old = cur["entries"].get(eid)
                        if old is None or e.get("ts", 0) > old.get("ts", 0):
                            cur["entries"][eid] = e
                elif k not in merged:
                    merged[k] = v
        return merged

    def get(self, key: str):
        return self.get_many([key]).get(key)

    # ------------------------------------------------------------ local side
    def local_store_batch(self, batch: list):
        with self.local.batch():
            self._local_store_batch(batch)

    def _local_store_batch(self, batch: list):
        for it in batch:
            key, value, mode = it["key"], it["value"], it.get("mode", "set")
            if mode == "add":
                cur = self.local.dht_get(key) or {"entries": {}}
                eid = value["id"]
                old = cur["entries"].get(eid)
                if old is None or value.get("ts", 0) >= old.get("ts", 0):
                    cur["entries"][eid] = value
                self.local.dht_put(key, cur)
            else:
                self.local.dht_put(key, value)

    def local_get_batch(self, keys: list, observer: str) -> dict:
        out = {}
        now = time.time()
        for k in keys:
            v = self.local.dht_get(k)
            if isinstance(v, dict) and "entries" in v:     # drop expired soft-state entries
                ttl = (self.cfg.provider_ttl_s if k.startswith("prov:")
                       else 3 * self.cfg.pseudonym_epoch_s if k.startswith("band:") else None)
                if ttl:
                    v["entries"] = {eid: e for eid, e in v["entries"].items()
                                    if now - e.get("ts", now) < ttl}
            out[k] = v
            if k.startswith("band:") and v:
                # Paper 3: this is exactly what an index holder can observe
                self.local.x("INSERT INTO query_log VALUES(?,?,?)",
                             (now, k, json.dumps(sorted(v.get("entries", {}).keys()))))
        return out
