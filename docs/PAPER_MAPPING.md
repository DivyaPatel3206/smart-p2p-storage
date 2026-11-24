# Step 1 — What the papers say, and Step 2 — How they map onto this project

Four papers were uploaded. **Paper 2 is used as the base paper**: it is the only one
that is about deduplication itself. The other three each improve one module.

| # | Paper | arXiv | Role in this project |
|---|---|---|---|
| 1 | Snellings et al., *A Private IPFS Data Sanctuary for Verifiable Digital Collection Objects* | 2610.07970 | P2P layer: identity, zones, swarm key, telemetry |
| **2** | **Gregoriadis, Balduf, Scheuermann, Pouwelse, *Benchmarking Content-Defined Chunking Algorithms for Data Deduplication*** | **2610.13704** | **BASE PAPER: chunking + dedup metrics** |
| 3 | Zhang, He, Sun, Lv, Liu, *"More Than You Expect!": Leakage-Abuse Attacks on Encrypted Vector Search* | 2611.27174 | Security of the shared near-duplicate index |
| 4 | Lin, Su, Liu, Bai, Zhu, Chen, *Can Vision–Language Models Truly Understand Images? A Benchmark Beyond Commonsense Bias* | 2611.22360 | Trustworthiness + evaluation of AI captions |

---

## Paper 2 (BASE) — Benchmarking CDC algorithms

- **Problem.** Every dedup system first cuts data into chunks. Many CDC algorithms have been
  proposed, but earlier benchmarks mixed up the *base* cut-point rule with add-ons
  (min/max sizes, normalisation, caching). So nobody knew which base rule actually works best.
  Some papers also tuned parameters wrongly.
- **Method.** They treat CDC as modular (base algorithm + high-level techniques). They strip the add-ons
  and calibrate every algorithm to the same target mean chunk size µ on random data. Then they
  freeze those settings and test on realistic data.
- **Architecture.** A Rust benchmark framework reads from a RAM disk and chunks without fingerprinting. Datasets:
  RAND, WEB, DB (MySQL VM snapshots), VMB (build-server backups), CODE (source tarballs).
- **Algorithms.** Rabin, Buzhash, Gear (hash-based); AE, RAM, MII, PCI, SeqCDC (hashless); FSC as baseline.
  They derive parameter rules: AE `h ≈ µ − 256` (µ ≥ 2 KiB), RAM Eq. (2), MII Eq. (3).
  They also find that the widely copied AE formula `h = µ/(e−1)` gives chunks **13–39 % too small**.
- **Metrics.** Throughput (median + IQR over 10 runs); mean chunk size c̄ and std s; Max Err = |c̄−µ|/µ;
  Max CV = s/c̄; dedup ratio = 1 − S_dedup/S_orig; storage savings = 1 − (S_dedup + βN)/S_orig with β = 64 B.
- **Findings.** AE is the most balanced (Max Err 0.12, Max CV 0.31, savings 0.71–0.89 at µ = 2 KiB).
  Gear is the best hash-based option. RAM is fast but breaks on low-entropy data. FSC wins on block-aligned data.

## Paper 1 — Private IPFS data sanctuary

- **Problem.** Museum scan data must stay identifiable, recoverable and verifiable without depending on one workstation.
- **Method / architecture.** A private 7-node IPFS cluster (5 Raspberry Pi 5 edge nodes + 2 archive nodes) in two
  wired zones. It uses a Kademlia DHT, mDNS, a private `swarm.key`, IPFS Cluster with CRDT, and a read-only HTTP gateway.
- **Key ideas.** Each import gets a *content-derived* root CID, so failed, repeated and accepted states stay distinct.
  The stable museum UID stays at object level. The manifest keeps the root CID, the import/chunking parameters and an
  independent SHA-256. Replication (resilience) and deduplication (block reuse) are complementary.
  Capacity bound: C_unique ≲ C_raw / r.
- **Metrics.** Logical recovery/ingest rate R = S/t (182 and 368 MB/s recovery; ≈520 MB/s ingest). Block-stat probe
  latency P50/P90 per node (edge 28–30 ms P50, archive 14–15 ms). 857 node-hours of telemetry.

## Paper 3 — Leakage-abuse attacks on encrypted vector search (SAGE)

- **Problem.** Even if vectors, contents and labels are encrypted, the server still sees which record IDs are
  returned together (the access pattern).
- **Method.** Build a query–record incidence matrix, then a Jaccard-weighted co-retrieval graph. **SAGE-Dist** uses spectral groups +
  class proportions + optimal transport. **SAGE-Known** uses label propagation + anchor voting from about 1 % known labels.
- **Metrics.** Record-label accuracy, macro-F1, query-category accuracy (10 runs). Up to 84.3 % record accuracy with
  1 % known labels. Leakage persists under real DCPE encryption.
