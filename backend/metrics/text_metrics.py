"""
Text-generation metrics implemented from scratch (no extra packages), so the
student can explain every line.

  ROUGE-N  (Lin, 2004): n-gram overlap; we report the F1 of precision and recall.
  ROUGE-L  : based on the Longest Common Subsequence of the two token lists.
  METEOR   (Lavie & Denkowski): unigram matching with a recall-weighted harmonic
             mean and a fragmentation penalty.
             SIMPLIFIED: exact word matches only (the original also matches
             stems and WordNet synonyms), so scores are a little lower than the
             official implementation.
  Contra-Acc (Paper 4, ContraSense): for every sample a correctness vector over
             several dimensions p_i in [0,1]^d; the sample score is its WORST
             dimension  S_i = min_j p_ij ; Contra-Acc = mean_i S_i.
"""
import re
from collections import Counter


def tokens(s: str) -> list:
    return re.findall(r"[a-z0-9]+", s.lower())


def _f1(p, r):
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def rouge_n(cand: str, ref: str, n: int = 1) -> float:
    c, r = tokens(cand), tokens(ref)
    cg = Counter(tuple(c[i:i + n]) for i in range(len(c) - n + 1))
    rg = Counter(tuple(r[i:i + n]) for i in range(len(r) - n + 1))
    overlap = sum((cg & rg).values())
    if not cg or not rg:
        return 0.0
    return _f1(overlap / sum(cg.values()), overlap / sum(rg.values()))


def _lcs(a: list, b: list) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def rouge_l(cand: str, ref: str) -> float:
    c, r = tokens(cand), tokens(ref)
    if not c or not r:
        return 0.0
    l = _lcs(c, r)
    return _f1(l / len(c), l / len(r))


def meteor(cand: str, ref: str, alpha: float = 0.9, beta: float = 3.0, gamma: float = 0.5) -> float:
    c, r = tokens(cand), tokens(ref)
    if not c or not r:
        return 0.0
    used, align = set(), []
    for i, w in enumerate(c):                       # greedy exact alignment, left to right
        for j, v in enumerate(r):
            if j not in used and w == v:
                used.add(j)
                align.append((i, j))
                break
    m = len(align)
    if m == 0:
        return 0.0
    p, rec = m / len(c), m / len(r)
    fmean = p * rec / (alpha * p + (1 - alpha) * rec)
    chunks = 1                                      # contiguous runs in both strings
    for (i1, j1), (i2, j2) in zip(align, align[1:]):
        if not (i2 == i1 + 1 and j2 == j1 + 1):
            chunks += 1
    penalty = gamma * (chunks / m) ** beta
    return fmean * (1 - penalty)


def best_over_refs(fn, cand: str, refs: list) -> float:
    return max(fn(cand, r) for r in refs) if refs else 0.0


def contra_acc(correctness: list) -> float:
    """correctness: list of per-sample vectors (values in [0,1]). Paper 4 Eq.: mean of min."""
    if not correctness:
        return 0.0
    return sum(min(v) for v in correctness) / len(correctness)
