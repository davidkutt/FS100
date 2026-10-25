## Retrieval eval · retrieval_v1-dev · `BAAI/bge-m3` · chunks 1000/150 · dense + bm25-english, rrf:2:0.5, rerank jinaai/jina-reranker-v2-base-multilingual-int8:10

218 chunks from 17 documents, ingest 175.8 s · 36 questions (30 answerable) · latency p50 1408 ms / p95 1516 ms

Suggested `score_threshold`: **0.363** (balanced accuracy 0.97, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.350: balanced accuracy **0.97**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 30 | 0.87 | 1.00 | 0.93 | 0.94 |
| domain `ai` | 6 | 0.67 | 1.00 | 0.83 | 0.87 |
| domain `architecture` | 3 | 0.33 | 1.00 | 0.67 | 0.75 |
| domain `cloud` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `dev` | 6 | 0.83 | 1.00 | 0.92 | 0.89 |
| domain `devops` | 5 | 0.80 | 1.00 | 0.90 | 0.91 |
| domain `mlops` | 3 | 0.67 | 1.00 | 0.83 | 0.84 |
| domain `security` | 4 | 1.00 | 1.00 | 1.00 | 0.98 |
| domain `sre` | 7 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `de` | 9 | 0.89 | 1.00 | 0.94 | 0.96 |
| lang `en` | 21 | 0.86 | 1.00 | 0.93 | 0.93 |
| type PDF | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 10 | 0.90 | 1.00 | 0.95 | 0.96 |
| type direct lookup | 9 | 0.89 | 1.00 | 0.94 | 0.96 |
| type multi-chunk | 6 | 0.67 | 1.00 | 0.83 | 0.82 |
| type paraphrase | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| **exact terms** | 3 | 1.00 | 1.00 | 1.00 | 0.96 |
