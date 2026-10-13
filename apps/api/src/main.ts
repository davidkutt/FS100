import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module.js';
import { configureApp } from './app.setup.js';
import type { AppConfig } from './config/config.js';
import { APP_CONFIG } from './config/config.module.js';

async function bootstrap() {
  const app = configureApp(await NestFactory.create(AppModule, { bufferLogs: true }));
  await app.listen(app.get<AppConfig>(APP_CONFIG).port);
}
await bootstrap();
