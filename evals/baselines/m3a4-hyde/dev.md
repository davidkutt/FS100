## Retrieval eval · retrieval_v1-dev · `BAAI/bge-m3` · chunks 1000/150 · dense + bm25-english, rrf:2:0.5, hyde

218 chunks from 17 documents, ingest 157.8 s · 36 questions (30 answerable) · latency p50 4049 ms / p95 6274 ms · USD 0.000114 per query

Suggested `score_threshold`: **0.610** (balanced accuracy 0.87, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.82**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 30 | 0.93 | 1.00 | 0.96 | 0.96 |
| domain `ai` | 6 | 1.00 | 1.00 | 1.00 | 0.96 |
| domain `architecture` | 3 | 0.67 | 1.00 | 0.78 | 0.81 |
| domain `cloud` | 3 | 0.67 | 1.00 | 0.83 | 0.88 |
| domain `db` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `dev` | 6 | 0.83 | 1.00 | 0.89 | 0.89 |
| domain `devops` | 5 | 1.00 | 1.00 | 1.00 | 0.98 |
| domain `mlops` | 3 | 1.00 | 1.00 | 1.00 | 0.95 |
| domain `security` | 4 | 1.00 | 1.00 | 1.00 | 0.98 |
| domain `sre` | 7 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `de` | 9 | 0.89 | 1.00 | 0.93 | 0.94 |
| lang `en` | 21 | 0.95 | 1.00 | 0.98 | 0.96 |
| type PDF | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 10 | 0.90 | 1.00 | 0.93 | 0.95 |
| type direct lookup | 9 | 0.89 | 1.00 | 0.94 | 0.96 |
| type multi-chunk | 6 | 1.00 | 1.00 | 1.00 | 0.93 |
| type paraphrase | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| **exact terms** | 3 | 1.00 | 1.00 | 1.00 | 0.95 |
