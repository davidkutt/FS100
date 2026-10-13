import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    root: './',
    env: { LOG_LEVEL: 'silent' },
    include: ['test/**/*.e2e-spec.ts'],
  },
});
