import { randomUUID } from 'node:crypto';
import { Module } from '@nestjs/common';
import { LoggerModule } from 'nestjs-pino';
import { AuthModule } from './auth/auth.module.js';
import { CONFIG, ConfigModule, type Config } from './config.js';
import { HealthModule } from './health/health.module.js';

@Module({
  imports: [
    ConfigModule,
    LoggerModule.forRootAsync({
      inject: [CONFIG],
      useFactory: (config: Config) => ({
        pinoHttp: {
          level: config.LOG_LEVEL,
          redact: ['req.headers.authorization', 'req.headers.cookie'],
          // Reuse the caller's id (D21) only if it looks like one; it ends up in every log line.
          genReqId: (req, res) => {
            const incoming = req.headers['x-request-id'];
            const id =
              typeof incoming === 'string' && /^[\w-]{1,64}$/.test(incoming)
                ? incoming
                : randomUUID();
            res.setHeader('x-request-id', id);
            return id;
          },
        },
      }),
    }),
    AuthModule,
    HealthModule,
  ],
})
export class AppModule {}
