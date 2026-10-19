# Runbook: LLM provider errors and outages

Owner: AI engineering · Applies to: chat in the AI service (`LLM_PROVIDER=openai_compat`) ·
Last reviewed: 2026-10

## Symptoms

- Chat answers stop after the sources event and end with an `error` event.
- AI service logs show HTTP 429, 402 or 5xx from the provider.
- Phoenix shows `llm` spans with errors or very long durations.

## Triage by status code

| Status | Meaning | Action |
|---|---|---|
| 429 | Rate limit of the provider or the model | Retries with exponential backoff happen automatically; if it persists, switch to another model |
| 402 | Credit limit of the API key reached | Intended cost guard. Raise the limit deliberately or wait for the next month |
| 5xx | Provider or upstream model down | Check the provider status page; switch provider if it lasts longer than 10 minutes |
| 401 | Key revoked or wrong | See the secret rotation runbook |

## Switch the provider

Every provider speaks the OpenAI-compatible API, so a switch is configuration only:

```bash
LLM_BASE_URL=https://router.huggingface.co/v1
LLM_API_KEY=<hugging face token>
LLM_MODEL=<model id available on that router>
```

Restart the AI service and send one test question. Model ids differ between providers; keep a tested
fallback model id in the team notes.

## Demos without a provider

For demos and tests set `LLM_PROVIDER=fake`. The fake provider streams a deterministic answer with
citations and costs nothing; retrieval still runs for real, so the sources and the inspector stay
meaningful.

## Afterwards

Note the duration and the error rate. If an outage hit users for more than 15 minutes, treat it as a
SEV2 incident.
