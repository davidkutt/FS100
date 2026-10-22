# ADR-0011: Agentic RAG for conversations; plain RAG stays the measured baseline

- **Status:** Proposed
- **Date:** 2026-10-21
- **Plan reference:** D32, D43, D49

## Context

D32 made knowledge-base search a tool the agent controls (whether to search, which domains, reformulation,
multi-hop) and kept the Phase 1 pipeline as `mode=rag`, with the comparison to be measured. M2.6 added the
runner: `kb-eval agent --dataset ../../evals/datasets/retrieval_v1.jsonl --mode rag|agent` turns the
retrieval golden set into tasks — an answerable question must cite a labelled source, an unanswerable one
must abstain (`answerStatus`, D49). Both modes use the same in-memory corpus (bge-m3, 1000/150, threshold
0.55) and the same model.

## Result

Golden set `retrieval_v1` (60 questions, 50 answerable, DE + EN), `openai/gpt-6-luna`, 1 repeat,
2026-10-21. Agent mode with the embedding router (ADR-0012), tools as deployed.

| | plain RAG (`mode=rag`) | agentic RAG (`mode=agent`) |
|---|---|---|
| success, all 60 | **0.87** (52) | 0.83 (50) |
| answerable: cites a relevant source | 0.88 (44 / 50) | 0.86 (43 / 50) |
| unanswerable: abstains | 0.80 (8 / 10) | 0.70 (7 / 10) |
| steps per turn | 1.0 | 2.5 |
| cost per turn | 0.0001 USD | 0.0007 USD |
| latency p50 / p95 (whole turn) | 1.6 / 2.9 s | 5.6 / 11.7 s |

- Six of the misses are shared (`r-005`, `r-022`, `r-033`, `r-037`, `u-005`, `u-010`); plain RAG alone
  misses 2 items, agentic RAG alone 4. With one repeat, a 2-item difference is within noise.
- Unanswerable misses in both modes are mostly D49's rule, not the answer: the model says "not in the
  knowledge base" but cites the near miss, so the turn counts as `answered` (also `a-019`, `a-020` in the
  agent set).
- What the golden set cannot show, the agent set does (`agent_v1`, 3 repeats, same day): multi-hop 0.80,
  GitHub + KB tasks 0.75, tool selection 1.00 — none of which plain RAG can do at all.

## Decision

Agent mode with agentic RAG stays the conversation default. On single-hop KB questions it matches plain
RAG within noise at 7× the cost and 3.5× the latency; at 0.07 ct per turn the cost is negligible against the
20 USD/month cap, and only the agent reaches GitHub, multi-hop and writes. `mode=rag` stays as the
measured baseline (and behind `/api/chat`); every retrieval or prompt change is compared against it.

## Alternatives considered

- **Plain RAG by default, agent on demand** — cheaper and faster for lookups, but the user would have to
  know in advance which questions need tools.
- **Route single-hop KB questions to `mode=rag`** — saves latency, needs a classifier we do not have (the
  LLM router adds 2.6 s itself, ADR-0012). Revisit if latency becomes the complaint.

## Consequences

- Latency is the cost of agentic RAG (p50 5.6 s vs 1.6 s); streaming the first step event keeps the UI
  alive, but the first token arrives after at least one search round trip.
- Follow-ups: abstention when only a near miss is found (prompt rule "do not cite what does not answer",
  or D49 checking the answer text), measured again with `agent_v1` and the golden set; repeats ≥ 3 before
  any claim about a difference this small.
