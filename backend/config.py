"""
Central configuration for one P2P node.

Every node runs the SAME code; only the command-line arguments differ
(port, name, zone, bootstrap peer). There is no central server.
"""
import argparse
import os
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)


@dataclass
class NodeConfig:
    host: str = "127.0.0.1"
    port: int = 5001
    name: str = "node1"
    zone: str = "zone-A"                 # failure domain (Paper 1: replicas across zones)
    bootstrap: list = field(default_factory=list)   # e.g. ["127.0.0.1:5001"]
    data_dir: str = ""

    # --- DHT / replication ---
    k_bucket_size: int = 8               # Kademlia k-bucket capacity
    replication_k: int = 2               # copies of every chunk / DHT record
    alpha: int = 3                       # parallelism of iterative lookups (we query sequentially, see dht.py)

    # --- chunking (Paper 2) ---
    chunker: str = "ae"                  # "ae" | "gear" | "fsc"
    target_chunk_size: int = 4096        # µ in the paper

    # --- near-duplicate detection ---
    hamming_threshold: int = 10          # dHash 64-bit; <= 10 bits different => near-duplicate
    dhash_bands: int = 4                 # 64 bits split into 4 bands of 16 bits (LSH banding)
    pseudonym_epoch_s: int = 300         # Paper 3 defense: rotate index identifiers every 5 min

    # --- failure handling ---
    heartbeat_interval_s: float = 3.0
    peer_timeout_s: float = 10.0
    maintenance_interval_s: float = 8.0  # re-replication + republish + scrub + telemetry
    provider_ttl_s: float = 90.0

    # --- security (Paper 1: private swarm key) ---
    swarm_key: str = "change-me-shared-swarm-secret"
    encrypt: bool = False                # optional convergent encryption of chunks at rest

    # --- AI ---
    enable_ai: bool = True
    min_caption_side: int = 128          # Paper 4: captions on tiny images are unreliable

    advertise: str = ""                  # public base URL other nodes use to reach us

    @property
    def address(self) -> str:
        """This node's identity on the network = the URL peers use to reach it,
        e.g. http://127.0.0.1:5001 locally or https://p2p-node1.onrender.com on Render."""
        if self.advertise:
            return normalize_url(self.advertise)
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        return f"http://{host}:{self.port}"


def normalize_url(addr: str) -> str:
    """'127.0.0.1:5001' -> 'http://127.0.0.1:5001';  'x.onrender.com' -> 'https://x.onrender.com'."""
    addr = addr.strip().rstrip("/")
    if addr.startswith(("http://", "https://")):
        return addr
    host_has_port = ":" in addr
    return ("http://" if host_has_port else "https://") + addr


def _env_advertise() -> str:
    """On Render the public URL is provided in environment variables."""
    if os.environ.get("ADVERTISE_URL"):
        return os.environ["ADVERTISE_URL"]
    if os.environ.get("RENDER_EXTERNAL_URL"):
        return os.environ["RENDER_EXTERNAL_URL"]
    if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        return "https://" + os.environ["RENDER_EXTERNAL_HOSTNAME"]
    return ""


def parse_args() -> NodeConfig:
    """Every option can come from the command line (local laptop) or from an
    environment variable (cloud deployment such as Render)."""
    env = os.environ.get
    on_cloud = bool(env("RENDER") or env("PORT"))
    p = argparse.ArgumentParser(description="Smart P2P Storage node")
    p.add_argument("--host", default=env("HOST", "0.0.0.0" if on_cloud else "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(env("PORT", "5001")))
    p.add_argument("--name", default=env("NODE_NAME"))
    p.add_argument("--zone", default=env("NODE_ZONE", "zone-A"))
    p.add_argument("--bootstrap", default=env("BOOTSTRAP", env("BOOTSTRAP_HOST", "")),
                   help="comma separated peers: host:port or https://url")
    p.add_argument("--advertise", default=_env_advertise(), help="public URL of this node")
    p.add_argument("--k", type=int, default=int(env("REPLICATION_K", "2")), help="replication factor")
    p.add_argument("--chunker", default=env("CHUNKER", "ae"), choices=["ae", "gear", "fsc"])
    p.add_argument("--chunk-size", type=int, default=int(env("CHUNK_SIZE", "4096")))
    p.add_argument("--hamming", type=int, default=10)
    p.add_argument("--swarm-key", default=env("SWARM_KEY", "change-me-shared-swarm-secret"))
    p.add_argument("--encrypt", action="store_true", default=env("ENCRYPT") == "1",
                   help="convergent encryption of chunks")
    p.add_argument("--no-ai", action="store_true", default=env("NO_AI") == "1",
                   help="disable DistilBART/BLIP even if installed")
    p.add_argument("--data-dir", default=env("DATA_DIR"))
    a = p.parse_args()

    name = a.name or f"node{a.port}"
    cfg = NodeConfig(
        host=a.host, port=a.port, name=name, zone=a.zone,
        bootstrap=[normalize_url(b) for b in a.bootstrap.split(",") if b.strip()],
        replication_k=a.k, chunker=a.chunker, target_chunk_size=a.chunk_size,
        hamming_threshold=a.hamming, swarm_key=a.swarm_key, encrypt=a.encrypt,
        enable_ai=not a.no_ai, advertise=a.advertise,
        data_dir=a.data_dir or os.path.join(PROJECT_DIR, "data", name),
    )
    if on_cloud:
        cfg.peer_timeout_s = 20.0          # internet latency + occasional slow responses
    return cfg
