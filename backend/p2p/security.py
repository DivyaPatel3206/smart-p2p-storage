"""
Security helpers.

1) Private swarm key (Paper 1: "a private swarm.key restricted IPFS participation").
   Every node-to-node request carries an HMAC-SHA256 signature computed with a
   shared secret.  A node without the key cannot join or read/write the DHT.
   This restricts *membership*; it is NOT encryption of data at rest (the paper
   makes the same distinction).

2) Optional convergent encryption (Douceur et al. 2002 / Bellare et al. 2013):
   key = SHA-256(plaintext chunk).  Identical plaintext -> identical ciphertext,
   so deduplication still works on encrypted chunks.  Known limitation: anyone
   who can guess the plaintext can confirm it (confirmation-of-file attack).
"""
import hashlib
import hmac
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAX_CLOCK_SKEW_S = 120


def sign(swarm_key: str, method: str, path: str, body: bytes) -> dict:
    """Return the headers to attach to an outgoing P2P request."""
    ts = str(int(time.time()))
    body_hash = hashlib.sha256(body or b"").hexdigest()
    msg = f"{method.upper()}|{path}|{body_hash}|{ts}".encode()
    sig = hmac.new(swarm_key.encode(), msg, hashlib.sha256).hexdigest()
    return {"X-Swarm-Ts": ts, "X-Swarm-Sig": sig}


def verify(swarm_key: str, method: str, path: str, body: bytes, ts: str, sig: str) -> bool:
    """Check an incoming P2P request. Rejects wrong key and replayed old requests."""
    if not ts or not sig:
        return False
    try:
        if abs(time.time() - int(ts)) > MAX_CLOCK_SKEW_S:
            return False
    except ValueError:
        return False
    body_hash = hashlib.sha256(body or b"").hexdigest()
    msg = f"{method.upper()}|{path}|{body_hash}|{ts}".encode()
    expected = hmac.new(swarm_key.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


# --------------------------------------------------------------------------
# Convergent encryption (AES-256-CTR, key and nonce derived from content)
# --------------------------------------------------------------------------
def convergent_key(plaintext: bytes) -> bytes:
    return hashlib.sha256(plaintext).digest()            # 32 bytes => AES-256


def _ctr(key: bytes):
    nonce = hashlib.sha256(b"nonce" + key).digest()[:16]  # deterministic, unique per key
    return Cipher(algorithms.AES(key), modes.CTR(nonce))


def ce_encrypt(plaintext: bytes) -> tuple:
    """Returns (ciphertext, key). Same plaintext => same ciphertext."""
    key = convergent_key(plaintext)
    enc = _ctr(key).encryptor()
    return enc.update(plaintext) + enc.finalize(), key


def ce_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    dec = _ctr(key).decryptor()
    return dec.update(ciphertext) + dec.finalize()


def wrap_key(swarm_key: str, chunk_key: bytes) -> str:
    """Hide a chunk key from non-members by XOR with a swarm-derived pad.
    (Simplification: a real system would wrap per-user keys.)"""
    pad = hashlib.sha256(b"wrap|" + swarm_key.encode()).digest()
    return bytes(a ^ b for a, b in zip(chunk_key, pad)).hex()


def unwrap_key(swarm_key: str, wrapped_hex: str) -> bytes:
    return bytes.fromhex(wrap_key(swarm_key, bytes.fromhex(wrapped_hex)))


def pseudonym(secret: str, file_id: str, epoch: int) -> str:
    """Paper 3 defense ("identifier rotation"): the near-duplicate index stores a
    per-epoch pseudonym instead of the stable file id, so the nodes that answer
    index queries cannot link co-retrieved records across epochs."""
    return hmac.new(secret.encode(), f"{file_id}|{epoch}".encode(),
                    hashlib.sha256).hexdigest()[:24]
