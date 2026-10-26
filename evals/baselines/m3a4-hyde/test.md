## Retrieval eval · retrieval_v1-test · `BAAI/bge-m3` · chunks 1000/150 · dense + bm25-english, rrf:2:0.5, hyde

218 chunks from 17 documents, ingest 165.0 s · 24 questions (20 answerable) · latency p50 3576 ms / p95 4817 ms · USD 0.000101 per query

Suggested `score_threshold`: **0.557** (balanced accuracy 0.95, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.95**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 20 | 0.70 | 1.00 | 0.85 | 0.87 |
| domain `ai` | 3 | 0.33 | 1.00 | 0.67 | 0.74 |
| domain `architecture` | 3 | 0.67 | 1.00 | 0.83 | 0.87 |
| domain `cloud` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `dev` | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `devops` | 5 | 0.80 | 1.00 | 0.90 | 0.85 |
| domain `mlops` | 1 | 0.00 | 1.00 | 0.50 | 0.69 |
| domain `security` | 3 | 0.67 | 1.00 | 0.83 | 0.87 |
| domain `sre` | 6 | 0.50 | 1.00 | 0.75 | 0.82 |
| lang `de` | 6 | 0.83 | 1.00 | 0.92 | 0.87 |
| lang `en` | 14 | 0.64 | 1.00 | 0.82 | 0.87 |
| type PDF | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 4 | 1.00 | 1.00 | 1.00 | 0.90 |
| type direct lookup | 8 | 0.75 | 1.00 | 0.88 | 0.91 |
| type multi-chunk | 4 | 0.25 | 1.00 | 0.62 | 0.72 |
| type paraphrase | 2 | 0.50 | 1.00 | 0.75 | 0.82 |
| type whole document | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| **exact terms** | 3 | 0.33 | 1.00 | 0.67 | 0.75 |
