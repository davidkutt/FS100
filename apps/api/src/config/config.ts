import { z } from 'zod';

/** `KEY=` in an env file yields an empty string; treat it like an unset variable. */
const env = <T extends z.ZodType>(schema: T) =>
  z.preprocess((value) => (value === '' ? undefined : value), schema);

const origin = z.url().refine((value) => new URL(value).origin === value, {
  message: 'must be an origin like http://localhost:4200 (scheme, host, optional port; no path)',
});

const EnvSchema = z.object({
  API_PORT: env(z.coerce.number().int().min(1).max(65535).default(3000)),
  CORS_ORIGINS: env(
    z
      .string()
      .default('http://localhost:4200')
      .transform((value) =>
        value
          .split(',')
          .map((entry) => entry.trim())
          .filter(Boolean),
      )
      .pipe(z.array(origin)),
  ),
  LOG_LEVEL: env(
    z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']).default('info'),
  ),
});

export interface AppConfig {
  port: number;
  corsOrigins: string[];
  logLevel: z.infer<typeof EnvSchema>['LOG_LEVEL'];
}

/** Reads and validates the API's environment (`.env.example`, api section). Fails fast at boot. */
export function loadConfig(source: NodeJS.ProcessEnv = process.env): AppConfig {
  const result = EnvSchema.safeParse(source);
  if (!result.success) {
    throw new Error(`Invalid API configuration:\n${z.prettifyError(result.error)}`);
  }
  const { API_PORT, CORS_ORIGINS, LOG_LEVEL } = result.data;
  return { port: API_PORT, corsOrigins: CORS_ORIGINS, logLevel: LOG_LEVEL };
}