- **Defence discussed.** Identifier rotation can reduce *accumulated* leakage if cross-window linkage is prevented.

## Paper 4 — ContraSense: do VLMs really look at the image?

- **Problem.** VLM benchmarks reward common-sense priors (camels → desert), so models can score well without looking.
- **Method.** 4,698 counter-intuitive image–QA pairs. Captions are written by GPT-4.1, images generated with FLUX.1-dev,
  and everything is calibrated by humans. There are five violation types and six question dimensions.
- **Metrics.** Accuracy, F1, MCC; ROUGE-1/2/L and METEOR for generated text. **Contra-Acc** = mean over samples of
  the *worst* of the six dimension scores (an L∞ / Chebyshev view).
- **Findings.** The best closed model reaches about 60 %, open models 35–37 %, humans 96.04 %. At 64×64 resolution,
  Contra-Acc drops to 8.68 %.

---

## Step 2 — Mapping onto the project (what comes from which paper)

| Your base feature | What the project does now | From |
|---|---|---|
| Chunking + SHA-256 storage | **AE content-defined chunking** with the *corrected* horizon (h = µ − 256; 348/793 for 512/1024). Gear and FSC available via `--chunker`. Exactly the paper's base algorithms, no min/max add-ons. | **Paper 2** |
| Exact dedup (file + chunk) | Whole-file SHA-256 → `fixity:` key; per-chunk providers → `prov:` key. A one-line edit keeps most chunks (demo: AE reuses 7/9, FSC reuses 1/9). | Paper 2 (CDC), your design |
| File identity | `file_id = SHA-256(manifest)`. The manifest stores the chunk list, **chunker parameters** and an **independent SHA-256 fixity**, checked end-to-end on download. | **Paper 1 §4.1** |
| Versions | Optional **object UID** groups all content-derived versions (like museum UID → CIDs). | **Paper 1 Fig. 2** |
| Kademlia DHT, replication to k | Plus **zone-aware placement**: replicas prefer different failure zones (`--zone`). | **Paper 1** (failure domains) |
| Private network | Every `/p2p/*` request is **HMAC-signed with a shared swarm key**. There is a read-only `/gateway/<id>`. | **Paper 1** (swarm.key, gateway) |
| Heartbeats, re-replication | Unchanged idea. Plus a Kademlia **republish** and an integrity **scrub**. | your design |
| Monitoring | **Block-stat probes** (time to read + hash a local block) → P50/P90; recovery rate **R = S/t**; capacity C_raw/r. | **Paper 1 §2.2, Eq. 1, §4.4** |
| Near-dup index (dHash) | 64-bit dHash split into 4 × 16-bit **LSH bands** as DHT keys. Entries are stored under **per-epoch pseudonyms** (HMAC of file id + epoch). Only the owner can resolve a pseudonym. | **Paper 3** defence (identifier rotation) |
| Privacy evaluation | **SAGE-Known-lite** attack on our own index vs a top-k index. | **Paper 3** |
| BLIP captions | Stored with **confidence**, **reliable** flag (false if the image is < 128 px, confidence is low, or the fallback was used) and `verified: false`. | **Paper 4** |
| AI evaluation | ROUGE-1/2/L, METEOR, **Contra-Acc** (6 dimensions), and a 64×64 stress test. | **Paper 4** |
| Chunking evaluation | Throughput median/IQR, c̄, s, Max Err, Max CV, dedup ratio, storage savings (β = 64). Reproduces the AE-formula bug. | **Paper 2** |

### What was simplified (say this in the viva)

1. **Chunking in pure Python** (~10–15 MiB/s vs the paper's ~650 MiB/s in Rust). Compare *chunk statistics and rankings*, not speed.
   Rabin, Buzhash, RAM, MII, PCI and SeqCDC are not implemented. Only FSC, AE (+ legacy formula) and Gear are.
2. **Datasets are small stand-ins** (MB, not GB): RAND, CODE (stdlib tarballs with edits), DB (SQLite snapshots). WEB and VMB are omitted.
3. **Kademlia:** sequential instead of α-parallel lookups. In a small network the routing table knows every peer, so lookups finish in one hop.
4. **No IPFS Cluster / CRDT.** Replication is done by the nodes themselves (leader = live holder with the smallest node id).
5. **SAGE:** only the Known variant, with plain label propagation (no spectral grouping, no optimal transport, no anchor voting).
6. **Contra-Acc:** synthetic 6-attribute images instead of the 4,698-sample ContraSense set. By default answers are "caption-grounded"
   (is the right value in the caption?). With `--vqa`, BLIP-VQA answers six questions.
7. **METEOR:** exact matches only (no stemming/WordNet synonyms).
8. **Convergent-encryption keys** are wrapped with the swarm key. That protects against non-members (e.g. a stolen disk), not against curious members.
   The confirmation-of-file side channel still exists.
