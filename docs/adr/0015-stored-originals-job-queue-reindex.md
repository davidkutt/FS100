# ADR-0015: Stored originals, a Postgres job queue and an eval-gated re-index

- **Status:** Accepted (M3a.1)
- **Date:** 2026-10-24
- **Plan reference:** D52, D53, D54, D55 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

Every retrieval technique of Phase 3a ends with a re-index (sparse vectors, Docling parses, parent-child
chunks, chunk contexts). Phase 1 keeps no originals (D7): a re-index would need every document uploaded
again. Parsing a PDF with Docling takes tens of seconds (ADR-0018), too long for the upload request, and
the Phase 1 background task in NestJS died with the process.

## Decision

- **Originals in Postgres `ai`, owned by the AI service** (`source_documents`: doc id, version, sha256,
  mime, size, `bytea` ≤ 20 MB). The AI service creates the database on boot if it is missing, so an
  existing volume needs no reset, and applies its own migrations (a `schema_migrations` table, an advisory
  lock; Procrastinate's schema is migration 0001). NestJS keeps metadata, ACL fields and the product
  status. The same bytes again keep their version, new bytes get the next one.
- **Procrastinate 3.10.0, worker inside the API process** (`JOBS_INPROCESS_WORKER`, one job at a time:
  parsing and embedding peak inside jobs, D50). Queues `ingest`, `reindex`, `maintenance`; `curator` and
  `eval` come with their milestones. Ingest and re-index share the lock `kb`, so a build never misses a
  document upserted meanwhile. Retries with backoff for transient errors (3 attempts), none for a
  document that cannot be parsed. A periodic task retries jobs whose worker stopped sending heartbeats
  (crash, `kill -9`). Progress per stage in `job_progress`; only the queue's own status ends a job.
- **Idempotent per document version:** point ID = UUIDv5(`doc_id:version:chunk_index`); an ingest
  upserts, then deletes the document's points of other versions or past its last chunk. Running a job
  again changes nothing.
- **`POST /v1/documents` → `202 {job_id, version}`, `GET /v1/jobs/{id}`.** NestJS copies the job's state
  (`queued → parsing → embedding → ready | failed`) into the row when documents are read. Deleting a
  `queued` document cancels its job; a running one answers 409. `POST /v1/ingest` is gone.
- **Collection v2** `kb__v2__{model}__{dim}__{build time}` with the D54 payload fields and indexes. The
  alias moves only through a re-index; on boot the service creates a collection only if the alias is
  missing.
- **Re-index (`kb-admin reindex`, `POST /v1/reindex`, admin page):** build from the stored originals
  with the live collection's labels → reconcile documents deleted or relabelled during the build →
  golden `dev` + `test` against the new and the live collection → swap only if no `test` metric
  (hit@5, MRR@10, nDCG@10, abstention accuracy at `RETRIEVAL_SCORE_THRESHOLD`) drops by more than 0.02
  and every live document has an original. A refused build is deleted; the report stays with the job.
  `--force` needs a reason. A different embedding model cannot be compared and always needs `--force`.
- **Rollback** points the alias at the collection the last swap to the live one replaced (from the run
  reports). Deletes and relabels reach every `kb__*` collection, so a rollback cannot bring back a
  deleted document or old labels.
- **Audit:** starts and rollbacks through NestJS (`/api/admin/reindex`) are `audit_log` rows
  (`kb.reindex`, `kb.rollback`). The CLI has no user token: its runs record `cli:<os user>` and the
  reason in the run report only.

Verified on throwaway state with bge-m3 (plan-phase-3.md M3a.1 notes): 17 documents through the queue in
177 s; a re-index from the stored originals in 188 s that reproduces the `p2-dense` baselines exactly
(`test` nDCG@10 0.780); rollback in 0.04 s (API) / 1.0 s (CLI). Embedding batches of 16 cut the ingest
peak from 3.84 GB to 2.52 GB at the same speed; the service with its worker peaks at 2.13 GB.

## Spike notes (M3a.0)

- `procrastinate==3.10.0` resolves with the service's dependencies and the other Phase 3 pins (psycopg
  3.3.6).
- Baselines for the gate: `evals/baselines/p2-dense/` — `retrieval_v1` split into `dev` (36) and `test`
  (24) per D51.
- Memory (D50, `pnpm mem`): see the M3a.0 notes in `plan-phase-3.md`. An in-process worker carries every
  model the jobs load; Docling's ~2 GB peak is why ADR-0018 parses in a child process.

## Alternatives considered

- **pg-boss in NestJS** — splits the pipeline across two languages; the work is Python.
- **Redis-based queue (arq, RQ)** — one more service on a 16 GB laptop; Postgres is already there.
- **Separate worker process now** — would load bge-m3 a second time (~2.3 GB); comes as its own
  Deployment in Phase 4.
- **Gate against the stored baseline file** instead of the live collection — the live corpus includes
  uploads beyond `data/sample-docs/`, and the baseline would go stale after every accepted swap.
- **Labels stored with the originals** — a third copy next to NestJS and the Qdrant payload, kept in
  sync on every relabel; the live payload already is the AI service's copy.
- **A NestJS poller for job states** — reading on demand needs no timer; rows nobody looks at stay stale
  until the next read.

## Consequences

- A re-index needs no re-upload; documents indexed before M3a.1 need `pnpm kb:backfill-originals` once
  (found in `data/sample-docs/` by SHA-256), the others block the swap until uploaded again.
- The AI service now needs Postgres at startup. Uploads wait (`queued`) while a re-index runs.
- Replaced collections are kept and never deleted automatically (the 14 days of D55 are a minimum);
  delete them by hand in the Qdrant dashboard when disk matters.
- Upgrading Procrastinate means adding its migration SQL as our next migration.
- The gate compares dense retrieval only; M3a.2+ evaluate through the same function, so the gate follows
  the retrieval pipeline that serves.
