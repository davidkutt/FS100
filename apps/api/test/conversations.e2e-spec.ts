import { randomUUID } from 'node:crypto';
import type { ServerResponse } from 'node:http';
import type { INestApplication } from '@nestjs/common';
import type { App } from 'supertest/types.js';
import {
  ConversationDetail,
  ConversationDto,
} from '../src/conversations/conversations.controller.js';
import { ADMIN, createApp, fakeAiService, token } from './support.js';

const SOURCE = { n: 1, docId: randomUUID(), title: 'Rollback runbook', score: 0.82, text: '…' };
const TOOL_CALL = { id: 'call_1', name: 'kb.search_knowledge_base', kind: 'read', risk: 'low' };
const TOOL_RESULT = { id: 'call_1', status: 'ok', summary: '1 hits', durationMs: 12 };
const DONE = {
  stopReason: 'end',
  answerStatus: 'answered',
  topScore: 0.82,
  usage: { inputTokens: 100, cachedTokens: 40, outputTokens: 20, costUsd: 0.0012 },
  model: 'openai/gpt-6-luna',
  promptVersion: 'agent-system@1',
  traceId: 'trace-1',
  protocolVersion: 2,
};
const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const EVENTS = [
  sse('step', { n: 1 }),
  sse('tool_call', { ...TOOL_CALL, args: { query: 'rollback' } }),
  sse('tool_result', { ...TOOL_RESULT, content: '<tool_result>…', truncated: false }),
  sse('sources', { sources: [SOURCE] }),
  ': ping\n\n',
  sse('step', { n: 2 }),
  sse('token', { text: 'Roll back ' }),
  sse('token', { text: 'with helm [1].' }),
  sse('done', DONE),
];

