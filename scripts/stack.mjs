// Thin wrapper around `docker compose` for the local infra (plan.md D18, Mode A).
// Uses the root `.env` and then `.env.local` (dev secrets, D37) when they exist; otherwise the defaults in
// the compose file apply.
// Usage: node scripts/stack.mjs <compose args...>   e.g. `pnpm stack:up`, `pnpm stack:logs keycloak`
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';

const args = ['compose', '--file', 'infra/compose/docker-compose.yml'];
for (const file of ['.env', '.env.local']) if (existsSync(file)) args.push('--env-file', file);
args.push(...process.argv.slice(2));

const { status, error } = spawnSync('docker', args, { stdio: 'inherit' });
if (error) {
  console.error(`Could not run docker: ${error.message}. Is Docker installed and running?`);
  process.exit(1);
}
process.exit(status ?? 1);
