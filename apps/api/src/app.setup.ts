import type { INestApplication } from '@nestjs/common';
import helmet from 'helmet';
import { Logger } from 'nestjs-pino';
import { REQUEST_ID_HEADER } from './common/request-id.js';
import type { AppConfig } from './config/config.js';
import { APP_CONFIG } from './config/config.module.js';

/** Shared bootstrap configuration, applied in `main.ts` and in the e2e tests. */
export function configureApp(app: INestApplication): INestApplication {
  const config = app.get<AppConfig>(APP_CONFIG);
  app.useLogger(app.get(Logger));
  app.use(helmet());
  app.enableCors({ origin: config.corsOrigins, exposedHeaders: [REQUEST_ID_HEADER] });
  // Browser-facing routes live under /api; probes stay at the root (plan.md §7.2).
  app.setGlobalPrefix('api', { exclude: ['healthz'] });
  app.enableShutdownHooks();
  return app;
}
