---
name: reindex-check
description: Runs upload → job states → `kb-admin reindex` gate → admin re-index → rollback end to end with the real bge-m3 on throwaway state (API :3001, AI :8001, databases app_/ai_reindex_check, Qdrant alias kb_reindex_check), samples the AI process's peak RSS, then removes only what it created — the user's kb_current and their app/ai databases stay untouched. Use when a retrieval or ingest change must pass the gate D55 ("does the re-index swap", "run kb:reindex without touching my data", "check job states end to end", "re-index memory", M3a.2–M3a.8).
---

# Re-index end to end on throwaway state

Never run `pnpm kb:reindex` or this branch's migrations against the user's stack to check a change: the
API migration and the alias swap change their data, and `main` may not run on the migrated `app` DB.

1. Preconditions: `pnpm stack:up` (Postgres, Qdrant, Keycloak healthy); ports 3001 and 8001 free (the
   `realm-check` skill uses them too); the API built from this branch: `pnpm --filter @fs100/api build`.
2. Run (≈ 10 min on the M1: model load, 17 documents ≈ 3 min, two builds ≈ 3 min each):
   ```bash
   S=<scratchpad>; uv run --directory apps/ai-service python ../../.claude/skills/reindex-check/check.py $S
   ```
   Long: start it with `run_in_background` and wait for the notification. `LLM_PROVIDER=fake`, tracing off.
   To check a change of how collections are built against the old build (an upgrade), prefix
   `LIVE_SPARSE_MODEL=none` (or another old value): the uploads build the live collection with it, then the
   AI service restarts with `.env`'s settings before the re-index (+≈ 40 s).
3. Read the output; expected on the sample corpus with bge-m3, chunks 1000/150:
   - no failed uploads, the PDF `queued → (parsing) → embedding → ready`
   - CLI run `swapped`; `test` nDCG@10 0.813 / MRR@10 0.788 / hit@5 0.95, `dev` nDCG@10 0.912
     (= `evals/baselines/m3a2-hybrid`) with `(+0.000)` against the live collection unless the change is meant
     to move them; with `LIVE_SPARSE_MODEL=none` the live side is `p2-dense` (`test` nDCG@10 +0.033)
   - admin `POST` 202, editor 403, both `kb.reindex` and `kb.rollback` in the audit list
   - rollbacks well under a minute; peak RSS against the D50 budget (M3a.2: idle 1.74 GB, ingest 2.30 GB)
4. Logs: `$S/ai.log`, `$S/api.log`.

## Pitfalls

- `assert … check alias exists already`: a previous run was killed before its cleanup. Delete the alias
  `kb_reindex_check` and the `kb__v2__…` collections it points at in the Qdrant dashboard (:6333), then
  `docker exec fs100-postgres-1 psql -U postgres -c "drop database if exists app_reindex_check with (force)"`
  (same for `ai_reindex_check`).
- Cleanup deletes every Qdrant collection created while the script ran — don't re-index the real stack
  in parallel.
- 401 instead of 403: a token older than 5 minutes; the script logs in before each phase for that reason.
- `parsing` is often too short to see at a 0.2 s poll; that is not a failure.
