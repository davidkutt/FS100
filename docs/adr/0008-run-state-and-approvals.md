# ADR-0008: Stateless agent turns; approvals as HMAC-signed actions with at-most-once execution

- **Status:** Proposed (M2.0 draft; accepted when M2.3 lands)
- **Date:** 2026-10-19
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
- **Proposal.** A write call ends the turn with `approval_required` and an **HMAC-signed action** over the
  user's `sub`, conversation id, tool, args hash and expiry (15 min), plus `done{stopReason:
  awaiting_approval}`. NestJS stores the action and removes `signedAction` before relaying to the browser.
- **Resume.** A decision is a new `/v1/agent` request with the transcript and `resume{signedAction,
  decision}`, sent with a freshly exchanged token. The AI service checks the signature, `sub`, expiry and
  args hash. It then either executes once and continues the loop, or adds a "user rejected" observation
  and continues.
- **State machine in NestJS:** `pending → approved | rejected | expired → executing → succeeded | failed |
  unknown`. Transitions are conditional updates, so a second click finds the row no longer `pending`.
  Before approving, NestJS re-checks that the approver is the requester and still has the role.
  A stream that breaks after `executing` without a result becomes `unknown`: shown to the user, never
  retried automatically.
- **Idempotency at the target:** `create_issue` writes a hidden marker `kb-agent:{approvalId}` into the
  issue body and searches for it before creating (`/search/issues` needs `is:issue` in `q`, otherwise 422).
- **Signing key** from env (`APPROVAL_SIGNING_KEY`), rotatable.

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
  approving, role downgrade between proposal and approval, double click (M2.3).
