## Retrieval eval · followup_v1-test · `BAAI/bge-m3` · chunks 1000/150 · dense + bm25-english, rrf:2:0.5, hyde

218 chunks from 17 documents, ingest 166.8 s · 6 questions (5 answerable) · latency p50 4069 ms / p95 4492 ms · USD 0.000118 per query

Suggested `score_threshold`: **0.530** (balanced accuracy 1.00, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.80**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 5 | 0.80 | 0.80 | 0.80 | 0.80 |
| domain `cloud` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `devops` | 2 | 0.50 | 0.50 | 0.50 | 0.50 |
| domain `security` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `sre` | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `de` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| lang `en` | 4 | 0.75 | 0.75 | 0.75 | 0.75 |
| type follow-up | 5 | 0.80 | 0.80 | 0.80 | 0.80 |

Misses (no relevant hit in the top 5):

- `f-011` How do I check afterwards that it worked? → setup-startup.md § Startup guide — run FS100 locally › 4. Check that everything works (0.595)
