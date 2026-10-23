import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    root: './',
    include: ['test/**/*.e2e-spec.ts'],
    // Booting the app with PGlite migrations per file passes 10 s when `pnpm test` runs web in parallel.
    hookTimeout: 30_000,
    env: {
      KEYCLOAK_CLIENT_SECRET: 'test-only',
      LOG_LEVEL: 'silent',
      API_DATABASE_URL: ':memory:',
      UPLOAD_MAX_MB: '1',
      CHAT_THROTTLE_PER_MIN: '3',
    },
  },
});
