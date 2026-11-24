"""
Difference hash (dHash) for near-duplicate images + LSH banding for the DHT.

dHash in 4 steps (64-bit version):
  1. convert to grayscale
  2. resize to 9 x 8 pixels (this throws away size, compression noise, detail)
  3. for each row compare neighbouring pixels: bit = 1 if left > right
     -> 8 comparisons x 8 rows = 64 bits
  4. two images are near-duplicates if the Hamming distance of their hashes
     (number of different bits) is <= threshold (we use 10 of 64)

Why banding?  A DHT can only do EXACT key lookups, but we need "hashes within
Hamming distance T".  Split the 64-bit hash into b = 4 bands of 16 bits and
store the image under each band value.  By the pigeonhole principle, if two
hashes differ in <= 3 bits, at least one band is identical, so the lookup
finds it.  With T = 10 a match is found with high probability, not certainty
(bit flips spread over all 4 bands are missed) — the evaluation measures this
recall directly.
"""
from PIL import Image


def dhash(img: Image.Image, hash_size: int = 8) -> int:
    g = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    px = list(g.getdata())
    w = hash_size + 1
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = px[row * w + col]
            right = px[row * w + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def dhash_file(path_or_fp) -> int:
    with Image.open(path_or_fp) as im:
        return dhash(im)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def bands(h: int, n_bands: int = 4, bits: int = 64) -> list:
    """Split a hash into n_bands integers (each bits/n_bands wide)."""
    width = bits // n_bands
    mask = (1 << width) - 1
    return [(h >> (width * (n_bands - 1 - i))) & mask for i in range(n_bands)]


def band_keys(h: int, n_bands: int = 4) -> list:
    """DHT keys for the near-duplicate index, e.g. 'band:2:3fa1'."""
    width_hex = 64 // n_bands // 4
    return [f"band:{i}:{v:0{width_hex}x}" for i, v in enumerate(bands(h, n_bands))]


def to_hex(h: int) -> str:
    return f"{h:016x}"
