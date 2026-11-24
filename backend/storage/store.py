"""
Local storage of ONE node.

  * Blockstore: chunk bytes are files on disk named by their SHA-256
    (data/<node>/blocks/ab/abcdef...). Content addressing => the name IS the
    integrity check.
  * SQLite (node.db) keeps the metadata: chunk index, DHT key/value records this
    node is responsible for, file manifests uploaded here, the pseudonym table,
    AI results, telemetry samples and the near-duplicate query log.
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    hash TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    encrypted INTEGER DEFAULT 0,
    stored_at REAL
);
CREATE TABLE IF NOT EXISTS dht (           -- DHT records held by this node
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,                   -- JSON
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS uploads (       -- every upload through this node (duplicates too)
    file_id TEXT,
    name TEXT, size INTEGER, mime TEXT,
    fixity TEXT, object_uid TEXT,
    uploaded_at REAL
);
CREATE TABLE IF NOT EXISTS pseudonyms (    -- Paper 3 defense: pid -> file_id (owner only)
    pid TEXT PRIMARY KEY, file_id TEXT, epoch INTEGER
);
CREATE TABLE IF NOT EXISTS telemetry (     -- Paper 1: block-stat probes
    ts REAL, kind TEXT, value REAL
);
CREATE TABLE IF NOT EXISTS query_log (     -- what an index holder can observe (Paper 3)
    ts REAL, query_key TEXT, returned TEXT
);
CREATE TABLE IF NOT EXISTS events (
    ts REAL, kind TEXT, message TEXT
);
"""


class LocalStore:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.block_dir = os.path.join(data_dir, "blocks")
        os.makedirs(self.block_dir, exist_ok=True)
        self.lock = threading.RLock()
        self._batch_depth = 0
        self.db = sqlite3.connect(os.path.join(data_dir, "node.db"), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")       # faster, readers don't block writers
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ------------------------------------------------------------ helpers
    def q(self, sql, args=(), one=False):
        with self.lock:
            cur = self.db.execute(sql, args)
            rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows

    def x(self, sql, args=()):
        with self.lock:
            self.db.execute(sql, args)
            if self._batch_depth == 0:
                self.db.commit()

    @contextmanager
    def batch(self):
        """Group many writes into ONE transaction (one commit instead of thousands)."""
        with self.lock:
            self._batch_depth += 1
            try:
                yield
            finally:
                self._batch_depth -= 1
                if self._batch_depth == 0:
                    self.db.commit()

    # ------------------------------------------------------------ blocks
    def _path(self, h: str) -> str:
        return os.path.join(self.block_dir, h[:2], h)

    def has_chunk(self, h: str) -> bool:
        return os.path.exists(self._path(h))

    def put_chunk(self, h: str, data: bytes, encrypted: bool = False) -> bool:
        """Store a chunk after verifying its hash. Returns False if hash mismatch."""
        if hashlib.sha256(data).hexdigest() != h:
            return False
        p = self._path(h)
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        self.x("INSERT OR IGNORE INTO chunks(hash,size,encrypted,stored_at) VALUES(?,?,?,?)",
               (h, len(data), int(encrypted), time.time()))
        return True

    def get_chunk(self, h: str):
        p = self._path(h)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    def delete_chunk(self, h: str):
        try:
            os.remove(self._path(h))
        except FileNotFoundError:
            pass
        self.x("DELETE FROM chunks WHERE hash=?", (h,))

    def chunk_hashes(self) -> list:
        return [r["hash"] for r in self.q("SELECT hash FROM chunks")]

    def chunk_bytes_total(self) -> int:
        r = self.q("SELECT COALESCE(SUM(size),0) s, COUNT(*) c FROM chunks", one=True)
        return int(r["s"])

    # ------------------------------------------------------------ DHT records
    def dht_get(self, key: str):
        r = self.q("SELECT value FROM dht WHERE key=?", (key,), one=True)
        return json.loads(r["value"]) if r else None

    def dht_put(self, key: str, value):
        self.x("INSERT OR REPLACE INTO dht(key,value,updated_at) VALUES(?,?,?)",
               (key, json.dumps(value, sort_keys=True), time.time()))

    def dht_items(self):
        return [(r["key"], json.loads(r["value"])) for r in self.q("SELECT key,value FROM dht")]

    # ------------------------------------------------------------ misc
    def log_event(self, kind: str, message: str):
        self.x("INSERT INTO events VALUES(?,?,?)", (time.time(), kind, message))
        self.x("DELETE FROM events WHERE rowid NOT IN (SELECT rowid FROM events ORDER BY ts DESC LIMIT 300)")

    def add_telemetry(self, kind: str, value: float):
        self.x("INSERT INTO telemetry VALUES(?,?,?)", (time.time(), kind, value))
