# AI metadata quality (Paper 4 metrics)

Caption model: `fallback-colour-heuristic`, Contra-Acc mode: caption-grounded

| Resolution | ROUGE-1 | ROUGE-2 | ROUGE-L | METEOR* | Contra-Acc | Mean acc |
|---|---|---|---|---|---|---|
| full | 0.3158 | 0.0 | 0.2105 | 0.1515 | 0.0 | 0.2194 |
| 64x64 | 0.3158 | 0.0 | 0.2105 | 0.1515 | 0.0 | 0.2194 |

Summariser `fallback-extractive`: ROUGE-1 0.2787, ROUGE-2 0.0613, ROUGE-L 0.2035

*METEOR simplified: exact matches only (no stemming/synonyms).

Paper 4 reference: strongest closed-source model ≈60 % Contra-Acc, humans 96.04 %, 8.68 % at 64×64.
