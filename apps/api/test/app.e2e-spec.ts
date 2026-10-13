import { Test, TestingModule } from '@nestjs/testing';
import { INestApplication } from '@nestjs/common';
import request from 'supertest';
import { App } from 'supertest/types.js';
import { AppModule } from './../src/app.module.js';
import { configureApp } from './../src/app.setup.js';

describe('API (e2e)', () => {
  let app: INestApplication<App>;

  beforeEach(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = configureApp(moduleFixture.createNestApplication());
    await app.init();
  });

  afterEach(async () => {
    await app.close();
  });

  it('GET /api/hello', () => {
    return request(app.getHttpServer())
      .get('/api/hello')
      .expect(200)
      .expect({ message: 'Hello from the FS100 API' });
  });

  it('GET /healthz is served without the /api prefix', () => {
    return request(app.getHttpServer()).get('/healthz').expect(200).expect({ status: 'ok' });
  });

  it('GET /hello without the prefix is 404', () => {
    return request(app.getHttpServer()).get('/hello').expect(404);
  });

  describe('x-request-id', () => {
    it('is minted when the caller sends none', async () => {
      const res = await request(app.getHttpServer()).get('/api/hello').expect(200);
      expect(res.headers['x-request-id']).toMatch(/^[0-9a-f-]{36}$/);
    });

    it('echoes a safe incoming id', () => {
      return request(app.getHttpServer())
        .get('/api/hello')
        .set('x-request-id', 'req-123')
        .expect('x-request-id', 'req-123');
    });

    it('replaces an unsafe incoming id', async () => {
      const res = await request(app.getHttpServer())
        .get('/api/hello')
        .set('x-request-id', 'bad id with spaces');
      expect(res.headers['x-request-id']).not.toBe('bad id with spaces');
    });
  });

  describe('CORS', () => {
    it('allows the web origin and exposes x-request-id', async () => {
      const res = await request(app.getHttpServer())
        .options('/api/hello')
        .set('Origin', 'http://localhost:4200')
        .set('Access-Control-Request-Method', 'POST')
        .set('Access-Control-Request-Headers', 'authorization,content-type')
        .expect(204);
      expect(res.headers['access-control-allow-origin']).toBe('http://localhost:4200');

      const get = await request(app.getHttpServer())
        .get('/api/hello')
        .set('Origin', 'http://localhost:4200');
      expect(get.headers['access-control-expose-headers']).toBe('x-request-id');
    });

    it('does not allow other origins', async () => {
      const res = await request(app.getHttpServer())
        .get('/api/hello')
        .set('Origin', 'https://evil.example.com');
      expect(res.headers['access-control-allow-origin']).toBeUndefined();
    });
  });

  it('sets helmet security headers', async () => {
    const res = await request(app.getHttpServer()).get('/api/hello');
    expect(res.headers['x-content-type-options']).toBe('nosniff');
    expect(res.headers['x-powered-by']).toBeUndefined();
  });
});
