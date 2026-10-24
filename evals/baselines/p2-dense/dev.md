## Retrieval eval · retrieval_v1-dev · `BAAI/bge-m3` · chunks 1000/150

218 chunks from 17 documents, ingest 173.2 s · 36 questions (30 answerable) · latency p50 56 ms / p95 74 ms

Suggested `score_threshold`: **0.610** (balanced accuracy 0.87, answerable vs. unanswerable top-1 scores)

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 30 | 0.83 | 1.00 | 0.89 | 0.91 |
| domain `ai` | 6 | 0.67 | 1.00 | 0.78 | 0.82 |
| domain `architecture` | 3 | 0.33 | 1.00 | 0.56 | 0.66 |
| domain `cloud` | 3 | 0.33 | 1.00 | 0.61 | 0.71 |
| domain `db` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `dev` | 6 | 0.83 | 1.00 | 0.89 | 0.88 |
| domain `devops` | 5 | 1.00 | 1.00 | 1.00 | 0.97 |
| domain `mlops` | 3 | 0.67 | 1.00 | 0.78 | 0.78 |
| domain `security` | 4 | 1.00 | 1.00 | 1.00 | 0.98 |
| domain `sre` | 7 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `de` | 9 | 0.89 | 1.00 | 0.93 | 0.94 |
| lang `en` | 21 | 0.81 | 1.00 | 0.88 | 0.89 |
