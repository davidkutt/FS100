// Starts the apps natively with hot reload (Mode A, plan.md D18).
// Usage: pnpm dev            -> web + api + ai
//        pnpm dev api ai     -> only the named apps
// The root `.env`, then `.env.local` (dev secrets such as the GitHub PATs, D37), are loaded by
// `node --env-file-if-exists` (see package.json), so every child process inherits the same environment.
import concurrently from 'concurrently';

const aiPort = process.env.AI_PORT ?? '8000';

const apps = {
  web: { command: 'pnpm --filter @grove/web start', prefixColor: 'magenta' },
  api: { command: 'pnpm --filter @grove/api start:dev', prefixColor: 'blue' },
  ai: {
    command: `uv run --directory apps/ai-service uvicorn ai_service.main:app --reload --host 127.0.0.1 --port ${aiPort}`,
    prefixColor: 'green',
  },
};

const requested = process.argv.slice(2);
const unknown = requested.filter((name) => !(name in apps));
if (unknown.length > 0) {
  console.error(
    `Unknown app(s): ${unknown.join(', ')}. Choose from: ${Object.keys(apps).join(', ')}`,
  );
  process.exit(1);
}

const selected = requested.length > 0 ? requested : Object.keys(apps);
const { result } = concurrently(
  selected.map((name) => ({ name, ...apps[name] })),
  { killOthersOn: ['failure'], prefix: '[{name}]', restartTries: 0 },
);

result.catch(() => process.exit(1));
