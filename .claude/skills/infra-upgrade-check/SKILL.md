---
name: infra-upgrade-check
description: Verifies a Keycloak, Qdrant, Phoenix or Postgres image bump (or a realm/admin-API experiment) on a throwaway Compose project, so the developer's local data in the `fs100_*` volumes is never touched. Use when bumping image pins in infra/compose/docker-compose.yml, reviewing a Dependabot docker-compose PR, or spiking Keycloak realm changes (token exchange, client scopes) before editing realm-kb.json.
disable-model-invocation: true
---

# Infra upgrade check on a throwaway stack

Ports in the compose file are fixed (`127.0.0.1:5432/6333/8080/6006`), so the throwaway project and the
real `fs100` stack cannot run at the same time.

## Steps

1. **Stop the real stack first.** Starting OrbStack/Docker auto-restarts `fs100-*` containers
   (`restart: unless-stopped`); anything you send to `localhost:6333` or `:8080` then hits real data.
   ```bash
   docker ps --format '{{.Names}}'                       # any fs100-* running?
   docker compose -p fs100 -f infra/compose/docker-compose.yml stop
   ```
2. **Boot the OLD pins** in a separate project (own volumes `fs100-m20_*`), seed something to survive:
   ```bash
   docker compose -p fs100-m20 -f infra/compose/docker-compose.yml up -d --wait postgres qdrant keycloak
   curl -s -X PUT localhost:6333/collections/upgrade_probe -H 'content-type: application/json' \
     -d '{"vectors":{"size":2,"distance":"Cosine"}}'
   curl -s -X PUT 'localhost:6333/collections/upgrade_probe/points?wait=true' -H 'content-type: application/json' \
     -d '{"points":[{"id":1,"vector":[0.1,0.9]}]}'
   ```
3. **Edit the pins**, then upgrade in place: same command plus `phoenix`. Check:
   ```bash
   curl -s localhost:6333/collections/upgrade_probe/points/1          # data survived
   docker logs fs100-m20-keycloak-1 2>&1 | grep -iE 'migrat|error'    # "migrated realm kb to …"
   ```
4. **Fresh import:** `down -v` the throwaway project, `up -d --wait postgres keycloak` again, then
   `curl localhost:8080/realms/kb/.well-known/openid-configuration` → 200 and a `kb-api` client-credentials
   token with `aud=kb-ai`.
5. **Retrieval eval** when `qdrant-client` changes: `pnpm eval:retrieval` before and after the bump; diff
   the two newest `evals/runs/*.md` from `| Slice` down — they must be identical.
6. **Tear down:** list the volumes before deleting them, and only delete `fs100-m20_*`:
   ```bash
   docker volume ls --format '{{.Name}}' | grep '^fs100-m20_'
   docker compose -p fs100-m20 -f infra/compose/docker-compose.yml down -v
   ```
   Leave the real stack stopped if it was stopped before; otherwise `pnpm stack:up`.

## Realm experiments

Admin token: `POST /realms/master/protocol/openid-connect/token` with `client_id=admin-cli`,
`admin` / `dev-only-change-me` (the throwaway project does not read the root `.env`). Change clients via
`GET/PUT /admin/realms/kb/clients/{id}`. For scripted user tokens on the throwaway realm only, set
`directAccessGrantsEnabled=true` on `kb-web`; never do that in `realm-kb.json`. Use the `user-token`
skill for the real stack.

## Pitfalls

- Keycloak and Qdrant migrate volumes forward only — never test a bump on `fs100_*`.
- Dependabot ignores major bumps for compose images; a major (e.g. GitHub MCP server 1.x → 2.x) is a
  deliberate edit.
