import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    root: './',
    include: ['test/**/*.e2e-spec.ts'],
    env: { KEYCLOAK_CLIENT_SECRET: 'test-only', LOG_LEVEL: 'silent' },
  },
});
