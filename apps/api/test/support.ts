import type { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { createLocalJWKSet, exportJWK, generateKeyPair, SignJWT } from 'jose';
import type { App } from 'supertest/types.js';
import { AiClient } from '../src/ai-client/ai-client.service.js';
import { AppModule } from '../src/app.module.js';
import { configureApp } from '../src/app.setup.js';
import { JWKS } from '../src/auth/auth.guard.js';

// Keycloak expands composite roles into the token.
export const EDITOR = ['editor', 'viewer'];
export const ADMIN = ['admin', 'editor', 'viewer'];

const ISSUER = 'http://localhost:8080/realms/kb';
const { privateKey: signingKey, publicKey } = await generateKeyPair('RS256');
const jwks = createLocalJWKSet({
  keys: [{ ...(await exportJWK(publicKey)), kid: 'test', alg: 'RS256' }],
});
export const foreignKey = (await generateKeyPair('RS256')).privateKey;

export const token = (
  roles: string[],
  { sub = 'user-1', aud = 'kb-api', exp = '5m' as string | number, key = signingKey } = {},
) =>
  new SignJWT({ name: 'Test User', realm_access: { roles } })
    .setProtectedHeader({ alg: 'RS256', kid: 'test' })
    .setSubject(sub)
    .setIssuer(ISSUER)
    .setAudience(aud)
    .setExpirationTime(exp)
    .sign(key);

/** The app with test signing keys, in-process PGlite (`API_DATABASE_URL=:memory:`) and `ai`. */
export async function createApp(ai: unknown): Promise<INestApplication<App>> {
  const moduleFixture = await Test.createTestingModule({ imports: [AppModule] })
    .overrideProvider(JWKS)
    .useValue(jwks)
    .overrideProvider(AiClient)
    .useValue(ai)
    .compile();
  const app = moduleFixture.createNestApplication<INestApplication<App>>();
  configureApp(app);
  await app.init();
  return app;
}
