import { Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { createRemoteJWKSet } from 'jose';
import { CONFIG, type Config } from '../config.js';
import { AuthGuard, JWKS } from './auth.guard.js';
import { MeController } from './me.controller.js';

@Module({
  controllers: [MeController],
  providers: [
    {
      provide: JWKS,
      inject: [CONFIG],
      useFactory: (config: Config) =>
        createRemoteJWKSet(
          new URL(
            `${config.KEYCLOAK_REALM_URL ?? config.KEYCLOAK_ISSUER}/protocol/openid-connect/certs`,
          ),
        ),
    },
    { provide: APP_GUARD, useClass: AuthGuard },
  ],
})
export class AuthModule {}
