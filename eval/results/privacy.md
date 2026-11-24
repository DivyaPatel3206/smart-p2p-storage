# Leakage of the near-duplicate index (Paper 3 metrics)

| Setting | Record-label acc | Macro-F1 | Query-category acc | Coverage | Acc on reached | Majority baseline |
|---|---|---|---|---|---|---|
| top-10 (Paper 3 setting), known=1%, no rotation | 0.366 ± 0.114 | 0.106 | 0.353 | 1.00 | 0.366 | 0.343 |
| top-10 (Paper 3 setting), known=1%, rotation x4 | 0.358 ± 0.112 | 0.102 | 0.363 | 1.00 | 0.358 | 0.343 |
| top-10 (Paper 3 setting), known=1%, rotation x16 | 0.320 ± 0.107 | 0.087 | 0.333 | 1.00 | 0.320 | 0.343 |
| top-10 (Paper 3 setting), known=5%, no rotation | 0.607 ± 0.011 | 0.406 | 0.667 | 1.00 | 0.607 | 0.343 |
| top-10 (Paper 3 setting), known=5%, rotation x4 | 0.536 ± 0.014 | 0.353 | 0.626 | 1.00 | 0.536 | 0.343 |
| top-10 (Paper 3 setting), known=5%, rotation x16 | 0.439 ± 0.018 | 0.264 | 0.544 | 1.00 | 0.439 | 0.343 |
| band index (ours), known=1%, no rotation | 0.348 ± 0.006 | 0.052 | 0.366 | 0.10 | 0.223 | 0.343 |
| band index (ours), known=1%, rotation x4 | 0.372 ± 0.011 | 0.054 | 0.366 | 0.00 | 0.333 | 0.343 |
| band index (ours), known=1%, rotation x16 | 0.413 ± 0.023 | 0.058 | 0.366 | 0.00 | 0.333 | 0.343 |
| band index (ours), known=5%, no rotation | 0.385 ± 0.027 | 0.109 | 0.424 | 0.25 | 0.530 | 0.343 |
| band index (ours), known=5%, rotation x4 | 0.389 ± 0.023 | 0.082 | 0.398 | 0.08 | 0.693 | 0.343 |
| band index (ours), known=5%, rotation x16 | 0.423 ± 0.032 | 0.077 | 0.391 | 0.08 | 0.706 | 0.343 |

Coverage = share of observed records connected (through co-retrieval) to at least one known label. Records that are not reached get the majority guess.

Paper 3 reference: SAGE-Known up to 84.3 % record-label accuracy with 1 % known labels on top-k encrypted vector search.
