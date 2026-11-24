"""
Small, reproducible stand-ins for the datasets of the base paper (Paper 2, Table II).

  RAND : random bytes (high-entropy calibration baseline, exactly as in the paper)
  CODE : several versions of a source-code tree stored as uncompressed TAR archives
         (paper: 207 versions of Linux/GCC/... tarballs; ours: Python stdlib files)
  DB   : successive snapshots of a real SQLite database file under an
         insert/update/delete workload (paper: 25 snapshots of a MySQL VM running TPC-C)
  DIR  : optional, your own folder of files/versions (--dir)

The paper's datasets are 11-285 GB; ours are a few MB so pure Python finishes in
about a minute. Chunk-size statistics transfer; absolute throughput does not.
"""
import io
import os
import random
import sqlite3
import tarfile
import tempfile


def rand_dataset(size_mb: float = 2.0, seed: int = 1) -> list:
    rnd = random.Random(seed)
    return [rnd.randbytes(int(size_mb * 1024 * 1024))]


def _stdlib_sources(limit_bytes: int = 700_000) -> dict:
    """Collect real source files from the Python standard library."""
    base = os.path.dirname(os.__file__)
    files = {}
    total = 0
    for pkg in ("json", "email", "http", "logging", "asyncio", "xml", "unittest", "concurrent"):
        d = os.path.join(base, pkg)
        for dp, _, fns in sorted(os.walk(d)):
            for fn in sorted(fns):
                if fn.endswith(".py"):
                    p = os.path.join(dp, fn)
                    with open(p, "rb") as fh:
                        data = fh.read()
                    files[os.path.relpath(p, base)] = data
                    total += len(data)
                    if total > limit_bytes:
                        return files
    return files


def _mutate(files: dict, rnd: random.Random, frac: float = 0.06) -> dict:
    """Simulate a new release: edit ~6 % of the files (insert, delete, change lines)."""
    out = dict(files)
    for name in rnd.sample(sorted(files), max(1, int(len(files) * frac))):
        lines = out[name].split(b"\n")
        for _ in range(rnd.randint(1, 6)):
            if not lines:
                break
            i = rnd.randrange(len(lines))
            op = rnd.random()
            if op < 0.4:
                lines.insert(i, b"# changed in this release: " + str(rnd.random()).encode())
            elif op < 0.7:
                lines.pop(i)
            else:
                lines[i] = lines[i] + b"  # tweak"
        out[name] = b"\n".join(lines)
    if rnd.random() < 0.5:                                   # occasionally add a file
        out[f"new_module_{rnd.randint(0, 999)}.py"] = b"def f():\n    return %d\n" % rnd.randint(0, 99)
    return out


def _tar(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size = len(files[name])
            info.mtime = 0
            tf.addfile(info, io.BytesIO(files[name]))
    return buf.getvalue()


def code_dataset(versions: int = 6, seed: int = 2) -> list:
    rnd = random.Random(seed)
    files = _stdlib_sources()
    out = []
    for _ in range(versions):
        out.append(_tar(files))
        files = _mutate(files, rnd)
    return out


def db_dataset(snapshots: int = 8, seed: int = 3) -> list:
    rnd = random.Random(seed)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    con = sqlite3.connect(tmp.name)
    con.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, customer TEXT, item TEXT, qty INT, price REAL, note TEXT)")
    con.commit()
    out = []
    next_id = 1
    for _ in range(snapshots):
        for _ in range(400):                                    # new orders
            con.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)",
                        (next_id, f"cust{rnd.randint(1, 500)}", f"item{rnd.randint(1, 80)}",
                         rnd.randint(1, 9), round(rnd.uniform(10, 999), 2), "x" * rnd.randint(0, 60)))
            next_id += 1
        for _ in range(60):                                     # updates
            con.execute("UPDATE orders SET qty=? WHERE id=?", (rnd.randint(1, 9), rnd.randint(1, next_id)))
        for _ in range(25):                                     # deletes
            con.execute("DELETE FROM orders WHERE id=?", (rnd.randint(1, next_id),))
        con.commit()
        with open(tmp.name, "rb") as fh:
            out.append(fh.read())
    con.close()
    os.unlink(tmp.name)
    return out


def dir_dataset(path: str, max_bytes: int = 50 * 1024 * 1024) -> list:
    out, total = [], 0
    for dp, _, fns in sorted(os.walk(path)):
        for fn in sorted(fns):
            with open(os.path.join(dp, fn), "rb") as fh:
                data = fh.read()
            out.append(data)
            total += len(data)
            if total > max_bytes:
                return out
    return out
