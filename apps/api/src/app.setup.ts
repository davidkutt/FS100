import type { INestApplication } from '@nestjs/common';
import helmet from 'helmet';
import { Logger } from 'nestjs-pino';
import { CONFIG, type Config } from './config.js';

/** Shared bootstrap configuration, applied in `main.ts` and in the e2e tests. */
export function configureApp(app: INestApplication): INestApplication {
  app.useLogger(app.get(Logger));
  app.use(helmet());
  app.enableCors({ origin: app.get<Config>(CONFIG).CORS_ORIGINS });
  // Browser-facing routes live under /api; probes stay at the root (plan.md §7.2).
  app.setGlobalPrefix('api', { exclude: ['healthz'] });
  app.enableShutdownHooks();
  return app;
}
