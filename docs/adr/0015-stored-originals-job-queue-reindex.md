# ADR-0015: Stored originals, a Postgres job queue and an eval-gated re-index

- **Status:** Proposed (draft, M3a.0; decided in M3a.1)
- **Date:** 2026-10-23
- **Plan reference:** D52, D53, D55 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

Every retrieval technique of Phase 3a ends with a re-index (sparse vectors, Docling parses, parent-child
chunks, chunk contexts). Phase 1 keeps no originals (D7): a re-index would need every document uploaded
again. Parsing a PDF with Docling takes tens of seconds (ADR-0018), too long for the upload request.

## Decision (proposed)

- New Postgres database `ai`, owned by the AI service: `source_documents` (original bytes ≤ 20 MB, sha256,
  parsed DoclingDocument JSON, parser + version) and the job tables. NestJS keeps metadata, ACL fields,
  priorities and approvals.
- **Procrastinate 3.10.0** for jobs, worker in the API process (shares the loaded models), queues
  `ingest` (concurrency 1), `reindex`, `curator`, `eval`; jobs idempotent per doc id + version.
- `kb-reindex` builds `kb__v2__…` from the stored originals, runs the `dev` and `test` retrieval eval and
  swaps `kb_current` only if no `test` metric drops by more than 0.02; `--rollback` re-points the alias.

## Spike notes (M3a.0)

- `procrastinate==3.10.0` resolves with the service's dependencies and the other Phase 3 pins (psycopg
  3.3.6). No spike; the worker is measured in M3a.1.
- Baselines for the gate: `evals/baselines/p2-dense/` — `retrieval_v1` split into `dev` (36) and `test`
  (24) per D51.
- Memory (D50, `pnpm mem`): see the M3a.0 notes in `plan-phase-3.md`. An in-process worker carries every
  model the jobs load; Docling's ~2 GB peak is why ADR-0018 parses in a child process.

## Alternatives considered

- **pg-boss in NestJS** — splits the pipeline across two languages; the work is Python.
- **Redis-based queue (arq, RQ)** — one more service on a 16 GB laptop; Postgres is already there.
- **Separate worker process now** — would load bge-m3 a second time (~2.3 GB); comes as its own
  Deployment in Phase 4.

## Consequences

To be written in M3a.1.
