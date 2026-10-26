## Retrieval eval · retrieval_v1-test · `BAAI/bge-m3` · chunks 1000/150 in 2000 · dense + bm25-english, rrf:2:0.5, contextual (all)

218 chunks from 17 documents, ingest 486.7 s (contexts 0.0338 USD) · 24 questions (20 answerable) · latency p50 59 ms / p95 67 ms · USD 0.000000 per query · 3,342 characters in the top 5

Suggested `score_threshold`: **0.543** (balanced accuracy 0.97, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.93**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 20 | 0.70 | 1.00 | 0.83 | 0.85 |
| domain `ai` | 3 | 0.33 | 1.00 | 0.61 | 0.65 |
| domain `architecture` | 3 | 0.33 | 1.00 | 0.58 | 0.69 |
| domain `cloud` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 0.67 | 1.00 | 0.83 | 0.86 |
| domain `dev` | 2 | 1.00 | 1.00 | 1.00 | 0.91 |
| domain `devops` | 5 | 0.80 | 1.00 | 0.90 | 0.90 |
| domain `mlops` | 1 | 0.00 | 1.00 | 0.50 | 0.69 |
| domain `security` | 3 | 0.67 | 1.00 | 0.75 | 0.83 |
| domain `sre` | 6 | 0.67 | 1.00 | 0.83 | 0.88 |
| lang `de` | 6 | 0.83 | 1.00 | 0.92 | 0.89 |
| lang `en` | 14 | 0.64 | 1.00 | 0.79 | 0.84 |
| type PDF | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 4 | 1.00 | 1.00 | 1.00 | 0.92 |
| type direct lookup | 8 | 0.75 | 1.00 | 0.88 | 0.91 |
| type multi-chunk | 4 | 0.00 | 1.00 | 0.40 | 0.52 |
| type paraphrase | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| type whole document | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| **exact terms** | 3 | 0.33 | 1.00 | 0.67 | 0.69 |
