# ADR-0012: Embedding router by default; the LLM classifier stays opt-in

- **Status:** Proposed
- **Date:** 2026-10-21
- **Plan reference:** D33, D43, D48

## Context

D33 routes each turn to domains, which pick the offered tool groups and the default search filter. M2.5
built two routers behind one interface: **embedding** similarity of the question to the domain
descriptions in `config/taxonomy.yaml` (bge-m3, softmax over cosine similarities, `MIN_CONFIDENCE = 0.8`
calibrated on the golden set's questions) and an **LLM classifier** with structured output
`{domains[], needs_tools, confidence}`. Below the threshold a route is not applied: every tool, no filter.
So a router that is rarely confident is safe but does little; a router that is confidently wrong hides
tools and filters the search.

## Result

`kb-eval routing --router embedding --router llm` on `routing_v1` (60 questions written for routing, not
from the golden set: every domain, DE + EN, 6 small-talk items), 2026-10-21. A route is correct when it
shares a domain with the label; small talk wants no domain or `needs_tools: false`.

| | embedding (bge-m3) | LLM (`openai/gpt-6-luna`) |
|---|---|---|
| accuracy, all 60 | 0.53 | **0.98** |
| confident (route applied) | 0.20 | 1.00 |
| accuracy when confident | 0.92 | 0.98 |
| confident & wrong (share of all) | 0.02 (1) | 0.02 (1) |
| `needs_tools` accuracy | 0.90 (always true) | 0.98 |
| cost for 60 routes | 0 | 0.0047 USD |
| latency p50 / p95 | 55 / 64 ms | 2,643 / 3,527 ms |

- The one confident miss each is arguable: embedding sends "How does the agent defend against prompt
  injection?" to `ai` (label `security`); the LLM sends "Which pull requests are open?" to `devops` (label
  `dev`), which still offers the GitHub tools.
- Embedding coverage vs threshold (same run): 0.5 → 43 % confident, 0.88 accurate; 0.6 → 37 %, 0.91;
  0.8 → 20 %, 0.92. Lower thresholds pay with confident mistakes (0.4 → 23 % of all routes wrong).
- The embedding router never says "no tools", so small talk still gets the full tool list (and the model
  correctly calls nothing: `no-tool` tasks 1.00 in `agent_v1`).

## Decision

`ROUTER=embedding` stays the default and `MIN_CONFIDENCE` stays 0.8. The LLM classifier is far more
accurate, but it adds ~2.6 s before the first step of every turn — about half of today's p50 turn (5.3 s)
— to trim a list of ~17 tools, which the model already selects from with 0.95 precision. `ROUTER=llm`
stays available and becomes the default once the tool list grows (P3 domain tools) or a faster classifier
model is measured (`ROUTER_MODEL`, same command).

## Alternatives considered

- **LLM router by default** — best accuracy, but the latency lands on every turn, small talk included.
- **Lower `MIN_CONFIDENCE` to 0.6** — almost doubles coverage at 0.91 accuracy, but `routing_v1` is the
  test set; recalibrate on a separate tuning set first.
- **Both: embedding first, LLM only below the threshold** — 80 % of turns would still pay the 2.6 s.

## Consequences

- The default route rarely filters, so the router's main effect today is the `route` event in the UI.
- Re-run `pnpm eval:routing` when `taxonomy.yaml` descriptions change; they are the embedding router's
  only input.
