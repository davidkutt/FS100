# FS100 system card (stub)

> **Status:** stub as of Phase 2 (M2.7, 2026-10-22). It grows with every phase and becomes a full system
> card in Phase 6. Numbers come from the eval runs named below; re-run them before quoting.

## What it is

An assistant for software, platform and operations engineers. It answers from a curated knowledge base
(runbooks, ADRs, setup guides, handbooks) and from one GitHub repository, with numbered citations, and it
can propose two writes — add a document from a URL (`kb.ingest_url`) or open an issue in a sandbox repo
(`github_sandbox.create_issue`) — which run only after the user approves them.

- **Intended use:** a self-hosted, single-team demo; questions about the team's own systems and decisions.
- **Out of scope:** general knowledge (the agent abstains instead), legal, medical or HR advice, autonomous
  changes to infrastructure, untrusted multi-tenant use (no per-document ACL before Phase 3b).

## Components and models

| Part | Choice | Record |
|---|---|---|
| LLM (chat, agent) | `openai/gpt-6-luna` via OpenRouter by default; per-conversation picker from `config/models.yaml` (DeepSeek V4.1 Flash, Claude Haiku 5.5 for editors) | [ADR-0005](adr/0005-llm-access-and-model.md), [ADR-0007](adr/0007-agent-harness-and-limits.md) |
| Embeddings | `BAAI/bge-m3`, in process, chunks 1000/150 inside sections of ≤ 2000 characters; the LLM gets the section | [ADR-0004](adr/0004-embedding-model-chunking-threshold.md), [ADR-0018](adr/0018-docling-parent-child-chunking.md) |
| Retrieval | hybrid: dense + BM25, weighted RRF; abstains when the best hit's cosine similarity is below 0.55. Reranker off by default; the opt-in `jinaai/jina-reranker-v2-base-multilingual` (int8) is **CC BY-NC 4.0 (non-commercial)**, the Apache-2.0 alternative is in ADR-0017. HyDE on request per search (`strategy: hyde`: the LLM drafts a passage that is searched too; plan-phase-3.md M3a.4) | [ADR-0016](adr/0016-hybrid-search-sparse-side.md), [ADR-0017](adr/0017-reranker.md) |
| PDF parsing | Docling 2.141 without OCR, in a child process per document: layout model `docling-project/docling-layout-heron` (Apache-2.0), TableFormer `docling-project/docling-models` (CDLA-Permissive-2.0 / Apache-2.0); pypdf when it fails or takes over 300 s. Scanned PDFs have no text | [ADR-0018](adr/0018-docling-parent-child-chunking.md) |
| Domain router | embedding similarity to the domain descriptions; LLM classifier opt-in | [ADR-0012](adr/0012-embedding-vs-llm-router.md) |
| Agent | own loop, no framework; agentic RAG by default, plain RAG as baseline | [ADR-0007](adr/0007-agent-harness-and-limits.md), [ADR-0011](adr/0011-plain-vs-agentic-rag.md) |
| Prompts | versioned files, `id@version` + hash on every message, trace and eval run | [ADR-0013](adr/0013-prompt-versioning.md) |

## Data

- **Corpus:** public or self-written documents only (plan.md D25); uploads are tagged with domains and
  optional sub-topics. Documents uploaded by users are visible to every user of the deployment.
- **Sent to the LLM provider (OpenRouter):** the question, recent conversation turns, retrieved chunks and
  tool results — including issues, runs and code of the configured public GitHub repo (D47). At ingest,
  documents of `CONTEXTUAL_DOMAINS` go there **whole**, once per chunk (contextual retrieval,
  [ADR-0019](adr/0019-contextual-retrieval-chunk-topics.md)); `CONTEXTUAL_DOMAINS` empty sends none.
- **Stored (Postgres `ai`):** uploaded originals, their parses and chunk contexts (D52, D60), deleted with
  the document.
- **Stored (Postgres `app`):** conversations and messages with tool parts (90-day retention planned, not
  enforced yet), approvals, an append-only audit log of every tool call with redacted arguments, per-turn
  usage and feedback. No secrets in tool context; GitHub tokens are least-privilege service identities.

## Safeguards

- **Approvals:** no write runs without the requester's approval; HMAC-signed actions, at-most-once state
  machine, idempotency marker at the target ([ADR-0008](adr/0008-run-state-and-approvals.md)).
- **Roles:** viewer, editor, admin from Keycloak; enforced server-side for tools, approvals and
  conversations; identity travels as exchanged tokens on every internal hop
  ([ADR-0009](adr/0009-token-exchange-internal-hops.md)).
- **Untrusted tool output:** every tool result is wrapped, truncated and labelled as data; GitHub MCP server
  read-only with lockdown mode; external tools allow-listed; URL fetches host-allow-listed with an SSRF guard.
- **Limits and cost:** per run max 8 steps, 120 s, 60 k input tokens, 0.05 USD; per user and UTC day
  0.20 / 1.00 / 5.00 USD for viewer / editor / admin (`429` once reached); the OpenRouter key limit is the
  backstop.
- **Observability:** one Phoenix trace per turn across the MCP hop; admin pages for the audit log and usage;
  gap signals (`answerStatus`, `topScore`) and thumbs up/down on every answer.

## Evaluation (Phase 2 baselines)

| Eval | Set | Result | Source |
|---|---|---|---|
| Retrieval | `retrieval_v1` (60 questions, DE + EN, 10 unanswerable) | hit@5 0.98 · nDCG@10 0.86 (blocking in CI, tolerance 0.02) | [evals/README.md](../evals/README.md) |
| Agent tasks | `agent_v1` (34 tasks, 3 repeats, fixture GitHub server) | success 0.82 · tool precision 0.95 / recall 0.99 · 0.08 ct and 5.3 s p50 per turn | plan-phase-2.md M2.6 |
| Red team | `redteam_v0` (15 cases: injection, exfiltration, tool misuse, goal hijack) | forbidden-tool checks 1.00 · success 0.98 | plan-phase-2.md M2.6 |
| Plain vs agentic RAG | golden set | 0.87 vs 0.83 (within noise), agentic at 7× the cost | [ADR-0011](adr/0011-plain-vs-agentic-rag.md) |

## Known limitations

- Cross-language retrieval is dense-only: an English question can miss the German disk-full runbook
  (`a-023`); hybrid search follows in Phase 3a.
- When the knowledge base has only a near miss, the agent sometimes cites it, so the answer counts as
  `answered` instead of `abstained` (`a-019`, `a-020`).
- The agent sometimes asks for confirmation in chat instead of proposing the write, and once offered a
  viewer a write the viewer cannot run (the harness denies it; `a-031`, `a-033`).
- Cost caps depend on the cost the provider reports; a model without cost data is not capped by cost.
- No output guardrails, no per-document access control and no judge-based answer eval yet (Phase 3b).
