## Retrieval eval · retrieval_v1-test · `BAAI/bge-m3` · chunks 1000/150 · dense + bm25-english, rrf:2:0.5, rerank jinaai/jina-reranker-v2-base-multilingual-int8:10

218 chunks from 17 documents, ingest 164.0 s · 24 questions (20 answerable) · latency p50 1267 ms / p95 1481 ms

Suggested `score_threshold`: **0.327** (balanced accuracy 0.97, answerable vs. unanswerable top-1 scores)

At `RETRIEVAL_SCORE_THRESHOLD` 0.350: balanced accuracy **0.95**

| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall** | 20 | 0.70 | 0.85 | 0.78 | 0.81 |
| domain `ai` | 3 | 0.33 | 0.33 | 0.42 | 0.50 |
| domain `architecture` | 3 | 0.67 | 1.00 | 0.83 | 0.84 |
| domain `cloud` | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `db` | 3 | 1.00 | 1.00 | 1.00 | 0.97 |
| domain `dev` | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| domain `devops` | 5 | 0.60 | 0.80 | 0.68 | 0.72 |
| domain `mlops` | 1 | 1.00 | 1.00 | 1.00 | 0.88 |
| domain `security` | 3 | 0.67 | 1.00 | 0.83 | 0.86 |
| domain `sre` | 6 | 0.50 | 0.67 | 0.62 | 0.71 |
| lang `de` | 6 | 0.67 | 0.83 | 0.73 | 0.77 |
| lang `en` | 14 | 0.71 | 0.86 | 0.80 | 0.82 |
| type PDF | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| type cross-language | 4 | 0.75 | 1.00 | 0.81 | 0.82 |
| type direct lookup | 8 | 0.75 | 0.75 | 0.78 | 0.83 |
| type multi-chunk | 4 | 0.50 | 0.75 | 0.67 | 0.65 |
| type paraphrase | 2 | 0.50 | 1.00 | 0.75 | 0.82 |
| type whole document | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| **exact terms** | 3 | 0.33 | 0.33 | 0.41 | 0.54 |

Misses (no relevant hit in the top 5):

- `r-015` Ein Server meldet 'no space left on device' — was prüfe ich zuerst? → runbook-speicherplatz-voll.md § Runbook: Speicherplatz voll › Symptome (0.351)
- `r-033` The LLM provider answers with HTTP 402 — what does that mean? → runbook-llm-provider-outage.md § Runbook: LLM provider errors and outages › Symptoms (0.592)
- `r-035` Which spans should a chat request produce in Phoenix? → fs100-plan.md § plan.md — Phase 1: Foundation, RAG Vertical Slice, Eval & Tracing › 10. Definition of Done (Phase 1) (0.695)
