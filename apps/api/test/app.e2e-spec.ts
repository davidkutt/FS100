import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import type { App } from 'supertest/types.js';
import { ADMIN, createApp, foreignKey, token } from './support.js';

describe('API (e2e)', () => {
  let app: INestApplication<App>;
  const ai = { get: vi.fn(async () => ({ status: 'ok', qdrant: 'ok' })) };

  beforeAll(async () => {
    app = await createApp(ai);
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

  it('GET /readyz is public and checks Postgres', () => {
    return request(app.getHttpServer()).get('/readyz').expect(200).expect({ status: 'ok' });
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

  it('errors are RFC 9457 problem details', async () => {
    const res = await request(app.getHttpServer()).get('/api/me').expect(401);

    expect(res.headers['content-type']).toMatch(/^application\/problem\+json/);
    expect(res.body).toEqual({
      type: 'about:blank',
      title: 'Unauthorized',
      status: 401,
      detail: 'Missing bearer token',
    });
  });

  it('GET /api/me returns the caller with app roles only', async () => {
    await request(app.getHttpServer())
      .get('/api/me')
      .auth(await token(['viewer', 'offline_access']), { type: 'bearer' })
      .expect(200)
      .expect({ sub: 'user-1', name: 'Test User', roles: ['viewer'] });
  });

  it('GET /api/status reports Postgres and asks the AI service with the request id', async () => {
    await request(app.getHttpServer())
      .get('/api/status')
      .set('x-request-id', 'req-7')
      .auth(await token(ADMIN), { type: 'bearer' })
      .expect(200)
      .expect({ api: 'ok', db: 'ok', aiService: 'ok', qdrant: 'ok' });
    expect(ai.get).toHaveBeenCalledWith('/v1/status', 'req-7');
  });

  it('GET /api/status survives a dead AI service', async () => {
    ai.get.mockRejectedValueOnce(new Error('ECONNREFUSED'));

    await request(app.getHttpServer())
      .get('/api/status')
      .auth(await token(ADMIN), { type: 'bearer' })
      .expect(200)
      .expect({ api: 'ok', db: 'ok', aiService: 'down', qdrant: 'unknown' });
  });
});
