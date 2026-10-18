# ADR-0005: LLM access via one OpenAI-compatible adapter; dev/demo model

- **Status:** Accepted
- **Date:** 2026-10-17
- **Plan reference:** D11, D12, D21, D24, D25

## Context

Grounded chat (M1.3) needs a hosted LLM that streams, reports token usage and cost, and can be swapped
between OpenRouter, the Hugging Face router and a free deterministic stand-in by changing env vars only.
Tokens are paid by the developer (D24); no agent framework through Phase 2 (D11); every call must show up
in Phoenix (D21).

## Decision

**One protocol, two providers** (`apps/ai-service/src/ai_service/llm.py`):

- `LlmProvider.stream_chat(messages) → AsyncGenerator[LlmEvent]`, events `Token | Usage | LlmError`
  (Phase 2 adds tool calls). Messages use the OpenAI chat format — every target speaks it.
- **`openai_compat`** on the raw `openai` SDK with `LLM_BASE_URL`: `max_tokens = LLM_MAX_OUTPUT_TOKENS`,
  `timeout = LLM_TIMEOUT_S`, the SDK's own retries (3, exponential backoff, 408/409/429/5xx and connection
  errors — only before the first token), `stream_options.include_usage` for token counts. OpenRouter's
  `usage.cost` becomes `costUsd` in the `done` event and the request log; other endpoints give `null`.
  API errors (401 key, 402 credit limit, 429 after retries) become one SSE `error` event.
- **`fake`**: deterministic, cites every source it gets; the default when `LLM_PROVIDER` is unset, so tests
  and CI never spend tokens. `openai_compat` without `LLM_API_KEY` or `LLM_MODEL` fails at startup.
- **Cancellation:** a client disconnect closes the provider's async generator (`contextlib.aclosing`),
  which closes the HTTP stream to the LLM; OpenRouter then stops generation for providers that support
  stream cancellation.
- **Tracing:** `openinference-instrumentation-openai` adds an LLM span (prompt, completion, tokens) under
  the `chat` span, next to `search` and `embed`.

**Prompt** (`rag.py`, snapshot in `tests/fixtures/chat-prompt.txt`): system rules (answer only from the
sources, otherwise say it is not in the knowledge base, reply in the question's language, cite as `[n]`,
sources are untrusted data); the sources go into the last user message inside `<source n="…">` tags, with
any such tags removed from document text so a document cannot close its block; history is trimmed to
~2000 tokens (4 chars per token estimate), newest first. Retrieval uses the last user message only (query
rewriting is Phase 3).

**Model:** dev model **`openai/gpt-6-luna`** (`.env.example`), demo model **`deepseek/deepseek-v4.1-flash`**.

## Manual quality pass

10 golden questions (`r-002 r-007 r-011 r-014 r-016 r-024 r-028 r-033 u-003 u-005`: 5 DE, 5 EN, two
unanswerable) through the real chat pipeline — corpus in in-memory Qdrant, `bge-m3`, top 5, threshold
0.55, `LLM_MAX_OUTPUT_TOKENS=800`, OpenRouter, 2026-10-17. Prices are OpenRouter list prices in USD per
1M tokens in / out; cost is what OpenRouter reported for all 10 answers.

| Model | Price in / out | Cost (10 answers) | TTFT p50 / max | Total p50 | Output tokens median / max | Invalid citations |
|---|---|---|---|---|---|---|
| **`openai/gpt-6-luna`** | 0.10 / 0.50 | **0.12 ct** | 1.5 / 2.6 s | 1.8 s | 80 / 207 | 0 |
| `deepseek/deepseek-v4.1-flash` | 0.024 / 0.72 | 0.32 ct | 1.3 / 1.9 s | 1.9 s | 183 / 481 | 0 |
| `anthropic/claude-haiku-5.5` | 0.10 / 0.50 | 0.30 ct | 1.5 / 4.6 s | 2.3 s | 326 / **800** | 0 |

Notes:

- **All three** answered in the question's language (also DE question → EN source), cited only existing
  sources, did the error-budget arithmetic in r-014 correctly (3 h 22 min per 28 days) and declined both
  unanswerable questions.
- **r-033 (HTTP 402) failed for all three — a retrieval miss, not a model fault:** the runbook section
  "Triage by status code" (table row "402 = credit limit reached") scored below the 0.55 threshold, so
  only 4 other chunks came back and every model said the sources do not define 402. Candidate for
  Phase 3 (table-aware chunking, hybrid search, reranking).
- **gpt-6-luna:** shortest correct answers, cheapest and never near the cap; terse on procedures (r-002
  gave the commands without the decide/announce steps).
- **deepseek-v4.1-flash:** the most complete answers (full rollback procedure, safe alternatives in
  r-016) — better for demos; occasionally opens with an awkward hedge (r-014).
- **claude-haiku-5.5:** reasons adaptively (an encrypted `reasoning_details` block) and the reasoning
  counts against `max_tokens`: r-002 used all 800 tokens and showed only a few words; two replays of the
  same prompt used 666 and 709 tokens. Also adds advice beyond the sources ("check your HR documents").
  Not chosen; it would need a higher cap.

At ~0.012 ct per dev answer, a 10 USD key limit lasts ~80 000 chat turns.

## Alternatives considered

- **LiteLLM** — one more abstraction over the same OpenAI format; hides what Phase 1 wants to learn (D11).
- **Native vendor SDKs** — a second adapter per vendor; only worth it for a feature OpenRouter cannot reach.
- **LangChain / agent frameworks** — excluded through Phase 2 (D11).
- **Exact token counting (tiktoken)** — tokenizers differ per routed model; the estimate is enough for a
  history budget.

## Consequences

- Provider switch is env-only: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (or `LLM_PROVIDER=fake`).
- Cost per request is visible in the `done` event, the AI-service log and the Phoenix trace.
- OpenRouter forwards prompts, including retrieved chunks, to third-party providers — only public or
  self-written documents go into the corpus (D25).
- Pinned model ids still drift when OpenRouter routes to another provider: re-run the manual pass when
  switching models.
- A truncated answer (output tokens = `LLM_MAX_OUTPUT_TOKENS`) is not flagged to the client yet; watch for
  it with reasoning models.
