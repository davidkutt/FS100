import { Test } from '@nestjs/testing';
import { INestApplication } from '@nestjs/common';
import { createLocalJWKSet, exportJWK, generateKeyPair, SignJWT, type CryptoKey } from 'jose';
import request from 'supertest';
import { App } from 'supertest/types.js';
import { AiClient } from './../src/ai-client/ai-client.service.js';
import { AppModule } from './../src/app.module.js';
import { configureApp } from './../src/app.setup.js';
import { JWKS } from './../src/auth/auth.guard.js';

const ISSUER = 'http://localhost:8080/realms/kb';

describe('API (e2e)', () => {
  let app: INestApplication<App>;
  let signingKey: CryptoKey;
  let foreignKey: CryptoKey;
  const ai = { get: vi.fn(async () => ({ status: 'ok' })) };

  const token = (
    roles: string[],
    { aud = 'kb-api', exp = '5m' as string | number, key = signingKey } = {},
  ) =>
    new SignJWT({ name: 'Test User', realm_access: { roles } })
      .setProtectedHeader({ alg: 'RS256', kid: 'test' })
      .setSubject('user-1')
      .setIssuer(ISSUER)
      .setAudience(aud)
      .setExpirationTime(exp)
      .sign(key);

  beforeAll(async () => {
    const pair = await generateKeyPair('RS256');
    signingKey = pair.privateKey;
    foreignKey = (await generateKeyPair('RS256')).privateKey;
    const jwk = { ...(await exportJWK(pair.publicKey)), kid: 'test', alg: 'RS256' };

    const moduleFixture = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(JWKS)
      .useValue(createLocalJWKSet({ keys: [jwk] }))
      .overrideProvider(AiClient)
      .useValue(ai)
      .compile();
    app = configureApp(moduleFixture.createNestApplication());
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  it('GET /healthz is public, unprefixed and echoes the request id', () => {
    return request(app.getHttpServer())
      .get('/healthz')
      .set('x-request-id', 'req-42')
      .expect(200)
      .expect('x-request-id', 'req-42')
      .expect({ status: 'ok' });
  });

  describe('token matrix', () => {
    it.each([
      ['no token', () => Promise.resolve(undefined)],
      ['wrong audience', () => token(['viewer'], { aud: 'kb-ai' })],
      ['expired', () => token(['viewer'], { exp: Math.floor(Date.now() / 1000) - 60 })],
      ['foreign signature', () => token(['viewer'], { key: foreignKey })],
    ])('%s → 401', async (_case, makeToken) => {
      const jwt = await makeToken();
      const req = request(app.getHttpServer()).get('/api/me');
      await (jwt ? req.auth(jwt, { type: 'bearer' }) : req).expect(401);
    });

    it.each(['viewer', 'editor'])('%s on an admin route → 403', async (role) => {
      await request(app.getHttpServer())
        .get('/api/status')
        .auth(await token([role]), { type: 'bearer' })
        .expect(403);
    });
  });

  it('GET /api/me returns the caller with app roles only', async () => {
    await request(app.getHttpServer())
      .get('/api/me')
      .auth(await token(['viewer', 'offline_access']), { type: 'bearer' })
      .expect(200)
      .expect({ sub: 'user-1', name: 'Test User', roles: ['viewer'] });
  });

  it('GET /api/status asks the AI service with the request id', async () => {
    await request(app.getHttpServer())
      .get('/api/status')
      .set('x-request-id', 'req-7')
      .auth(await token(['admin', 'editor', 'viewer']), { type: 'bearer' })
      .expect(200)
      .expect({ api: 'ok', aiService: 'ok' });
    expect(ai.get).toHaveBeenCalledWith('/v1/status', 'req-7');
  });
});
