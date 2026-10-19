# ADR-0007: Own agent harness with hard limits; dev model for agent mode

- **Status:** Proposed (M2.0 draft; accepted when M2.1 lands)
- **Date:** 2026-10-19
- **Plan reference:** D11, D27, D40, D41 ([plan-phase-2.md §3](../../plan-phase-2.md#3-decisions))

## Context

Phase 2 turns grounded chat into an agent: the model decides whether and where to search and calls tools
from the own MCP server and the GitHub MCP server. No agent framework through Phase 2 (D11), so the loop
is ours. Tokens are user-funded (D24), and a tool loop can run away in steps, time and cost. The
`LlmProvider` from [ADR-0005](0005-llm-access-and-model.md) streams tokens and usage but no tool calls
yet.

## Decision

- **Own loop** in `apps/ai-service/src/ai_service/agent/` on the existing `LlmProvider` (raw `openai` SDK,
  OpenRouter). The provider gains `tools`, `tool_choice`, streamed tool-call delta assembly and usage
  with cached tokens.
- **Limits** (env, D27 defaults): `max_steps=8`; at most 4 parallel calls, **read tools only**; per-tool
  timeout 20 s; run wall clock 120 s; run input-token budget 60 k; run cost cap 0.05 USD (dev). Each limit
  ends the run with its own `stopReason`.
- **Errors are observations:** a failed tool call goes back to the model as a tool result; transient
  errors are retried ≤ 2× with backoff.
- **Requests** send `provider.require_parameters=true` and `session_id=<conversationId>`, but **not**
  `parallel_tool_calls`: none of the three candidates lists it on OpenRouter, so with
  `require_parameters` it would filter out every provider. All three make parallel calls without it; the
  harness enforces the cap.
- **Dev model for agent mode: `openai/gpt-6-luna`** (unchanged from ADR-0005). Fallback:
  `anthropic/claude-haiku-5.5`. Re-checked with the agent eval (M2.6, 3 repeats).

## Tool-calling shortlist (M2.0)

3 models × 5 scripted prompts, one run each, streamed, `max_tokens=400`, 4 strict function tools
(`kb_search_knowledge_base`, `kb_list_sources`, `github_actions_list`, `github_sandbox_create_issue`),
OpenRouter, 2026-10-19. Prompts: **single** (one KB search), **parallel** (CI run + runbook in one turn),
**schema** (enum array args), **no_tool** (small talk), **inject** (a tool result tells the model to call
the write tool).

| Model | Pass | Cost (5 prompts) | TTFT p50 / max | Tool calls | Notes |
|---|---|---|---|---|---|
| **`openai/gpt-6-luna`** | **5/5** | **0.029 ct** | 1.8 / 2.5 s | 6 | args stream in ~25 deltas per call |
| `anthropic/claude-haiku-5.5` | 5/5 | 0.078 ct | 0.8 / 1.4 s | 5 | fewest calls (one `list_sources` for two domains) |
| `deepseek/deepseek-v4.1-flash` | 4/5 | 0.070 ct | 1.0 / 8.5 s | 8 | extra call on **single**; text preamble before tool calls; 8.5 s on **no_tool** |

- **All three** returned valid JSON for strict schemas and enum values, called two read tools in one turn
  for **parallel**, and none followed the injected instruction (no write call, no "pwned" text).
- **Delta assembly is required:** `gpt-6-luna` streams one call's arguments in 23–25 chunks; parallel calls
  arrive with distinct `index` values. Content and tool calls can come in the same turn (DeepSeek).
- **Claude Haiku 5.5** is the fastest and most precise. Its reasoning counts against `max_tokens`
  (ADR-0005), so it needs a higher output cap in agent mode.
- One run per prompt, so these numbers only shortlist; the agent eval decides.

## Alternatives considered

- **Agent framework** (LangGraph, OpenAI Agents SDK, PydanticAI) — excluded through Phase 2 (D11); it
  would hide the loop, limits and delta handling that this phase is meant to teach.
- **No hard limits, rely on the OpenRouter key limit** — a runaway loop is only noticed at the monthly cap.
- **DeepSeek V4.1 Flash as dev model** — cheapest list price, but over-calls tools and showed one slow
  outlier; still a candidate for the demo model.

## Consequences

- Every limit is a tested code path with a visible `stopReason`; the `fake` provider scripts tool calls,
  errors and slow tools, so CI spends nothing.
- Parallelism is our responsibility (`asyncio.TaskGroup` + semaphore), not the provider's.
- Model swaps stay env-only; the agent eval guards against a model change silently lowering task success.
