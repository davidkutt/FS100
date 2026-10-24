-- Runs once, on the first start of an empty Postgres volume (docker-entrypoint-initdb.d).
-- One instance, two databases (plan.md D15): Keycloak's own state and the product DB `app`.
-- The AI service creates its database `ai` itself on boot (D52), so it needs no reset.
-- After changing this file: `pnpm stack:reset && pnpm stack:up` (drops all local data).
CREATE DATABASE keycloak;
CREATE DATABASE app;
