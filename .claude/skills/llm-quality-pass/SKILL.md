---
name: llm-quality-pass
description: Runs the manual LLM quality pass — 10 golden questions through the real chat pipeline against one or more OpenRouter models — and records the result in ADR-0005. Use when choosing, switching or re-checking the chat model (LLM_MODEL), comparing OpenRouter models by price/quality, or when asked to "re-run the model pass" or "check the dev/demo model".
disable-model-invocation: true
---

# LLM quality pass

Spends real tokens (≈ 0.1–0.3 ct per model) and sends corpus chunks to OpenRouter. Only public or
self-written docs are in the corpus (D25).

1. Check the key is set in the repo-root `.env` without printing it (it never goes into `.env.example`):
   `python3 -I -c "print(len([l for l in open('.env') if l.startswith('LLM_API_KEY=')][0].split('=',1)[1].split('#')[0].strip()))"`
   → must be > 0.
2. Pick candidates and current list prices from the public catalog:
   `curl -s https://openrouter.ai/api/v1/models` (`pricing.prompt` / `.completion` are USD per token).
3. Run from `apps/ai-service` (takes ~3 min to ingest the corpus with `bge-m3`, then ~1 min per model):
   ```bash
   cd apps/ai-service
   .venv/bin/python ../../.claude/skills/llm-quality-pass/quality_pass.py openai/gpt-6-luna deepseek/deepseek-v4.1-flash
   ```
   Uses `Settings()` defaults (embedding model, top_k, threshold, `LLM_MAX_OUTPUT_TOKENS`); answers land in
   `evals/runs/quality-pass-*.json` (git-ignored).
4. Read every answer, not just the summary line. Check per answer: language matches the question,
   citations point at sources that contain the claim, unanswerable `u-*` items are declined, no advice
   beyond the sources.
5. Update the "Manual quality pass" table and notes in `docs/adr/0005-llm-access-and-model.md`; if the
   model changes, also `LLM_MODEL` in `.env.example` and plan.md Appendix A.

## Pitfalls

- **Output max = `LLM_MAX_OUTPUT_TOKENS` means a cut-off answer.** Reasoning models (e.g. Claude Haiku 5.5)
  spend the cap on hidden reasoning (`delta.reasoning_details`); the client is not told. Replay the
  prompt and inspect the raw deltas before blaming the adapter.
- **r-033 is a known retrieval miss** (the 402 table row scores below the 0.55 threshold): all models say
  "not defined". It measures grounding, not knowledge.
- Input token counts differ per model for the same prompt (different tokenizers); compare cost, not tokens.
