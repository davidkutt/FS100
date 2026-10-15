import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module.js';
import { configureApp } from './app.setup.js';
import { CONFIG, type Config } from './config.js';

async function bootstrap() {
  const app = configureApp(await NestFactory.create(AppModule, { bufferLogs: true }));
  await app.listen(app.get<Config>(CONFIG).API_PORT);
}
await bootstrap();
