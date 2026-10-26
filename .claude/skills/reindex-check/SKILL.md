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
   To check a change of how collections are built against the old build (an upgrade), prefix the old
   settings as `LIVE_<VAR>=value` (`LIVE_SPARSE_MODEL=none` for M3a.2, `LIVE_PARENT_SIZE=0` for M3a.5): the
   uploads build the live collection with them, then the AI service restarts with `.env`'s settings before
   the re-index (+≈ 40 s). Settings missing from `.env` can be given as plain env vars.
   - Contextual retrieval (M3a.6) needs the real LLM: `REAL_LLM=1 LIVE_CONTEXTUAL_DOMAINS=
     CONTEXTUAL_DOMAINS=db,dev,cloud,devops,mlops,ai,security,architecture,sre` (uploads without contexts,
     re-index with them; ≈ 0.04 USD per build, two builds; each build ≈ 8 min instead of 3).
   - `FORCE_REASON="…"` runs the CLI re-index with `--force` and that reason.
3. Read the output; expected on the sample corpus with bge-m3, chunks 1000/150 in parents ≤ 2000:
   - no failed uploads (218 chunks since M3a.6's chunk fix), the PDF `queued → parsing → embedding → ready`
     (`contextualizing` between them when the uploads contextualize) and no `Docling failed` in `ai.log`
   - CLI run `swapped`; `test` nDCG@10 0.807 / MRR@10 0.780 / hit@5 0.95, `dev` nDCG@10 0.924 (server
     Qdrant; `evals/baselines/m3a5-parents` is in-memory, ±0.002) with `(+0.000)` against the live
     collection unless the change is meant to move them; `LIVE_PARENT_SIZE=0` gives −0.001; contextual
     (M3a.6) `kept`: `test` nDCG@10 +0.06, MRR@10 +0.07…+0.10, abstention 0.80–0.925 (−0.025…−0.15),
     contexts 0.043 USD, build ≈ 380 s — swap it with `FORCE_REASON`; the API run then reuses the stored
     contexts (no new OpenRouter calls in `ai.log`) and swaps with no blocker
   - admin `POST` 202, editor 403, both `kb.reindex` and `kb.rollback` in the audit list
   - rollbacks well under a minute; peak RSS against the D50 budget (M3a.6: idle 1.82 GB, ingest 2.39 GB,
     gate 2.60 GB; Docling's child process is not in it)
4. Logs: `$S/ai.log`, `$S/api.log`.

## Pitfalls

- `assert … check alias exists already`: a previous run was killed before its cleanup. Delete the alias
  `kb_reindex_check` and the `kb__v2__…` collections it points at in the Qdrant dashboard (:6333), then
  `docker exec fs100-postgres-1 psql -U postgres -c "drop database if exists app_reindex_check with (force)"`
  (same for `ai_reindex_check`).
- Cleanup deletes every Qdrant collection created while the script ran — don't re-index the real stack
  in parallel.
- 401 instead of 403: a token older than 5 minutes; the script logs in before each phase for that reason,
  and again while it polls a build (contextual builds take ≈ 8 min).
- `parsing` is often too short to see at a 0.2 s poll; that is not a failure.
