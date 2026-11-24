# Five likely viva questions (with answers you can say in your own words)

### 1. Why content-defined chunking (AE) instead of fixed-size chunks? Why h = µ − 256?
Fixed-size chunking has the **boundary-shift problem**. Insert one byte and every later chunk
boundary moves, so nothing after the edit matches. In our demo a one-sentence insertion
let FSC reuse **1 of 9** chunks, while AE reused **7 of 9**.
AE puts a cut where a byte is the maximum of the next *h* bytes. So boundaries depend on content and
re-synchronise after an edit. The base paper (Gregoriadis et al.) found AE the most balanced base
algorithm and showed that the old rule h = µ/(e−1) is wrong. For a large horizon the maximum byte is almost
always 255, and the chance that a new byte equals it is 1/256. So the average chunk is about h + 256, giving
h = µ − 256. Our evaluation reproduces both results: AE gives c̄ = 2056 B, s = 254 B on random
data (paper: 2048, 252). The legacy formula gives chunks **11.8–38.9 % too small** (paper: 13–39 %).

### 2. How does a node know a chunk already exists somewhere in the network, with no central server?
Each chunk is named by its SHA-256 hash. The key `prov:<hash>` is stored on the k nodes whose
256-bit IDs are **XOR-closest** to SHA-256 of the key (Kademlia). Before sending a chunk, the
uploading node asks those nodes (one batched request per node) whether a provider record exists. If yes,
it skips the chunk. A whole-file SHA-256 under `fixity:<hash>` catches exact file copies in one
lookup. Lookups cost O(log n) hops in general. In our 3-node network the routing table already knows everyone, so it is one hop.

### 3. What happens when a node fails? How do you know data is not corrupted?
Every node pings its peers every 3 s. A peer silent for 10 s is marked dead. In the maintenance
loop each node counts the live holders of every chunk it stores. If fewer than k remain, the live holder
with the **smallest node ID** (a deterministic leader, so only one node does it) copies the chunk to the
next responsible node. Demo step 7 kills node2 and downloads still succeed. Integrity: every chunk is
re-hashed when it is read and when it is received. A periodic scrub deletes corrupted local copies, and the
manifest's independent SHA-256 checks the whole file end-to-end (Paper 1's "fixity" idea). Demo step 8
corrupts a block on disk and the download still returns the correct file from another replica.

### 4. How does near-duplicate detection work on a DHT that only supports exact lookups? Is it private?
dHash shrinks the image to 9×8 grey pixels and compares neighbours, giving 64 bits. Near-duplicates have a
small Hamming distance (threshold 10). We split the hash into **4 bands of 16 bits** and store the image
under each band. If two hashes differ in ≤ 3 bits, at least one band must be identical (pigeonhole),
so the lookup finds it. Candidates are then verified locally with the real Hamming distance.
Results: resize, JPEG and blur give recall 1.0 with no false positives at T = 10. A 5 % crop or 3° rotation drops to
about 0.56, and a mirror flip fails. Privacy: Paper 3 shows that a server seeing which IDs are returned
together can infer categories. Our simplified SAGE attack reaches **60.7 %** on a top-10 index (5 % known
labels). On our band index it only reaches 25 % of records (accuracy near the 34 % majority baseline).
**Per-epoch pseudonyms** (identifier rotation) further cut the top-10 leak to 43.9 %.

### 5. Why run the AI only on the uploading node, and can we trust the captions?
Inference is the most expensive step, so we compute it **once**. The result goes into the DHT
(`ai:<file_id>`), every peer reads it, and an exact-duplicate upload reuses it without re-running the model.
Trust: Paper 4 (ContraSense) shows that even strong vision-language models score only about 60 % on counter-intuitive images
and collapse at 64×64. So every caption is stored with a confidence value (geometric-mean token
probability), `reliable = false` for images under 128 px, and `verified = false`. We evaluate captions with
ROUGE-1/2/L, METEOR and Contra-Acc (the worst of six attribute dimensions), plus a 64×64 stress test.
Summaries are evaluated with ROUGE.
