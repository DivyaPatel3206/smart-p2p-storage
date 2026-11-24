# P2P network evaluation (Paper 1 metrics)

## Ingest and recovery (R = S / t)

| Workload | Size MB | Ingest MB/s | Recovery on other node MB/s | Verified |
|---|---|---|---|---|
| eval_text_1MB.bin | 1.05 | 5.17 | 21.38 | True |
| eval_random_1MB.bin | 1.05 | 5.85 | 24.65 | True |
| eval_text_4MB.bin | 4.19 | 5.53 | 30.81 | True |
| eval_random_4MB.bin | 4.19 | 7.22 | 31.87 | True |
| eval_text_16MB.bin | 16.78 | 5.93 | 41.0 | True |
| eval_random_16MB.bin | 16.78 | 6.6 | 36.03 | True |

Paper: recovery 182 and 368 MB/s (6.20 / 5.19 GB), ingest ≈520 MB/s (156.1 GB).

## Block-stat probes (local blockstore access)

| Node | Zone | Probes | P50 ms | P90 ms |
|---|---|---|---|---|
| node1 | zone-A | 16 | 0.104 | 0.156 |
| node2 | zone-B | 16 | 0.105 | 0.893 |
| node3 | zone-A | 16 | 0.09 | 0.144 |

Paper P50/P90 ms: Edge-01 28.2/87.8, Edge-04 30.0/35.6, Archive-01 15.5/18.5, Archive-02 14.3/14.9.

## Capacity

{'raw_bytes_all_nodes': 88080384, 'replication_k': 2, 'unique_bytes_estimate': 44040192, 'logical_bytes_uploaded_by_eval': 44040192, 'replication_health': '10960/10960 chunks with >= k live copies', 'rule': 'C_unique <= C_raw / r (Paper 1, Sec. 4.4)'}
