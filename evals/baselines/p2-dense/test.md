## Retrieval eval · retrieval_v1-test · `BAAI/bge-m3` · chunks 1000/150

218 chunks from 17 documents, ingest 181.5 s · 24 questions (20 answerable) · latency p50 60 ms / p95 70 ms

Suggested `score_threshold`: **0.557** (balanced accuracy 0.95, answerable vs. unanswerable top-1 scores)

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 20 | 0.65 | 0.95 | 0.77 | 0.78 |
| domain `ai` | 3 | 0.33 | 0.67 | 0.44 | 0.52 |
| domain `architecture` | 3 | 0.67 | 1.00 | 0.78 | 0.81 |
| domain `cloud` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 1.00 | 1.00 | 1.00 | 0.96 |
| domain `dev` | 2 | 1.00 | 1.00 | 1.00 | 0.81 |
| domain `devops` | 5 | 0.60 | 1.00 | 0.77 | 0.78 |
| domain `mlops` | 1 | 0.00 | 1.00 | 0.50 | 0.62 |
| domain `security` | 3 | 0.67 | 1.00 | 0.78 | 0.85 |
| domain `sre` | 6 | 0.50 | 0.83 | 0.63 | 0.72 |
| lang `de` | 6 | 0.67 | 1.00 | 0.81 | 0.75 |
| lang `en` | 14 | 0.64 | 0.93 | 0.75 | 0.79 |

Misses (no relevant hit in the top 5):

- `r-033` The LLM provider answers with HTTP 402 — what does that mean? → runbook-llm-provider-outage.md § Runbook: LLM provider errors and outages › Symptoms (0.634)
