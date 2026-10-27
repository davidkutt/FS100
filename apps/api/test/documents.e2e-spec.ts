import { randomUUID } from 'node:crypto';
import { BadGatewayException, type INestApplication } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import request from 'supertest';
import type { App } from 'supertest/types.js';
import type { JobStatus } from '../src/ai-client/ai-client.service.js';
import { DB, type Db } from '../src/db/db.module.js';
import { auditLog, type DocumentStatus } from '../src/db/schema.js';
import { DocumentDto } from '../src/documents/documents.controller.js';
import { DocumentsService } from '../src/documents/documents.service.js';
import { ADMIN, EDITOR, createApp, token } from './support.js';

describe('Documents (e2e)', () => {
  let app: INestApplication<App>;
  // The AI service's job per id; unset = ready.
  const jobs = new Map<string, Partial<JobStatus>>();
  let lastJob = 0;
  const STATUS = { alias: 'kb_current', collection: 'kb__v2__new', runs: [] };
  const ai = {
    submit: vi.fn(async (_form: FormData) => ({ job_id: ++lastJob, version: 1 })),
    job: vi.fn(async (id: string) => ({
      id: Number(id),
      state: 'ready',
      result: { doc_id: '', chunk_count: 3, page_count: null, embedding_model: 'test-model' },
      ...jobs.get(id),
    })),
    deleteDocument: vi.fn(async () => undefined),
    updateLabels: vi.fn(async () => undefined),
    reindex: vi.fn(async () => 7),
    reindexStatus: vi.fn(async () => STATUS),
    rollback: vi.fn(async () => ({ alias: 'kb_current', collection: 'kb__v2__old' })),
  };

  beforeAll(async () => {
    app = await createApp(ai);
  });

  afterAll(async () => {
    await app.close();
  });

  const upload = async (
    filename: string,
    content: string | Buffer,
    status: number,
    { roles = EDITOR, sub = 'user-1', domains = ['devops'], topics = [] as string[] } = {},
  ) => {
    const req = request(app.getHttpServer())
      .post('/api/documents')
      .auth(await token(roles, { sub }), { type: 'bearer' });
    for (const domain of domains) void req.field('domains', domain);
    for (const topic of topics) void req.field('topics', topic);
    return req.attach('file', Buffer.from(content), filename).expect(status);
  };

  const list = async () => {
    const res = await request(app.getHttpServer())
      .get('/api/documents')
      .auth(await token(['viewer']), { type: 'bearer' })
      .expect(200);
    return DocumentDto.array().parse(res.body);
  };

  const settled = (id: string, status: DocumentStatus) =>
    vi.waitFor(async () => {
      const doc = (await list()).find((d) => d.id === id);
      expect(doc?.status).toBe(status);
      return doc!;
    });

  const relabel = async (
    id: string,
    body: object,
    status: number,
    roles = EDITOR,
    sub = 'user-1',
  ) =>
    request(app.getHttpServer())
      .patch(`/api/documents/${id}`)
      .auth(await token(roles, { sub }), { type: 'bearer' })
      .send(body)
      .expect(status);

  const remove = async (id: string, roles: string[], status: number, sub = 'user-1') =>
    request(app.getHttpServer())
      .delete(`/api/documents/${id}`)
      .auth(await token(roles, { sub }), { type: 'bearer' })
      .expect(status);

  it('editor upload → 202, queued in the AI service → ready', async () => {
    const res = await upload('Übersicht.md', '# Rollback\nkubectl rollout undo', 202, {
      domains: ['devops', 'sre'],
    });

    const doc = await settled(res.body.id, 'ready');
    expect(doc).toMatchObject({
      filename: 'Übersicht.md',
      mime: 'text/markdown',
      ownerId: 'user-1',
      domains: ['devops', 'sre'],
      chunkCount: 3,
      embeddingModel: 'test-model',
      jobId: String(lastJob),
      version: 1,
    });
    const form = ai.submit.mock.calls.at(-1)![0];
    expect(form.get('doc_id')).toBe(doc.id);
    expect(form.getAll('domains')).toEqual(['devops', 'sre']);
    expect((form.get('file') as File).name).toBe('Übersicht.md');
  });

  it('topics from the taxonomy go along to the ingest; unknown ones → 400', async () => {
    const res = await upload('topics.md', `# T ${randomUUID()}`, 202, {
      topics: ['devops/ci-cd'],
    });

    expect((await settled(res.body.id, 'ready')).topics).toEqual(['devops/ci-cd']);
    expect(ai.submit.mock.calls.at(-1)![0].getAll('topics')).toEqual(['devops/ci-cd']);
    const bad = await upload('bad.md', `# B ${randomUUID()}`, 400, { topics: ['devops/nope'] });
    expect(bad.body.detail).toBe('Unknown topics: devops/nope');
  });

  it('owners relabel without re-ingesting; others, viewers and bad labels are refused', async () => {
    const { body } = await upload('labels.md', `# L ${randomUUID()}`, 202, { sub: 'user-4' });
    await settled(body.id, 'ready');
    const ingests = ai.submit.mock.calls.length;
    const labels = { domains: ['devops', 'sre'], topics: ['devops/deployment'] };

    const res = await relabel(body.id, labels, 200, EDITOR, 'user-4');

    expect(DocumentDto.parse(res.body)).toMatchObject(labels);
    expect(ai.updateLabels).toHaveBeenLastCalledWith(body.id, labels, expect.any(String));
    expect(ai.submit.mock.calls.length).toBe(ingests);
    await relabel(body.id, { topics: [] }, 200, ADMIN);
    await relabel(body.id, { topics: [] }, 403);
    await relabel(body.id, { topics: [] }, 403, ['viewer'], 'user-4');
    await relabel(body.id, {}, 400, EDITOR, 'user-4');
    await relabel(body.id, { domains: [] }, 400, EDITOR, 'user-4');
    await relabel(body.id, { topics: ['sre/x'] }, 400, EDITOR, 'user-4');
    await relabel(randomUUID(), { topics: [] }, 404, ADMIN);
    const audited = await app
      .get<Db>(DB)
      .select()
      .from(auditLog)
      .where(eq(auditLog.tool, 'documents.relabel'));
    expect(audited.map((row) => [row.actorId, row.argsRedacted])).toEqual([
      ['user-4', { docId: body.id, ...labels }],
      ['user-1', { docId: body.id, topics: [] }],
    ]);
  });

  it('owners set priority, scope and lifecycle; the AI service gets them, the audit too', async () => {
    const { body } = await upload('pinned.md', `# P ${randomUUID()}`, 202, { sub: 'user-4' });
    await settled(body.id, 'ready');
    const pin = { priority: 'canonical', priorityTopics: ['devops/ci-cd'] };

    const pinned = await relabel(body.id, pin, 200, EDITOR, 'user-4');
    const retired = await relabel(body.id, { lifecycle: 'retired' }, 200, EDITOR, 'user-4');

    expect(DocumentDto.parse(pinned.body)).toMatchObject({ ...pin, lifecycle: 'active' });
    expect(DocumentDto.parse(retired.body)).toMatchObject({ ...pin, lifecycle: 'retired' });
    expect(ai.updateLabels).toHaveBeenCalledWith(
      body.id,
      { priority: 'canonical', priority_topics: ['devops/ci-cd'] },
      expect.any(String),
    );
    await relabel(body.id, { priorityTopics: ['sre/x'] }, 400, EDITOR, 'user-4');
    await relabel(body.id, { priority: 'top' }, 400, EDITOR, 'user-4');
    await relabel(body.id, { lifecycle: 'staged' }, 400, EDITOR, 'user-4');
    await relabel(body.id, { lifecycle: 'active' }, 403);
    const audited = await app
      .get<Db>(DB)
      .select()
      .from(auditLog)
      .where(eq(auditLog.tool, 'documents.relabel'));
    expect(audited.slice(-2).map((row) => row.argsRedacted)).toEqual([
      { docId: body.id, ...pin },
      { docId: body.id, lifecycle: 'retired' },
    ]);
  });

  it('the same content again → 409, whatever the filename', async () => {
    await upload('a.txt', 'same bytes', 202);
    const res = await upload('b.txt', 'same bytes', 409);

    expect(res.body.detail).toMatch(/Already uploaded as "a.txt"/);
  });

  it('viewer upload → 403', async () => {
    await upload('x.txt', 'x', 403, { roles: ['viewer'] });
  });

  it.each([
    ['an unknown domain', ['cooking']],
    ['no domain', []],
  ])('%s → 400', async (_case, domains) => {
    await upload('y.txt', `y ${randomUUID()}`, 400, { domains });
  });

  it.each([
    ['binary.md', Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00, 0x01])],
    ['fake.pdf', 'not a pdf'],
    ['tool.exe', 'MZ'],
  ])('%s → 415', async (filename, content) => {
    await upload(filename, content, 415);
  });

  it('a file over UPLOAD_MAX_MB (1 in tests) → 413', async () => {
    await upload('big.txt', Buffer.alloc(1024 * 1024 + 1, 'a'), 413);
  });

  it('a failed job or an unreachable AI service → failed with the detail', async () => {
    jobs.set(String(lastJob + 1), { state: 'failed', error: 'No extractable text (scanned PDF?)' });
    const scan = await upload('scan.pdf', '%PDF-1.7 scanned', 202);
    ai.submit.mockRejectedValueOnce(new BadGatewayException('AI service unreachable'));
    const down = await upload('down.txt', `down ${randomUUID()}`, 202);

    expect((await settled(scan.body.id, 'failed')).error).toBe(
      'No extractable text (scanned PDF?)',
    );
    expect((await settled(down.body.id, 'failed')).error).toBe('AI service unreachable');
  });

  it('editors delete only their own documents, admins any; vectors go first', async () => {
    const { body: own } = await upload('own.txt', 'own', 202, { sub: 'user-2' });
    const { body: other } = await upload('other.txt', 'other', 202, { sub: 'user-3' });
    await settled(own.id, 'ready');
    await settled(other.id, 'ready');

    await remove(own.id, EDITOR, 403);
    await remove(own.id, ['viewer'], 403, 'user-2');
    await remove(own.id, EDITOR, 204, 'user-2');
    expect(ai.deleteDocument).toHaveBeenLastCalledWith(own.id, expect.any(String));
    await remove(other.id, ADMIN, 204);

    const ids = (await list()).map((d) => d.id);
    expect(ids).not.toContain(own.id);
    expect(ids).not.toContain(other.id);
    await remove(randomUUID(), ADMIN, 404);
    await remove('not-a-uuid', ADMIN, 400);
  });

  it('a running ingest blocks delete and relabel; a queued one is deleted (cancelled)', async () => {
    jobs.set(String(lastJob + 1), { state: 'parsing' });
    jobs.set(String(lastJob + 2), { state: 'queued' });
    const { body: running } = await upload('running.txt', 'running', 202);
    const { body: queued } = await upload('queued.txt', 'queued', 202);
    await settled(running.id, 'parsing');
    await settled(queued.id, 'queued');

    await remove(running.id, EDITOR, 409);
    await relabel(running.id, { topics: [] }, 409);
    await relabel(queued.id, { topics: [] }, 409);
    await remove(queued.id, EDITOR, 204);

    expect(ai.deleteDocument).toHaveBeenLastCalledWith(queued.id, expect.any(String));
    jobs.delete(String(lastJob - 1));
    expect((await settled(running.id, 'ready')).chunkCount).toBe(3);
  });

  it('boot recovery fails uploads the AI service never got; queued jobs resume', async () => {
    jobs.set(String(lastJob + 1), { state: 'embedding' });
    const { body: working } = await upload('working.txt', 'working', 202);
    await settled(working.id, 'embedding');
    ai.submit.mockImplementationOnce(() => new Promise(() => {}));
    const { body: lost } = await upload('lost.txt', 'lost', 202);
    await settled(lost.id, 'pending');

    await app.get(DocumentsService).onApplicationBootstrap();

    expect((await settled(lost.id, 'failed')).error).toMatch(/Interrupted by an API restart/);
    expect((await list()).find((d) => d.id === working.id)?.status).toBe('embedding');
  });

  it('admins re-index and roll back through the AI service; both are audited', async () => {
    const admin = await token(ADMIN, { sub: 'alice' });
    const call = (method: 'get' | 'post', path: string, bearer = admin) =>
      request(app.getHttpServer())[method](`/api/admin/reindex${path}`).auth(bearer, {
        type: 'bearer',
      });

    const started = await call('post', '').send({ reason: 'new chunker' }).expect(202);
    const status = await call('get', '').expect(200);
    const rolledBack = await call('post', '/rollback').expect(200);
    await call('post', '', await token(EDITOR))
      .send({})
      .expect(403);
    await call('post', '').send({ force: true }).expect(400);

    expect(started.body).toEqual({ jobId: 7 });
    expect(ai.reindex).toHaveBeenCalledWith(
      { reason: 'new chunker', force: false },
      expect.any(String),
      admin,
    );
    expect(status.body).toEqual(STATUS);
    expect(rolledBack.body).toEqual({ alias: 'kb_current', collection: 'kb__v2__old' });
    const audited = await app
      .get<Db>(DB)
      .select()
      .from(auditLog)
      .where(eq(auditLog.actorId, 'alice'));
    expect(audited.map((row) => [row.tool, row.argsRedacted])).toEqual([
      ['kb.reindex', { jobId: 7, reason: 'new chunker', force: false }],
      ['kb.rollback', { alias: 'kb_current', collection: 'kb__v2__old' }],
    ]);
  });
});
