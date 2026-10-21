import { randomUUID } from 'node:crypto';
import type { ServerResponse } from 'node:http';
import type { INestApplication } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import type { App } from 'supertest/types.js';
import { AuditEntryDto } from '../src/audit/audit.controller.js';
import { ApprovalDto, ConversationDetail } from '../src/conversations/conversations.controller.js';
import { DB, type Db } from '../src/db/db.module.js';
import { auditLog } from '../src/db/schema.js';
import { ADMIN, createApp, EDITOR, fakeAiService, token } from './support.js';

const ARGS = { title: 'Flaky test', body: 'x'.repeat(300) };
const WRITE = { id: 'call_w', name: 'github_sandbox.create_issue', kind: 'write', risk: 'medium' };
const READ = { id: 'call_r', name: 'kb.search_knowledge_base', kind: 'read', risk: 'low' };
const TOOLS = [
  { name: WRITE.name, description: '', kind: 'write', risk: 'medium', min_role: 'editor' },
];
const DONE = {
  answerStatus: 'answered',
  topScore: null,
  usage: {
    inputTokens: 1,
    cachedTokens: 0,
    outputTokens: 1,
    costUsd: null,
    steps: 1,
    toolCalls: 1,
  },
  model: 'm',
  promptVersion: 'agent-system@1',
  traceId: 'trace-1',
  protocolVersion: 2,
};
const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const proposal = (expiresAt: Date) => ({
  approvalId: randomUUID(),
  callId: WRITE.id,
  tool: WRITE.name,
  args: ARGS,
  risk: 'medium',
  expiresAt: expiresAt.toISOString(),
  signedAction: 'signed.action.secret',
});

