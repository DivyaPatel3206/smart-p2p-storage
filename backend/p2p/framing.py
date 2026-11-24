"""
Batch transfer of many chunks in ONE HTTP request (much faster than one
request per 4 KB chunk).

Wire format:   <JSON header>\n<chunk 1 bytes><chunk 2 bytes>...
               header = {"hashes": [...], "sizes": [...]}
"""
import json


def pack(items: list) -> bytes:
    """items: list of (hash, bytes)."""
    header = {"hashes": [h for h, _ in items], "sizes": [len(b) for _, b in items]}
    return json.dumps(header).encode() + b"\n" + b"".join(b for _, b in items)


def unpack(blob: bytes) -> list:
    nl = blob.index(b"\n")
    header = json.loads(blob[:nl])
    out, pos = [], nl + 1
    for h, n in zip(header["hashes"], header["sizes"]):
        out.append((h, blob[pos:pos + n]))
        pos += n
    return out


def batches(items: list, max_bytes: int = 4 * 1024 * 1024) -> list:
    """Split (hash, bytes) items into groups of at most ~max_bytes."""
    groups, cur, size = [], [], 0
    for it in items:
        if cur and size + len(it[1]) > max_bytes:
            groups.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += len(it[1])
    if cur:
        groups.append(cur)
    return groups
