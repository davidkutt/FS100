## Retrieval eval · retrieval_v1-dev · `BAAI/bge-m3` · chunks 1000/150 in 2000 · dense + bm25-english, rrf:2:0.5, contextual (all)

218 chunks from 17 documents, ingest 486.7 s (contexts 0.0338 USD) · 36 questions (30 answerable) · latency p50 56 ms / p95 79 ms · USD 0.000000 per query · 3,224 characters in the top 5

Suggested `score_threshold`: **0.618** (balanced accuracy 0.90, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.73**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 30 | 0.83 | 1.00 | 0.91 | 0.93 |
| domain `ai` | 6 | 0.83 | 1.00 | 0.92 | 0.94 |
| domain `architecture` | 3 | 0.67 | 1.00 | 0.83 | 0.88 |
| domain `cloud` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 0.67 | 1.00 | 0.83 | 0.88 |
| domain `dev` | 6 | 0.83 | 1.00 | 0.92 | 0.93 |
| domain `devops` | 5 | 0.60 | 1.00 | 0.77 | 0.82 |
| domain `mlops` | 3 | 0.67 | 1.00 | 0.83 | 0.88 |
| domain `security` | 4 | 0.75 | 1.00 | 0.88 | 0.91 |
| domain `sre` | 7 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `de` | 9 | 0.89 | 1.00 | 0.94 | 0.96 |
| lang `en` | 21 | 0.81 | 1.00 | 0.90 | 0.92 |
| type PDF | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 10 | 0.80 | 1.00 | 0.90 | 0.93 |
| type direct lookup | 9 | 0.89 | 1.00 | 0.94 | 0.96 |
| type multi-chunk | 6 | 0.83 | 1.00 | 0.89 | 0.92 |
| type paraphrase | 3 | 0.67 | 1.00 | 0.83 | 0.88 |
| **exact terms** | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
