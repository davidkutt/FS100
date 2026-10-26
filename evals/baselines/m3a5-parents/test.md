## Retrieval eval · retrieval_v1-test · `BAAI/bge-m3` · chunks 1000/150 in 2000 · dense + bm25-english, rrf:2:0.5

224 chunks from 17 documents, ingest 192.4 s · 24 questions (20 answerable) · latency p50 66 ms / p95 81 ms · USD 0.000000 per query · 3,373 characters in the top 5

Suggested `score_threshold`: **0.557** (balanced accuracy 0.95, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.95**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 20 | 0.70 | 0.95 | 0.78 | 0.81 |
| domain `ai` | 3 | 0.33 | 0.67 | 0.46 | 0.54 |
| domain `architecture` | 3 | 0.67 | 1.00 | 0.73 | 0.80 |
| domain `cloud` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `dev` | 2 | 1.00 | 1.00 | 1.00 | 0.93 |
| domain `devops` | 5 | 0.60 | 1.00 | 0.72 | 0.75 |
| domain `mlops` | 1 | 1.00 | 1.00 | 1.00 | 0.92 |
| domain `security` | 3 | 0.67 | 1.00 | 0.73 | 0.80 |
| domain `sre` | 6 | 0.50 | 1.00 | 0.67 | 0.75 |
| lang `de` | 6 | 0.67 | 1.00 | 0.76 | 0.76 |
| lang `en` | 14 | 0.71 | 0.93 | 0.79 | 0.83 |
| type PDF | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 4 | 0.75 | 1.00 | 0.83 | 0.79 |
| type direct lookup | 8 | 0.75 | 1.00 | 0.81 | 0.86 |
| type multi-chunk | 4 | 0.50 | 0.75 | 0.58 | 0.63 |
| type paraphrase | 2 | 0.50 | 1.00 | 0.75 | 0.82 |
| type whole document | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| **exact terms** | 3 | 0.33 | 1.00 | 0.50 | 0.57 |

Misses (no relevant hit in the top 5):

- `r-035` Which spans should a chat request produce in Phoenix? → runbook-llm-provider-outage.md § Runbook: LLM provider errors and outages › Symptoms (0.582)
