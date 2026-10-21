# ADR-0008: Stateless agent turns; approvals as HMAC-signed actions with at-most-once execution

- **Status:** Accepted (M2.3)
- **Date:** 2026-10-19 (accepted 2026-10-20)
- **Plan reference:** D28, D39, D42 ([plan-phase-2.md §3](../../plan-phase-2.md#3-decisions))

## Context

A write tool (`github_sandbox.create_issue`, `kb.ingest_url`) must not run without the user's approval.
An approval can come minutes after the proposal and after a restart of either service. The run must
then continue where it stopped, and the write must happen at most once, even with double clicks, retries
and broken streams. NestJS already owns product data and the security boundary
([ADR-0002](0002-ai-layer-in-python.md)); the AI service has no database.

## Decision

- **Stateless turns.** NestJS is the system of record for conversations, messages, approvals, audit and
  usage. The AI service gets the transcript with every request and keeps no run state.
- **Proposal.** A write call with valid args ends the turn with `approval_required` and an **HMAC-signed
  action** (HS256 JWT) over approval id, the user's `sub`, conversation id, tool, call id, the SHA-256 of
  the validated args (canonical JSON, so `1` vs `1.0` or key order survive a round trip) and expiry
  (`APPROVAL_TTL_MIN`, 15), plus `done{stopReason: awaiting_approval}`. One write per step; further
  writes in the same step get an error observation. NestJS stores the action and removes `signedAction`
  from the relayed and the stored copy (the relay rewrites that one SSE block).
- **Resume.** A decision is a new `/v1/agent` request with the transcript up to the question and
  `resume{signed_action, decision, note?, args}` — `args` as NestJS showed them to the user. The AI
  service checks signature, expiry, `sub`, conversation and args hash **before** the stream starts
  (failure → 422, nothing runs). The resumed turn replays the `tool_call`, then executes once (after
  re-checking the role) or adds a "user rejected" observation with the note, and continues the loop.
- **State machine in NestJS:** `pending → approved | rejected | expired → executing → succeeded | failed |
  unknown`. Transitions are conditional updates, so a second click finds the row no longer `pending`.
  Before approving, NestJS re-checks that the approver is the requester (others get 404, admins too)
  and that the role still reaches the tool's `min_role` from `/v1/tools`. The write's `tool_result` in
  the continuation settles it; a 4xx from the AI service → `failed`; a stream that ends without the
  result → `unknown`: shown to the user, never retried automatically. Pending rows past `expiresAt`
  become `expired` whenever approvals are read or decided (no timer job).
- **Audit.** One `audit_log` row per `tool_result` (read and write) plus one for a write settled without
  a result, written in the answer's transaction with redacted args (secret-looking keys masked, strings
  cut to 200 chars). Append-only through a trigger that rejects UPDATE, DELETE and TRUNCATE — the API
  connects as the database owner, so revoking privileges would not bind it.
- **Idempotency at the target:** `create_issue` writes a hidden marker `kb-agent:{approvalId}` into the
  issue body and searches for it before creating (`/search/issues` needs `is:issue` in `q`, otherwise 422).
- **Signing key** from env (`APPROVAL_SIGNING_KEY`): comma-separated, the first signs, all verify, so a
  rotation keeps pending approvals valid. Unset → write calls fail closed (`stopReason: error`).

## Alternatives considered

- **Durable run state in the AI service** (paused coroutine or a run store in Redis/Postgres) — more moving
  parts for the same demo, and the AI service would need its own database and recovery.
- **Unsigned action ids** — the AI service would have to trust that NestJS never changes the args; the
  signature makes tampering detectable at the place that executes.
- **MCP Tasks extension** — not yet in the Python SDK (plan-phase-2 §2, out of scope).

## Consequences

- Restarts lose nothing; horizontal scaling (P4) needs no sticky sessions.
- Every request carries the transcript, so cost grows with history; the context builder trims it (D41).
- At-most-once needs both halves: the NestJS state machine prevents a second execution request, and the
  idempotency marker covers a request that reached GitHub but whose response was lost.
- Negative tests are part of the decision: tampered args, replayed or expired action, another user
  approving, role downgrade between proposal and approval, double click (M2.3: `tests/test_agent.py`,
  `apps/api/test/approvals.e2e-spec.ts`).
- The AI service alone cannot detect a replay within the expiry window (it is stateless); the NestJS
  state machine prevents it, and the idempotency marker covers the target (M2.5).
- Read results from the step that proposed the write are not in the resumed context (the transcript is
  text only, M2.2); the model searches again if it needs them.
