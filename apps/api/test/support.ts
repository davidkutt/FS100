import { once } from 'node:events';
import { createServer, type IncomingHttpHeaders, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import type { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { createLocalJWKSet, decodeJwt, exportJWK, generateKeyPair, SignJWT } from 'jose';
import type { App } from 'supertest/types.js';
import { AiClient } from '../src/ai-client/ai-client.service.js';
import { AppModule } from '../src/app.module.js';
import { configureApp } from '../src/app.setup.js';
import { JWKS } from '../src/auth/auth.guard.js';
import type { Config } from '../src/config.js';

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
  {
    sub = 'user-1',
    aud = 'kb-api',
    exp = '5m' as string | number,
    key = signingKey,
    clientRoles = [] as string[], // of kb-api, e.g. a service account's `ingest-on-behalf`
  } = {},
) =>
  new SignJWT({
    name: 'Test User',
    realm_access: { roles },
    resource_access: { 'kb-api': { roles: clientRoles } },
  })
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

export interface Received {
  url: string;
  headers: IncomingHttpHeaders;
  body: unknown;
  closed: Promise<unknown>;
}

/**
 * A fake AI service (and its token endpoint) on a real socket; `respond` answers each call. An
 * exchanged token is `user-token:<sub>`, the service account's is `svc-token`.
 */
export async function fakeAiService() {
  const upstream = {
    received: [] as Received[],
    tokenRequests: [] as URLSearchParams[],
    respond: (res: ServerResponse): void => void res.end(),
    ai: undefined as unknown as AiClient,
    close: () => {
      server.closeAllConnections();
      server.close();
    },
  };
  const server = createServer(async (req, res) => {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    const text = Buffer.concat(chunks).toString();
    if (req.url!.endsWith('/token')) {
      const form = new URLSearchParams(text);
      upstream.tokenRequests.push(form);
      const subject = form.get('subject_token');
      const sub = subject && (decodeJwt(subject).sub as string);
      res.end(
        JSON.stringify({ access_token: sub ? `user-token:${sub}` : 'svc-token', expires_in: 300 }),
      );
      return;
    }
    upstream.received.push({
      url: req.url!,
      headers: req.headers,
      body: text ? JSON.parse(text) : undefined,
      closed: once(res, 'close'),
    });
    upstream.respond(res);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  upstream.ai = new AiClient({
    AI_SERVICE_URL: url,
    AI_SERVICE_AUDIENCE: 'kb-ai',
    KEYCLOAK_ISSUER: `${url}/realms/kb`,
    KEYCLOAK_CLIENT_ID: 'kb-api',
    KEYCLOAK_CLIENT_SECRET: 'test-only',
  } as Config);
  return upstream;
}
