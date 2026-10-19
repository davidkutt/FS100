# Runbook: Swap the embedding model

Owner: AI engineering · Applies to: the AI service and its Qdrant collections · Last reviewed: 2026-10

## Background

Vectors from different embedding models are not comparable. Every model therefore gets its own Qdrant
collection, named `kb__<model-slug>__<dimension>`, and the AI service reads and writes through the
alias `kb_current`. Changing `EMBEDDING_MODEL` makes the service create the new collection on startup
and point the alias at it — which is empty until the documents are re-ingested.

## Before you switch

1. Run the retrieval benchmark with the candidate model:
   `pnpm eval:retrieval --model <candidate> --model <current>`.
2. The candidate must not be worse on hit@5 and nDCG@10 overall, and not worse by more than 0.05 in any
   domain or language slice.
3. Re-calibrate `RETRIEVAL_SCORE_THRESHOLD`: scores of different models live on different scales, so the
   old threshold is meaningless for the new model.
4. Record the numbers and the decision in an ADR.

## Switch

1. Set `EMBEDDING_MODEL` and the new `RETRIEVAL_SCORE_THRESHOLD`, restart the AI service.
2. Re-ingest every document (the documents API re-sends the stored originals; in Phase 1 upload them
   again).
3. Check the Qdrant dashboard: the new collection's point count matches the old one's.

## Roll back

Set `EMBEDDING_MODEL` back to the old value and restart. The service points `kb_current` at the old
collection again, which was never touched. Keep the old collection for **seven days** after a swap, then
delete it to free memory.

## Pitfalls

- E5 models need the `query: ` and `passage: ` prefixes; without them quality drops sharply. The
  embedder applies them automatically for every model id containing `e5`.
- Larger models are slower on CPU: check p95 search latency and ingest time in the benchmark output, not
  only the quality metrics.
- The model download happens on first start; the readiness probe stays red until the model is loaded.
