## Retrieval eval · retrieval_v1-dev · `BAAI/bge-m3` · chunks 1000/150 in 2000 · dense + bm25-english, rrf:2:0.5

224 chunks from 17 documents, ingest 182.4 s · 36 questions (30 answerable) · latency p50 59 ms / p95 79 ms · USD 0.000000 per query · 3,601 characters in the top 5

Suggested `score_threshold`: **0.614** (balanced accuracy 0.88, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.82**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 30 | 0.83 | 1.00 | 0.92 | 0.92 |
| domain `ai` | 6 | 1.00 | 1.00 | 1.00 | 0.96 |
| domain `architecture` | 3 | 0.67 | 1.00 | 0.83 | 0.81 |
| domain `cloud` | 3 | 0.67 | 1.00 | 0.83 | 0.88 |
| domain `db` | 3 | 0.67 | 1.00 | 0.83 | 0.88 |
| domain `dev` | 6 | 0.67 | 1.00 | 0.83 | 0.87 |
| domain `devops` | 5 | 0.80 | 1.00 | 0.90 | 0.90 |
| domain `mlops` | 3 | 1.00 | 1.00 | 1.00 | 0.96 |
| domain `security` | 4 | 0.50 | 1.00 | 0.75 | 0.82 |
| domain `sre` | 7 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `de` | 9 | 0.89 | 1.00 | 0.94 | 0.96 |
| lang `en` | 21 | 0.81 | 1.00 | 0.90 | 0.91 |
| type PDF | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 10 | 0.80 | 1.00 | 0.90 | 0.93 |
| type direct lookup | 9 | 0.78 | 1.00 | 0.89 | 0.92 |
| type multi-chunk | 6 | 0.83 | 1.00 | 0.92 | 0.87 |
| type paraphrase | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| **exact terms** | 3 | 1.00 | 1.00 | 1.00 | 0.96 |
