import { Global, Module } from '@nestjs/common';
import { z } from 'zod';

const schema = z.object({
  API_PORT: z.coerce.number().int().default(3000),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']).default('info'),
  KEYCLOAK_ISSUER: z.url().default('http://localhost:8080/realms/kb'),
  KEYCLOAK_AUDIENCE: z.string().default('kb-api'),
  KEYCLOAK_CLIENT_ID: z.string().default('kb-api'),
  KEYCLOAK_CLIENT_SECRET: z.string().min(1),
  AI_SERVICE_URL: z.url().default('http://localhost:8000'),
  CORS_ORIGINS: z
    .string()
    .default('http://localhost:4200')
    .transform((origins) => origins.split(',').map((origin) => origin.trim())),
});

export type Config = z.infer<typeof schema>;
export const CONFIG = Symbol('CONFIG');

@Global()
@Module({
  providers: [{ provide: CONFIG, useFactory: () => schema.parse(process.env) }],
  exports: [CONFIG],
})
export class ConfigModule {}
