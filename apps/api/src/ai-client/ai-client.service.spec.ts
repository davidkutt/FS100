import { HttpException } from '@nestjs/common';
import type { Config } from '../config.js';
import { type AgentRequest, AiClient } from './ai-client.service.js';

const config = {
  KEYCLOAK_ISSUER: 'http://kc/realms/kb',
  KEYCLOAK_CLIENT_ID: 'kb-api',
  KEYCLOAK_CLIENT_SECRET: 'secret',
  AI_SERVICE_URL: 'http://ai',
  AI_SERVICE_AUDIENCE: 'kb-ai',
} as Config;

describe('AiClient', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('caches the service token and forwards the request id', async () => {
    const fetchMock = vi.fn(async (url: string | URL) =>
      String(url).endsWith('/token')
        ? Response.json({ access_token: 'svc-token', expires_in: 300 })
        : Response.json({ status: 'ok' }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const client = new AiClient(config);

    await client.get('/v1/status', 'req-1');
    const body = await client.get('/v1/status', 'req-2');

    expect(body).toEqual({ status: 'ok' });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/token'))).toHaveLength(1);
    expect(fetchMock).toHaveBeenLastCalledWith(
      new URL('http://ai/v1/status'),
      expect.objectContaining({
        headers: { authorization: 'Bearer svc-token', 'x-request-id': 'req-2' },
      }),
    );
  });

  it('exchanges a user token once until it nears expiry, and afresh for a resume', async () => {
    const forms: URLSearchParams[] = [];
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      if (!String(url).endsWith('/token')) return new Response('event: done\ndata: {}\n\n');
      forms.push(init!.body as URLSearchParams);
      return Response.json({ access_token: `exchanged-${forms.length}`, expires_in: 300 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const client = new AiClient(config);
    const { signal } = new AbortController();
    const body = { conversation_id: 'c', messages: [] } as unknown as AgentRequest;

    await client.agent(body, 'req-1', signal, 'user-a');
    await client.agent(body, 'req-2', signal, 'user-a');
    await client.agent(body, 'req-3', signal, 'user-a', true);

    expect(forms.map((form) => Object.fromEntries(form))).toEqual([
      {
        grant_type: 'urn:ietf:params:oauth:grant-type:token-exchange',
        subject_token: 'user-a',
        subject_token_type: 'urn:ietf:params:oauth:token-type:access_token',
        audience: 'kb-ai',
        client_id: 'kb-api',
        client_secret: 'secret',
      },
      expect.objectContaining({ subject_token: 'user-a' }),
    ]);
    expect(fetchMock).toHaveBeenLastCalledWith(
      new URL('http://ai/v1/agent'),
      expect.objectContaining({
        headers: expect.objectContaining({ authorization: 'Bearer exchanged-2' }),
      }),
    );
  });

  it.each([
    [422, 422, { detail: 'Unsupported file type' }, 'Unsupported file type'],
    [401, 502, { detail: 'Signature verification failed' }, 'AI service /v1/status: HTTP 401'],
    [500, 502, 'Internal Server Error', 'AI service /v1/status: HTTP 500'],
  ])('upstream HTTP %i → HTTP %i', async (upstream, status, body, message) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string | URL) =>
        String(url).endsWith('/token')
          ? Response.json({ access_token: 'svc-token', expires_in: 300 })
          : Response.json(body, { status: upstream }),
      ),
    );

    const error = await new AiClient(config).get('/v1/status', 'req').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(HttpException);
    expect(error).toMatchObject({ status, message });
  });
});
