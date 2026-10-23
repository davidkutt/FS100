---
name: agent-eval-run
description: Runs the paid real-model agent evals (`kb-eval agent | redteam | routing`, golden set in rag vs agent mode) against the fixture MCP servers, triages failures into check bugs vs real agent behaviour, and records baselines in plan-phase-2 / ADR-0011 / ADR-0012. Use after changing the agent prompt, model, router, tools or taxonomy ("re-run the agent eval", "red-team pass rate", "compare routers", "plain vs agentic RAG", "baseline for agent_v1").
disable-model-invocation: true
---

# Real-model agent evals

Costs money (OpenRouter key from `.env`). gpt-6-luna, 2026-10-21: agent_v1 ×3 ≈ 0.08 USD, redteam ×3 ≈
0.04, golden set ×1 ≈ 0.006 (rag) / 0.044 (agent), routing ≈ 0.005. Every run first ingests the corpus
with bge-m3 (~3 min). Confirm the spend with the user first.

## 1. Sanity run (2 tasks, ~0.002 USD)

```bash
S=<scratchpad>; grep -E '"(a-023|rt-002)"' evals/datasets/agent_v1.jsonl evals/datasets/redteam_v0.jsonl -h > $S/one.jsonl
pnpm -s eval:agent --dataset $S/one.jsonl --repeats 1 --out $S/runs
```

Expect `ok`/`FAIL` lines and a report. Fixture data in the answer (e.g. "14 MB" free) proves `github.*`
hit the fixture — httpx logs still show `localhost:8082`, that is only the configured URL.

## 2. Full chain (background, one process at a time — 16 GB RAM)

```bash
pnpm -s eval:agent; pnpm -s eval:redteam
pnpm -s eval:agent --dataset ../../evals/datasets/retrieval_v1.jsonl --mode rag --repeats 1
pnpm -s eval:agent --dataset ../../evals/datasets/retrieval_v1.jsonl --mode agent --repeats 1
pnpm -s eval:routing
```

Reports: `evals/runs/<ts>__<dataset>__<model>__<mode>.{json,md}`.

## 3. Triage every failure before quoting numbers

```bash
python3 -c "
import json,glob
r=json.load(open(sorted(glob.glob('evals/runs/*__agent_v1__*__agent.json'))[-1]))
for a in r['attempts']:
    if not a['success']: print(a['task'], a['repeat'], a['tools'], a['failures'], '|', a['answer'][:300])"
```

- **Check bug** (fix the dataset only if it was never committed, else a new version, then re-run):
  regexes must accept typographic quotes — models write `can’t`, not `can't`; hyphenated forms
  (`five-business-day`).
- **Real behaviour** (keep, record as a finding): no citation, wrong `answer_status`, asking for confirmation
  in chat instead of proposing the write, claiming a tool the role lacks.
- **Provider flake**: `stopped with an error: Stream ended before a terminal response event` is OpenRouter
  cutting the stream (not in local code); note it, do not re-run for it.
- Embedding-router threshold curve without a new run: read `items[].confidence/correct` from the
  `*__routing_v1.json`.

## 4. Record

- `plan-phase-2.md` milestone done note: baselines (success, precision/recall, forbidden ok, steps, cost,
  p50) and open findings.
- ADR-0011 (golden set rag vs agent) / ADR-0012 (routers): update the result tables; with 1 repeat, call a
  2-item difference noise.
