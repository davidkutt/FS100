import { Module } from '@nestjs/common';
import { LoggerModule } from 'nestjs-pino';
import { AppController } from './app.controller.js';
import { AppService } from './app.service.js';
import { REQUEST_ID_HEADER, requestIdFrom } from './common/request-id.js';
import type { AppConfig } from './config/config.js';
import { APP_CONFIG, ConfigModule } from './config/config.module.js';
import { HealthModule } from './health/health.module.js';

@Module({
  imports: [
    ConfigModule,
    LoggerModule.forRootAsync({
      inject: [APP_CONFIG],
      useFactory: (config: AppConfig) => ({
        pinoHttp: {
          level: config.logLevel,
          // One id per request: reuse the caller's x-request-id or mint one, and echo it back.
          genReqId: (req, res) => {
            const id = requestIdFrom(req.headers[REQUEST_ID_HEADER]);
            res.setHeader(REQUEST_ID_HEADER, id);
            return id;
          },
          redact: ['req.headers.authorization', 'req.headers.cookie'],
          autoLogging: { ignore: (req) => req.url === '/healthz' },
        },
      }),
    }),
    HealthModule,
  ],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
