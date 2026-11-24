"""
Content-Defined Chunking (CDC) — implementation of the base algorithms
benchmarked in the base paper:

  M. Gregoriadis, L. Balduf, B. Scheuermann, J. Pouwelse,
  "Benchmarking Content-Defined Chunking Algorithms for Data Deduplication",
  arXiv:2610.13704 (Oct 2026).

What we take from the paper
---------------------------
1. FSC (fixed-size chunking) suffers from the *boundary-shift problem*: inserting
   one byte shifts every later boundary, so unchanged data looks new.
2. AE (Asymmetric Extremum) is the most balanced base algorithm across
   throughput, deduplication and chunk-size variance (paper, Table IX).
3. The *corrected* AE parameter rule (paper Sec. IV-B, Table IV):
       h ≈ µ − 256            for µ ≥ 2 KiB
       h = 348, 793           for µ = 512, 1024 (found by simulation)
   The old, widely copied rule h = µ / (e − 1) makes chunks 13–39 % too small.
   We keep the old rule as "ae_legacy" so the evaluation can reproduce that finding.
4. Gear is the strongest hash-based alternative; bitmask size b = round(log2 µ).

These are *base* algorithms: no min/max thresholds, no normalisation, exactly
like the paper, so our measurements are comparable to theirs.
Pure Python is ~100x slower than the paper's Rust, so compare *rankings*
and *chunk-size statistics*, not absolute MiB/s.
"""
import math
import random

# ----------------------------------------------------------------------------
# AE parameterisation (Paper 2, Table IV)
# ----------------------------------------------------------------------------
AE_HORIZON_TABLE = {512: 348, 1024: 793, 2048: 1792, 4096: 3840, 8192: 7936}


def ae_horizon(target: int) -> int:
    """Corrected horizon h for a target mean chunk size µ (paper Sec. IV-B)."""
    if target in AE_HORIZON_TABLE:
        return AE_HORIZON_TABLE[target]
    if target >= 2048:
        return target - 256                      # h ≈ µ − 256 (large-horizon approximation)
    # small, non-tabulated targets: interpolate between the simulated points
    return max(1, int(round(target * 0.7)))


def ae_horizon_legacy(target: int) -> int:
    """The OLD formula h = µ/(e−1) that the paper shows is wrong."""
    return max(1, int(round(target / (math.e - 1))))


# ----------------------------------------------------------------------------
# Chunkers. Each returns a list of cut positions (exclusive end offsets).
# ----------------------------------------------------------------------------
def chunk_fsc(data: bytes, target: int) -> list:
    """Fixed-Size Chunking: cut every `target` bytes."""
    n = len(data)
    cuts = list(range(target, n, target))
    if n:
        cuts.append(n)
    return cuts


def chunk_ae(data: bytes, target: int, horizon: int = None) -> list:
    """
    Asymmetric Extremum chunking (max variant).

    Walk through the bytes remembering the position of the current maximum byte.
    If `h` bytes pass without any byte being GREATER than that maximum, the byte
    at (max_pos + h) is a cut point.  Equivalently (paper Def. 1): position i+h
    is a cut point if B_i >= max(B_{i+1} .. B_{i+h}).

    Because a chunk can never end before `h` bytes after its first byte, AE has a
    built-in lower bound on chunk size => low variance (paper Sec. VI).
    """
    h = horizon if horizon is not None else ae_horizon(target)
    n = len(data)
    cuts = []
    start = 0
    while start < n:
        max_val = data[start]
        max_pos = start
        i = start + 1
        cut = n                              # default: last chunk runs to end of data
        while i < n:
            b = data[i]
            if b > max_val:                  # new (strictly greater) maximum
                max_val = b
                max_pos = i
            elif i == max_pos + h:           # h bytes with nothing bigger => cut here
                cut = i + 1
                break
            i += 1
        cuts.append(cut)
        start = cut
    return cuts


def _gear_table(seed: int = 42) -> list:
    rnd = random.Random(seed)
    return [rnd.getrandbits(64) for _ in range(256)]


GEAR = _gear_table()
MASK64 = (1 << 64) - 1


def chunk_gear(data: bytes, target: int) -> list:
    """
    Gear chunking: rolling fingerprint fp = (fp << 1) + G[byte].
    A cut point is declared when the top b bits of fp are all zero,
    which happens with probability 2^-b per byte => mean chunk ≈ 2^b.
    b = round(log2 µ) as in the paper (Table III).
    Using the TOP bits means the decision depends on the last 64 bytes (the
    implicit Gear window), which mirrors the "w = 32/64" window of Rabin.
    """
    b = int(round(math.log2(target)))
    mask = ((1 << b) - 1) << (64 - b)        # top-b-bit mask
    n = len(data)
    cuts = []
    fp = 0
    g = GEAR
    for i in range(n):
        fp = ((fp << 1) + g[data[i]]) & MASK64
        if fp & mask == 0:
            cuts.append(i + 1)
            fp = 0
    if not cuts or cuts[-1] != n:
        if n:
            cuts.append(n)
    return cuts


CHUNKERS = {
    "fsc": chunk_fsc,
    "ae": chunk_ae,
    "gear": chunk_gear,
    "ae_legacy": lambda d, t: chunk_ae(d, t, horizon=ae_horizon_legacy(t)),
}


def split(data: bytes, algorithm: str = "ae", target: int = 4096) -> list:
    """Split bytes into a list of chunk byte-strings."""
    cuts = CHUNKERS[algorithm](data, target)
    chunks, prev = [], 0
    for c in cuts:
        chunks.append(data[prev:c])
        prev = c
    return chunks


def chunker_params(algorithm: str, target: int) -> dict:
    """Import parameters that must be stored in the manifest (Paper 1, Sec. 4.1:
    an ID that depends on chunking must record the chunking parameters)."""
    p = {"algorithm": algorithm, "target": target}
    if algorithm == "ae":
        p["horizon"] = ae_horizon(target)
    elif algorithm == "ae_legacy":
        p["horizon"] = ae_horizon_legacy(target)
    elif algorithm == "gear":
        p["mask_bits"] = int(round(math.log2(target)))
    return p
