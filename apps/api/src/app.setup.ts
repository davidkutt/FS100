import type { INestApplication } from '@nestjs/common';

/** Shared bootstrap configuration, applied in `main.ts` and in the e2e tests. */
export function configureApp(app: INestApplication): INestApplication {
  // Browser-facing routes live under /api; probes stay at the root (plan.md §7.2).
  app.setGlobalPrefix('api', { exclude: ['healthz'] });
  app.enableShutdownHooks();
  return app;
}
