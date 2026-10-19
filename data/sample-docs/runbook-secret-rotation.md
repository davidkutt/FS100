# Runbook: Rotate secrets and API keys

Owner: security champion · Applies to: Keycloak client secrets, LLM provider keys, database passwords ·
Last reviewed: 2026-10

## Rotation schedule

| Secret | Where it lives | Rotate |
|---|---|---|
| `kb-api` client secret (Keycloak) | Keycloak, `KEYCLOAK_CLIENT_SECRET` of the API | every 90 days |
| OpenRouter API key | OpenRouter dashboard, `LLM_API_KEY` of the AI service | every 90 days and after every team change |
| Postgres passwords | database, `API_DATABASE_URL` | every 180 days |

## Zero-downtime order of operations

Rotation always follows **add → deploy → revoke**:

1. Create the new secret while the old one stays valid.
2. Roll the new value out to every consumer and restart them.
3. Verify that the consumers authenticate with the new value (logs, a smoke test).
4. Only then revoke the old secret.

## Keycloak client secret

Keycloak keeps one active secret per client, but supports a rotated secret with a grace period
(client policy "secret rotation"). Generate the new secret under *Clients → kb-api → Credentials →
Regenerate*, update `KEYCLOAK_CLIENT_SECRET` in the secret store, restart the API and check that the
admin status card still shows the AI service as `ok`.

## LLM provider key

Create a new key in the OpenRouter dashboard **with a credit limit**, set it as `LLM_API_KEY`, restart
the AI service, send one test question, then delete the old key. Keys without a credit limit are not
allowed.

## Leaked secret

If a secret was committed to git, pasted into a chat or shows up in logs:

1. Revoke it immediately — skip the zero-downtime order, a short outage is acceptable.
2. Create and roll out a new one.
3. Check the provider's usage and audit logs for abuse since the leak.
4. Removing the commit from history is cleanup, not mitigation: assume the secret was copied.
5. Write a SEV2 postmortem.