/** Real sockets on both hops, so the tee sees the bytes the browser gets. */
describe('Conversations (e2e)', () => {
  let app: INestApplication<App>;
  let apiUrl: string;
  let upstream: Awaited<ReturnType<typeof fakeAiService>>;

  beforeAll(async () => {
    upstream = await fakeAiService();
    app = await createApp(upstream.ai);
    await app.listen(0, '127.0.0.1');
    apiUrl = await app.getUrl();
  });

  afterAll(async () => {
    await app.close();
    upstream.close();
  });

  const api = async (
    method: string,
    path: string,
    {
      body,
      sub = 'alice',
      roles = ['viewer'],
      signal = undefined as AbortSignal | undefined,
    } = {} as {
      body?: unknown;
      sub?: string;
      roles?: string[];
      signal?: AbortSignal;
    },
  ) =>
    fetch(`${apiUrl}/api${path}`, {
      method,
      headers: {
        authorization: `Bearer ${await token(roles, { sub })}`,
        'content-type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });

  const create = async (sub: string) =>
    ConversationDto.parse(await (await api('POST', '/conversations', { body: {}, sub })).json());

  const detail = async (id: string, sub: string) =>
    ConversationDetail.parse(await (await api('GET', `/conversations/${id}`, { sub })).json());

  const streamAll = (res: ServerResponse) => {
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    for (const event of EVENTS) res.write(event);
    res.end();
  };

  it('a turn relays SSE v2 unchanged and stores both messages with parts and gap signals', async () => {
    const { id } = await create('turn');
    upstream.respond = streamAll;

    const res = await api('POST', `/conversations/${id}/messages`, {
      sub: 'turn',
      body: { text: 'How do I roll back?', modelId: 'openai/gpt-6-luna', domains: ['devops'] },
    });

    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('text/event-stream');
    expect(await res.text()).toBe(EVENTS.join(''));
    expect(upstream.received.at(-1)).toMatchObject({
      url: '/v1/agent',
      headers: { authorization: 'Bearer svc-token' },
      body: {
        conversation_id: id,
        messages: [{ role: 'user', parts: [{ type: 'text', text: 'How do I roll back?' }] }],
        model: 'openai/gpt-6-luna',
        domains: ['devops'],
        user: { sub: 'turn', roles: ['viewer'] },
      },
    });
    const conversation = await detail(id, 'turn');
    expect(conversation).toMatchObject({
      title: 'How do I roll back?',
      modelId: 'openai/gpt-6-luna',
    });
    expect(conversation.messages.map((m) => m.role)).toEqual(['user', 'assistant']);
    expect(conversation.messages[1]).toMatchObject({
      parts: [
        { type: 'tool_call', ...TOOL_CALL, args: { query: 'rollback' } },
        { type: 'tool_result', ...TOOL_RESULT },
        { type: 'sources', sources: [SOURCE] },
        { type: 'text', text: 'Roll back with helm [1].' },
      ],
      stopReason: 'end',
      answerStatus: 'answered',
      topScore: 0.82,
      model: DONE.model,
      promptVersion: DONE.promptVersion,
      traceId: DONE.traceId,
      feedback: null,
    });
    expect(await (await api('GET', '/me/usage', { sub: 'turn' })).json()).toEqual({
      ...DONE.usage,
      turns: 1,
    });
  });

  it('the next turn gets the stored transcript as text, with the conversation model', async () => {
    const { id } = await create('history');
    upstream.respond = streamAll;
    await (
      await api('POST', `/conversations/${id}/messages`, {
        sub: 'history',
        body: { text: 'First?', modelId: 'm-1' },
      })
    ).text();

    await (
      await api('POST', `/conversations/${id}/messages`, {
        sub: 'history',
        body: { text: 'And then?', mode: 'rag' },
      })
    ).text();

    expect(upstream.received.at(-1)!.body).toMatchObject({
      mode: 'rag',
      model: 'm-1',
      messages: [
        { role: 'user', parts: [{ type: 'text', text: 'First?' }] },
        { role: 'assistant', parts: [{ type: 'text', text: 'Roll back with helm [1].' }] },
        { role: 'user', parts: [{ type: 'text', text: 'And then?' }] },
      ],
    });
    expect((await detail(id, 'history')).messages).toHaveLength(4);
  });

  it('a stop mid-run cancels the upstream and keeps the partial answer as cancelled', async () => {
    const { id } = await create('stop');
    upstream.respond = (res) => {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write(sse('token', { text: 'Partial' })); // …and never ends, like an LLM still generating
    };
    const abort = new AbortController();
    const res = await api('POST', `/conversations/${id}/messages`, {
      sub: 'stop',
      body: { text: 'Long one?' },
      signal: abort.signal,
    });
    await res.body!.getReader().read();

    abort.abort();

    await upstream.received.at(-1)!.closed;
    await vi.waitFor(async () => {
      const [, answer] = (await detail(id, 'stop')).messages;
      expect(answer).toMatchObject({
        parts: [{ type: 'text', text: 'Partial' }],
        stopReason: 'cancelled',
        answerStatus: null,
      });
    });
  });

  it('an upstream that breaks off ends the stream and is stored as error', async () => {
    const { id } = await create('broken');
    upstream.respond = (res) => {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write(sse('token', { text: 'Half' }), () => res.destroy());
    };

    const res = await api('POST', `/conversations/${id}/messages`, {
      sub: 'broken',
      body: { text: 'Q?' },
    });

    expect(await res.text()).toBe(sse('token', { text: 'Half' }));
    const [, answer] = (await detail(id, 'broken')).messages;
    expect(answer).toMatchObject({ stopReason: 'error', parts: [{ type: 'text', text: 'Half' }] });
  });

  it('a turn the AI service rejects comes back as problem+json and stores nothing', async () => {
    const { id } = await create('rejected');
    upstream.respond = (res) => {
      res.writeHead(422, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ detail: 'Model x is not available' }));
    };

    const res = await api('POST', `/conversations/${id}/messages`, {
      sub: 'rejected',
      body: { text: 'Q?', modelId: 'x' },
    });

    expect(res.status).toBe(422);
    expect(await res.json()).toMatchObject({ detail: 'Model x is not available' });
    expect(await detail(id, 'rejected')).toMatchObject({ messages: [], modelId: null });
  });

  it('an empty text → 400', async () => {
    const { id } = await create('empty');
    const res = await api('POST', `/conversations/${id}/messages`, {
      sub: 'empty',
      body: { text: '   ' },
    });

    expect(res.status).toBe(400);
  });

  it('conversations are private: others get 404, admins may delete any', async () => {
    const { id } = await create('owner');
    const forbidden = [
      api('GET', `/conversations/${id}`, { sub: 'intruder' }),
      api('DELETE', `/conversations/${id}`, { sub: 'intruder' }),
      api('POST', `/conversations/${id}/messages`, { sub: 'intruder', body: { text: 'Hi' } }),
    ];

    for (const res of await Promise.all(forbidden)) expect(res.status).toBe(404);
    const lists = await Promise.all(
      ['owner', 'intruder'].map(async (sub) =>
        (await api('GET', '/conversations', { sub })).json(),
      ),
    );
    expect(lists.map((list: unknown[]) => list.length)).toEqual([1, 0]);
    expect(
      (await api('DELETE', `/conversations/${id}`, { sub: 'admin', roles: ADMIN })).status,
    ).toBe(204);
    expect((await api('GET', `/conversations/${id}`, { sub: 'owner' })).status).toBe(404);
  });

  it('owners rate assistant messages, a second rating replaces the first', async () => {
    const { id } = await create('rater');
    upstream.respond = streamAll;
    await (
      await api('POST', `/conversations/${id}/messages`, {
        sub: 'rater',
        body: { text: 'Q?' },
      })
    ).text();
    const [question, answer] = (await detail(id, 'rater')).messages;
    const rate = (messageId: string, body: unknown, sub = 'rater') =>
      api('POST', `/messages/${messageId}/feedback`, { sub, body });

    expect((await rate(answer.id, { rating: 'up' })).status).toBe(204);
    expect((await rate(answer.id, { rating: 'down', comment: 'Wrong runbook' })).status).toBe(204);
    expect((await rate(answer.id, { rating: 'up' }, 'intruder')).status).toBe(404);
    expect((await rate(question.id, { rating: 'up' })).status).toBe(404);
    expect((await rate(answer.id, { rating: 'meh' })).status).toBe(400);
    expect((await detail(id, 'rater')).messages[1].feedback).toEqual({
      rating: 'down',
      comment: 'Wrong runbook',
    });
  });
});
