import { once } from 'node:events';
import { createServer, type IncomingHttpHeaders, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import type { INestApplication } from '@nestjs/common';
import type { App } from 'supertest/types.js';
import { AiClient } from '../src/ai-client/ai-client.service.js';
import type { Config } from '../src/config.js';
import { createApp, token } from './support.js';

const EVENTS = [
  'event: sources\ndata: {"sources":[]}\n\n',
  ': ping\n\n',
  'event: token\ndata: {"text":"Grüße [1]"}\n\n',
  'event: done\ndata: {"usage":null,"model":null,"traceId":null}\n\n',
];

interface Received {
  url: string;
  headers: IncomingHttpHeaders;
  body: unknown;
  closed: Promise<unknown>;
}

/** Real sockets on both hops: client → API → a fake AI service (and its token endpoint). */
describe('Chat and search relay (e2e)', () => {
  let app: INestApplication<App>;
  let apiUrl: string;
  let respond: (res: ServerResponse) => void;
  const received: Received[] = [];
  const upstream = createServer(async (req, res) => {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    if (req.url!.endsWith('/token')) {
      res.end(JSON.stringify({ access_token: 'svc-token', expires_in: 300 }));
      return;
    }
    const text = Buffer.concat(chunks).toString();
    received.push({
      url: req.url!,
      headers: req.headers,
      body: text ? JSON.parse(text) : undefined,
      closed: once(res, 'close'),
    });
    respond(res);
  });

  beforeAll(async () => {
    upstream.listen(0, '127.0.0.1');
    await once(upstream, 'listening');
    const upstreamUrl = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`;
    const ai = new AiClient({
      AI_SERVICE_URL: upstreamUrl,
      KEYCLOAK_ISSUER: `${upstreamUrl}/realms/kb`,
      KEYCLOAK_CLIENT_ID: 'kb-api',
      KEYCLOAK_CLIENT_SECRET: 'test-only',
    } as Config);
    app = await createApp(ai);
    await app.listen(0, '127.0.0.1');
    apiUrl = await app.getUrl();
  });

  afterAll(async () => {
    await app.close();
    upstream.closeAllConnections();
    upstream.close();
  });

  const post = async (path: string, body: unknown, sub = 'chat-user', signal?: AbortSignal) =>
    fetch(`${apiUrl}/api${path}`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${await token(['viewer'], { sub })}`,
        'content-type': 'application/json',
        'x-request-id': 'req-chat',
      },
      body: JSON.stringify(body),
      signal,
    });

  const streamAll = (res: ServerResponse) => {
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    for (const event of EVENTS) res.write(event);
    res.end();
  };

  it('relays the SSE bytes unchanged, with the user context from the token', async () => {
    respond = streamAll;
    const res = await post('/chat', {
      messages: [{ role: 'user', content: 'Hallo?' }],
      domains: ['devops'],
      user: { sub: 'someone-else', roles: ['admin'] },
    });

    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('text/event-stream');
    expect(res.headers.get('cache-control')).toBe('no-cache, no-transform');
    expect(await res.text()).toBe(EVENTS.join(''));
    expect(received.at(-1)).toMatchObject({
      url: '/v1/chat',
      headers: { authorization: 'Bearer svc-token', 'x-request-id': 'req-chat' },
      body: {
        messages: [{ role: 'user', content: 'Hallo?' }],
        domains: ['devops'],
        user: { sub: 'chat-user', roles: ['viewer'] },
      },
    });
  });

  it('a client disconnect mid-stream closes the upstream request', async () => {
    respond = (res) => {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write(EVENTS[0]); // …and never ends, like an LLM still generating
    };
    const abort = new AbortController();
    const res = await post('/chat', { messages: [] }, 'abort-mid', abort.signal);
    await res.body!.getReader().read();

    abort.abort();

    await received.at(-1)!.closed;
  });

  it('a client disconnect before the first event closes the upstream request', async () => {
    respond = () => {}; // still retrieving: no headers yet
    const abort = new AbortController();
    const pending = post('/chat', { messages: [] }, 'abort-early', abort.signal).catch(
      () => undefined,
    );
    const count = received.length;
    await vi.waitFor(() => expect(received.length).toBe(count + 1));

    abort.abort();

    await received.at(-1)!.closed;
    await pending;
  });

  it('upstream validation errors come back as problem+json with their detail', async () => {
    respond = (res) => {
      res.writeHead(422, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ detail: [{ loc: ['body', 'messages'], msg: 'Too short' }] }));
    };
    const res = await post('/chat', {}, 'invalid');

    expect(res.status).toBe(422);
    expect(res.headers.get('content-type')).toMatch(/^application\/problem\+json/);
    expect(await res.json()).toMatchObject({ status: 422, detail: 'messages: Too short' });
  });

  it('more than CHAT_THROTTLE_PER_MIN (3 in tests) chats a minute → 429', async () => {
    respond = streamAll;
    for (let i = 0; i < 3; i++) await (await post('/chat', { messages: [] }, 'chatty')).text();

    const res = await post('/chat', { messages: [] }, 'chatty');

    expect(res.status).toBe(429);
    expect(await post('/chat', { messages: [] }, 'quiet')).toHaveProperty('status', 200);
  });

  it('search relays the AI service response', async () => {
    const hits = { embedding_model: 'test-model', hits: [] };
    respond = (res) => res.end(JSON.stringify(hits));
    const res = await post('/search', { query: 'rollback', top_k: 3 });

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(hits);
    expect(received.at(-1)).toMatchObject({
      url: '/v1/search',
      body: { query: 'rollback', top_k: 3 },
    });
  });
});
