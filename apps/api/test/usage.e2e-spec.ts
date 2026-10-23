import { randomUUID } from 'node:crypto';
import type { INestApplication } from '@nestjs/common';
import type { App } from 'supertest/types.js';
import { z } from 'zod';
import { DB, type Db } from '../src/db/db.module.js';
import { usage } from '../src/db/schema.js';
import { MyUsage, UserUsageDay } from '../src/usage/usage.controller.js';
import { ADMIN, createApp, EDITOR, fakeAiService, token } from './support.js';

const DAY_MS = 86_400_000;
const CHAT_DONE = {
  usage: { inputTokens: 3, outputTokens: 2, costUsd: 0.01 },
  model: 'm',
  traceId: null,
};

/** Daily caps by role (D44) against seeded `usage` rows. */
describe('Usage and daily caps (e2e)', () => {
  let app: INestApplication<App>;
  let apiUrl: string;
  let db: Db;
  let upstream: Awaited<ReturnType<typeof fakeAiService>>;

  beforeAll(async () => {
    upstream = await fakeAiService();
    upstream.respond = (res) => {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.end(`event: done\ndata: ${JSON.stringify(CHAT_DONE)}\n\n`);
    };
    app = await createApp(upstream.ai);
    await app.listen(0, '127.0.0.1');
    apiUrl = await app.getUrl();
    db = app.get(DB);
  });

  afterAll(async () => {
    await app.close();
    upstream.close();
  });

  const call = async (
    method: string,
    path: string,
    { sub = 'someone', roles = ['viewer'], body = undefined as unknown } = {},
  ) =>
    fetch(`${apiUrl}/api${path}`, {
      method,
      headers: {
        authorization: `Bearer ${await token(roles, { sub })}`,
        'content-type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

  const spend = (userId: string, costUsd: number, daysAgo = 0) =>
    db.insert(usage).values({
      userId,
      model: 'm',
      inputTokens: 10,
      outputTokens: 5,
      costUsd,
      createdAt: new Date(Date.now() - daysAgo * DAY_MS),
    });

  const mine = async (sub: string, roles = ['viewer']) =>
    MyUsage.parse(await (await call('GET', '/me/usage', { sub, roles })).json());

  it('reports today against the highest role’s cap, and the last 30 days', async () => {
    await spend('dora', 0.1);
    await spend('dora', 0.05);
    await spend('dora', 0.3, 2);
    await spend('dora', 9, 40);

    const report = await mine('dora', EDITOR);

    expect(report.capUsd).toBe(1);
    expect(report.today).toMatchObject({ costUsd: 0.15, turns: 2, inputTokens: 20 });
    expect(report.days.map((day) => day.costUsd)).toEqual([0.15, 0.3]);
    expect((await mine('nobody')).today).toMatchObject({ costUsd: 0, turns: 0 });
  });

  it('answers 429 on every LLM relay once the cap is reached, before calling the AI service', async () => {
    await spend('erin', 0.2);
    const created = await call('POST', '/conversations', { sub: 'erin', body: {} });
    const { id } = (await created.json()) as { id: string };
    const received = upstream.received.length;

    const responses = [
      await call('POST', `/conversations/${id}/messages`, { sub: 'erin', body: { text: 'Hi' } }),
      await call('POST', '/chat', { sub: 'erin', body: { messages: [] } }),
      await call('POST', `/approvals/${randomUUID()}`, {
        sub: 'erin',
        body: { decision: 'approve' },
      }),
    ];

    for (const res of responses) {
      expect(res.status).toBe(429);
      expect(res.headers.get('content-type')).toContain('application/problem+json');
      expect(await res.json()).toMatchObject({
        type: 'daily_cap_exceeded',
        detail: expect.stringContaining('0.20 USD'),
      });
    }
    expect(upstream.received.length).toBe(received);
  });

  it('counts /api/chat towards the cap', async () => {
    await spend('finn', 0.19);

    const res = await call('POST', '/chat', { sub: 'finn', body: { messages: [] } });
    await res.text();

    expect(res.status).toBe(200);
    expect((await mine('finn')).today.costUsd).toBe(0.2);
    expect((await call('POST', '/chat', { sub: 'finn', body: { messages: [] } })).status).toBe(429);
  });

  it('lists usage per user and day for admins only', async () => {
    await spend('gus', 0.01, 1);
    await spend('gus', 0.02, 1);

    const res = await call('GET', '/admin/usage?user=gus', { roles: ADMIN });

    expect(z.array(UserUsageDay).parse(await res.json())).toEqual([
      {
        userId: 'gus',
        day: new Date(Date.now() - DAY_MS).toISOString().slice(0, 10),
        inputTokens: 20,
        cachedTokens: 0,
        outputTokens: 10,
        costUsd: 0.03,
        turns: 2,
      },
    ]);
    expect((await call('GET', '/admin/usage', { roles: EDITOR })).status).toBe(403);
  });
});
