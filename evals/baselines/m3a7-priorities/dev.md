## Retrieval eval · retrieval_v1-dev · `BAAI/bge-m3` · chunks 1000/150 in 2000 · dense + bm25-english, rrf:2:0.5, contextual (all), priorities priorities_v1

218 chunks from 17 documents, ingest 464.5 s (contexts 0.0433 USD) · 36 questions (30 answerable) · latency p50 56 ms / p95 73 ms · USD 0.000000 per query · 3,290 characters in the top 5

Suggested `score_threshold`: **0.608** (balanced accuracy 0.92, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.75**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 30 | 0.73 | 1.00 | 0.86 | 0.88 |
| domain `ai` | 6 | 0.83 | 1.00 | 0.92 | 0.89 |
| domain `architecture` | 3 | 0.67 | 1.00 | 0.78 | 0.81 |
| domain `cloud` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 0.33 | 1.00 | 0.67 | 0.75 |
| domain `dev` | 6 | 0.67 | 1.00 | 0.81 | 0.85 |
| domain `devops` | 5 | 0.60 | 1.00 | 0.77 | 0.82 |
| domain `mlops` | 3 | 0.67 | 1.00 | 0.83 | 0.82 |
| domain `security` | 4 | 0.50 | 1.00 | 0.75 | 0.82 |
| domain `sre` | 7 | 0.86 | 1.00 | 0.93 | 0.95 |
| lang `de` | 9 | 0.89 | 1.00 | 0.93 | 0.94 |
| lang `en` | 21 | 0.67 | 1.00 | 0.83 | 0.86 |
| type PDF | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 10 | 0.80 | 1.00 | 0.88 | 0.91 |
| type direct lookup | 9 | 0.78 | 1.00 | 0.89 | 0.92 |
| type multi-chunk | 6 | 0.67 | 1.00 | 0.81 | 0.81 |
| type paraphrase | 3 | 0.33 | 1.00 | 0.67 | 0.75 |
| **exact terms** | 3 | 1.00 | 1.00 | 1.00 | 0.94 |
| pinned `cloud/cost` | 6 | 0.83 | 1.00 | 0.92 | 0.94 |
| pinned `db/backup-restore` | 2 | 0.50 | 1.00 | 0.75 | 0.82 |
| pinned `devops/deployment` | 3 | 0.67 | 1.00 | 0.83 | 0.85 |
| pinned `mlops/model-swap` | 5 | 0.80 | 1.00 | 0.90 | 0.89 |
| pinned `security/certificates` | 1 | 0.00 | 1.00 | 0.50 | 0.63 |
| pinned `security/secrets` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| pinned `sre/capacity` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
| pinned `sre/incidents` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| pinned `sre/outages` | 5 | 0.60 | 1.00 | 0.80 | 0.84 |
| pinned `sre/slos` | 3 | 1.00 | 1.00 | 1.00 | 1.00 |
