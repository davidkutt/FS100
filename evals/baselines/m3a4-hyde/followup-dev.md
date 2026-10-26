## Retrieval eval · followup_v1-dev · `BAAI/bge-m3` · chunks 1000/150 · dense + bm25-english, rrf:2:0.5, hyde

218 chunks from 17 documents, ingest 149.1 s · 8 questions (7 answerable) · latency p50 5348 ms / p95 10012 ms · USD 0.000143 per query

Suggested `score_threshold`: **0.562** (balanced accuracy 1.00, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.50**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 7 | 0.86 | 1.00 | 0.89 | 0.91 |
| domain `ai` | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `devops` | 2 | 0.50 | 1.00 | 0.60 | 0.69 |
| domain `mlops` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `security` | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `sre` | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `de` | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `en` | 5 | 0.80 | 1.00 | 0.84 | 0.88 |
| type follow-up | 7 | 0.86 | 1.00 | 0.89 | 0.91 |
