# Runbook: Roll back a failed deployment

Owner: platform team · Applies to: every service deployed by the CD pipeline · Last reviewed: 2026-10

## When to use this runbook

Use it when a release that went out in the last 24 hours causes errors, a latency regression or a broken
user journey, and the fastest way back to a healthy state is the previous version. Rolling back is
preferred over a hot fix whenever the cause is not understood within 15 minutes.

Do **not** roll back blindly when the release contained a database migration — read
[Database migrations](#database-migrations) first.

## Decide

1. Confirm the correlation: did the error rate or p95 latency change within minutes of the rollout?
   Check the deployment annotation on the service dashboard.
2. Announce in the incident channel: "Rolling back `<service>` from `<new>` to `<old>`".
3. Freeze the pipeline for that service so that nothing redeploys the broken version.

## Rollback on Kubernetes

```bash
kubectl rollout history deployment/api -n fs100
kubectl rollout undo deployment/api -n fs100                  # previous revision
kubectl rollout undo deployment/api -n fs100 --to-revision=41 # a specific one
kubectl rollout status deployment/api -n fs100 --timeout=5m
```

`rollout undo` re-applies the previous ReplicaSet's pod template, so the old image tag and the old
environment come back together. With GitOps, revert the commit in the deployment repository instead —
otherwise the controller will re-apply the broken version within minutes.

## Rollback with Docker Compose

Pin the previous image tag in the environment file and recreate only the affected service:

```bash
API_IMAGE_TAG=1.14.2 docker compose up -d --no-deps api
docker compose ps api
```

## Database migrations

Migrations are written expand/contract: a release only **adds** columns or tables, and the contract
step (dropping old columns) ships one release later. Therefore the previous application version still
works against the new schema and a rollback needs no down-migration. If a release broke this rule, stop
and page the database owner — never run a down-migration under pressure without a fresh backup (see the
Postgres backup runbook).

## Verify

- Error rate and p95 latency back to the pre-release baseline for 15 minutes.
- Smoke test: log in, upload a small document, ask one question.
- `kubectl get pods -n fs100` shows no restarts of the rolled-back pods.

## Follow-up

- Keep the pipeline frozen until a fix is merged and has passed staging.
- Open a postmortem if users were affected for more than 15 minutes.
- Add a test or an alert that would have caught the regression before production.
