import { defineConfig, devices } from '@playwright/test';

// Runs against an already running stack: `pnpm stack:up:full` (CI) or Mode A with `pnpm dev`.
export default defineConfig({
  testDir: '.',
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:4200',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
