// `pnpm contracts:generate`: writes the OpenAPI document; needs neither Postgres nor Keycloak.
import { writeFileSync } from 'node:fs';
import { NestFactory } from '@nestjs/core';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { AppModule } from './app.module.js';
import { configureApp } from './app.setup.js';

process.env.API_DATABASE_URL = ':memory:';
process.env.KEYCLOAK_CLIENT_SECRET ??= 'unused';
process.env.LOG_LEVEL = 'silent';

const app = configureApp(await NestFactory.create(AppModule, { logger: false }));
const config = new DocumentBuilder()
  .setTitle('Grove API')
  .addBearerAuth()
  .addSecurityRequirements('bearer')
  .build();
writeFileSync(
  process.argv[2],
  `${JSON.stringify(SwaggerModule.createDocument(app, config), null, 2)}\n`,
);
await app.close();