/** Proposal and resume against a fake AI service; the API owns the state machine (ADR-0008). */
describe('Approvals and audit (e2e)', () => {
  let app: INestApplication<App>;
  let apiUrl: string;
  let db: Db;
  let upstream: Awaited<ReturnType<typeof fakeAiService>>;
  /** What `/v1/agent` streams next; `/v1/tools` always answers with TOOLS. */
  let agent: (res: ServerResponse) => void;

  beforeAll(async () => {
    upstream = await fakeAiService();
    upstream.respond = (res) => {
      if (upstream.received.at(-1)!.url === '/v1/tools') return void res.end(JSON.stringify(TOOLS));
      agent(res);
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

  const api = async (
    method: string,
    path: string,
    {
      body,
      sub = 'alice',
      roles = EDITOR,
    }: { body?: unknown; sub?: string; roles?: string[] } = {},
  ) =>
    fetch(`${apiUrl}/api${path}`, {
      method,
      headers: {
        authorization: `Bearer ${await token(roles, { sub })}`,
        'content-type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

  const streams = (...events: string[]) => {
    agent = (res) => {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      for (const event of events) res.write(event);
      res.end();
    };
  };

  const agentCalls = () => upstream.received.filter((r) => r.url === '/v1/agent');

  /** A conversation whose last answer stopped for approval. */
  const proposed = async (sub: string, expiresAt = new Date(Date.now() + 15 * 60_000)) => {
    const { id } = (await (await api('POST', '/conversations', { body: {}, sub })).json()) as {
      id: string;
    };
    const event = proposal(expiresAt);
    streams(
      sse('step', { n: 1 }),
      sse('tool_call', { ...WRITE, args: ARGS }),
      sse('approval_required', event),
      sse('done', { ...DONE, stopReason: 'awaiting_approval' }),
    );
    const relayed = await (
      await api('POST', `/conversations/${id}/messages`, { sub, body: { text: 'Open an issue' } })
    ).text();
    return { id, approvalId: event.approvalId, relayed };
  };

  const decide = (approvalId: string, body: unknown, sub = 'alice', roles = EDITOR) =>
    api('POST', `/approvals/${approvalId}`, { body, sub, roles });

  const detail = async (id: string, sub: string) =>
    ConversationDetail.parse(await (await api('GET', `/conversations/${id}`, { sub })).json());

  const audit = async (approvalId: string) =>
    (await db.select().from(auditLog).where(eq(auditLog.approvalId, approvalId))).map((row) => ({
      outcome: row.outcome,
      kind: row.kind,
      tool: row.tool,
    }));

  const succeeds = () =>
    streams(
      sse('tool_call', { ...WRITE, args: ARGS }),
      sse('tool_result', { id: WRITE.id, status: 'ok', summary: 'created #7', content: '…' }),
      sse('step', { n: 1 }),
      sse('tool_call', { ...READ, args: { query: 'issue #7', apiKey: 'k' } }),
      sse('tool_result', { id: READ.id, status: 'ok', summary: '0 hits', content: '…' }),
      sse('step', { n: 2 }),
      sse('token', { text: 'Created #7.' }),
      sse('done', { ...DONE, stopReason: 'end' }),
    );

  it('a write proposal is stored pending; the signed action never reaches the browser', async () => {
    const { id, approvalId, relayed } = await proposed('proposer');

    expect(relayed).toContain('event: approval_required');
    expect(relayed).not.toContain('signed.action.secret');
    expect(relayed).toContain(sse('tool_call', { ...WRITE, args: ARGS }));
    const raw = await (await api('GET', `/conversations/${id}`, { sub: 'proposer' })).text();
    expect(raw).not.toContain('signedAction');
    expect(raw).not.toContain('signed.action.secret');
    const conversation = await detail(id, 'proposer');
    expect(conversation.messages[1].parts).toContainEqual(
      expect.objectContaining({ type: 'approval_required', approvalId, args: ARGS }),
    );
    expect(conversation.approvals).toEqual([
      expect.objectContaining({ id: approvalId, status: 'pending', callId: WRITE.id, args: ARGS }),
    ]);
    const pending = (sub: string, roles = EDITOR) =>
      api('GET', '/approvals?status=pending', { sub, roles }).then(async (res) =>
        ApprovalDto.array()
          .parse(await res.json())
          .map((approval) => approval.id),
      );
    expect(await pending('proposer')).toEqual([approvalId]);
    expect(await pending('admin', ADMIN)).toContain(approvalId);
  });

  it('approve resumes the turn with the signed action once; a replay is a conflict', async () => {
    const { id, approvalId } = await proposed('approver');
    succeeds();

    const res = await decide(approvalId, { decision: 'approve' }, 'approver');
    const continuation = await res.text();
    const replay = await decide(approvalId, { decision: 'approve' }, 'approver');

    expect(res.status).toBe(200);
    expect(continuation).toContain('Created #7.');
    expect(agentCalls().at(-1)!.body).toMatchObject({
      conversation_id: id,
      messages: [{ role: 'user', parts: [{ type: 'text', text: 'Open an issue' }] }],
      resume: { signed_action: 'signed.action.secret', decision: 'approve', args: ARGS },
      user: { sub: 'approver' },
    });
    expect(replay.status).toBe(409);
    expect(await replay.json()).toMatchObject({ type: 'approval_state_conflict' });
    const conversation = await detail(id, 'approver');
    expect(conversation.approvals[0]).toMatchObject({ status: 'succeeded', error: null });
    expect(conversation.messages.map((m) => m.role)).toEqual(['user', 'assistant', 'assistant']);
    expect(await audit(approvalId)).toEqual([{ outcome: 'ok', kind: 'write', tool: WRITE.name }]);
  });

  it('a double click runs the action once', async () => {
    const { approvalId } = await proposed('clicker');
    succeeds();
    const before = agentCalls().length;

    const statuses = await Promise.all(
      [1, 2].map(async () => {
        const res = await decide(approvalId, { decision: 'approve' }, 'clicker');
        await res.text();
        return res.status;
      }),
    );

    expect(statuses.sort((a, b) => a - b)).toEqual([200, 409]);
    expect(agentCalls().length - before).toBe(1);
  });

  it('reject continues the turn with the note; nothing executes', async () => {
    const { id, approvalId } = await proposed('rejecter');
    streams(
      sse('tool_call', { ...WRITE, args: ARGS }),
      sse('tool_result', { id: WRITE.id, status: 'rejected', summary: 'rejected by the user' }),
      sse('done', { ...DONE, stopReason: 'end' }),
    );

    const res = await decide(approvalId, { decision: 'reject', note: 'Wrong repo' }, 'rejecter');
    await res.text();

    expect(agentCalls().at(-1)!.body).toMatchObject({
      resume: { decision: 'reject', note: 'Wrong repo' },
    });
    expect((await detail(id, 'rejecter')).approvals[0]).toMatchObject({
      status: 'rejected',
      note: 'Wrong repo',
    });
    expect(await audit(approvalId)).toEqual([
      { outcome: 'rejected', kind: 'write', tool: WRITE.name },
    ]);
  });

  it('another user cannot decide, not even an admin', async () => {
    const { id, approvalId } = await proposed('owner');
    const before = agentCalls().length;

    const intruder = await decide(approvalId, { decision: 'approve' }, 'intruder');
    const admin = await decide(approvalId, { decision: 'reject' }, 'admin', ADMIN);

    expect([intruder.status, admin.status]).toEqual([404, 404]);
    expect(agentCalls().length).toBe(before);
    expect((await detail(id, 'owner')).approvals[0].status).toBe('pending');
  });

  it('a role downgrade between proposal and approval is refused', async () => {
    const { id, approvalId } = await proposed('downgraded');
    const before = agentCalls().length;

    const res = await decide(approvalId, { decision: 'approve' }, 'downgraded', ['viewer']);

    expect(res.status).toBe(403);
    expect(await res.json()).toMatchObject({ type: 'tool_not_permitted' });
    expect(agentCalls().length).toBe(before);
    expect((await detail(id, 'downgraded')).approvals[0].status).toBe('pending');
  });

  it('an expired action is gone', async () => {
    const { id, approvalId } = await proposed('late', new Date(Date.now() - 1000));
    const before = agentCalls().length;

    const res = await decide(approvalId, { decision: 'approve' }, 'late');

    expect(res.status).toBe(410);
    expect(await res.json()).toMatchObject({ type: 'approval_expired' });
    expect(agentCalls().length).toBe(before);
    expect((await detail(id, 'late')).approvals[0].status).toBe('expired');
  });

  it('a stream that breaks after executing leaves the outcome unknown, never retried', async () => {
    const { id, approvalId } = await proposed('broken');
    agent = (res) => {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write(sse('tool_call', { ...WRITE, args: ARGS }), () => res.destroy());
    };

    await (await decide(approvalId, { decision: 'approve' }, 'broken')).text();
    const retry = await decide(approvalId, { decision: 'approve' }, 'broken');

    expect((await detail(id, 'broken')).approvals[0].status).toBe('unknown');
    expect(retry.status).toBe(409);
    expect(await audit(approvalId)).toEqual([
      { outcome: 'unknown', kind: 'write', tool: WRITE.name },
    ]);
  });

  it('an action the AI service refuses (e.g. tampered args) fails without running', async () => {
    const { id, approvalId } = await proposed('tampered');
    agent = (res) => {
      res.writeHead(422, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ detail: 'Invalid approval: the arguments differ' }));
    };

    const res = await decide(approvalId, { decision: 'approve' }, 'tampered');

    expect(res.status).toBe(422);
    expect((await detail(id, 'tampered')).approvals[0]).toMatchObject({
      status: 'failed',
      error: 'Invalid approval: the arguments differ',
    });
    expect(await audit(approvalId)).toEqual([
      { outcome: 'failed', kind: 'write', tool: WRITE.name },
    ]);
  });

  it('every tool result gets one redacted audit row that outlives the conversation', async () => {
    const { id, approvalId } = await proposed('audited');
    succeeds();
    await (await decide(approvalId, { decision: 'approve' }, 'audited')).text();
    const entries = async (query: string) => {
      const res = await api('GET', `/admin/audit?${query}`, { sub: 'admin', roles: ADMIN });
      return AuditEntryDto.array().parse(await res.json());
    };

    await api('DELETE', `/conversations/${id}`, { sub: 'audited' });

    expect(await entries('user=audited')).toEqual([
      expect.objectContaining({
        tool: READ.name,
        kind: 'read',
        approvalId: null,
        argsRedacted: { query: 'issue #7', apiKey: '[redacted]' },
      }),
      expect.objectContaining({
        actorId: 'audited',
        actorRoles: ['viewer', 'editor'], // the guard's order
        conversationId: id,
        approvalId,
        tool: WRITE.name,
        outcome: 'ok',
        traceId: 'trace-1',
        argsRedacted: { title: ARGS.title, body: `${'x'.repeat(200)}…` },
      }),
    ]);
    expect(await entries(`user=audited&tool=${READ.name}&outcome=ok`)).toHaveLength(1);
    expect(await entries('user=audited&from=2000-01-01&to=2000-01-02')).toEqual([]);
    expect((await api('GET', '/admin/audit', { sub: 'audited' })).status).toBe(403);
  });

  it('the audit log is append-only', async () => {
    await expect(db.update(auditLog).set({ outcome: 'ok' })).rejects.toThrow();
    await expect(db.delete(auditLog)).rejects.toThrow();
  });
});
