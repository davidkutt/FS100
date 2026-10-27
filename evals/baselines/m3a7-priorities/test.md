## Retrieval eval · retrieval_v1-test · `BAAI/bge-m3` · chunks 1000/150 in 2000 · dense + bm25-english, rrf:2:0.5, contextual (all), priorities priorities_v1

218 chunks from 17 documents, ingest 464.5 s (contexts 0.0433 USD) · 24 questions (20 answerable) · latency p50 60 ms / p95 67 ms · USD 0.000000 per query · 3,416 characters in the top 5

Suggested `score_threshold`: **0.580** (balanced accuracy 0.93, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.550: balanced accuracy **0.82**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 20 | 0.80 | 1.00 | 0.88 | 0.87 |
| domain `ai` | 3 | 1.00 | 1.00 | 1.00 | 0.87 |
| domain `architecture` | 3 | 0.33 | 1.00 | 0.57 | 0.67 |
| domain `cloud` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 0.67 | 1.00 | 0.83 | 0.86 |
| domain `dev` | 2 | 1.00 | 1.00 | 1.00 | 0.91 |
| domain `devops` | 5 | 0.80 | 1.00 | 0.87 | 0.88 |
| domain `mlops` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `security` | 3 | 0.67 | 1.00 | 0.73 | 0.81 |
| domain `sre` | 6 | 0.67 | 1.00 | 0.81 | 0.86 |
| lang `de` | 6 | 0.83 | 1.00 | 0.89 | 0.87 |
| lang `en` | 14 | 0.79 | 1.00 | 0.87 | 0.87 |
| type PDF | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 4 | 1.00 | 1.00 | 1.00 | 0.92 |
| type direct lookup | 8 | 0.88 | 1.00 | 0.92 | 0.94 |
| type multi-chunk | 4 | 0.50 | 1.00 | 0.68 | 0.65 |
| type paraphrase | 2 | 0.50 | 1.00 | 0.75 | 0.82 |
| type whole document | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| **exact terms** | 3 | 0.67 | 1.00 | 0.78 | 0.77 |
| pinned `cloud/cost` | 1 | 0.00 | 1.00 | 0.33 | 0.50 |
| pinned `db/backup-restore` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| pinned `devops/deployment` | 4 | 1.00 | 1.00 | 1.00 | 0.97 |
| pinned `mlops/model-swap` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| pinned `security/certificates` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| pinned `security/secrets` | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| pinned `sre/capacity` | 2 | 0.50 | 1.00 | 0.67 | 0.75 |
| pinned `sre/incidents` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| pinned `sre/outages` | 2 | 0.50 | 1.00 | 0.75 | 0.75 |
| pinned `sre/slos` | 2 | 0.50 | 1.00 | 0.75 | 0.82 |
