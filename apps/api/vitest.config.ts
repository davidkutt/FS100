import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    root: './',
    env: { LOG_LEVEL: 'silent' },
    include: ['src/**/*.spec.ts'],
  },
});
