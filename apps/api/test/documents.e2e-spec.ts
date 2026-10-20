import { randomUUID } from 'node:crypto';
import { type INestApplication, UnprocessableEntityException } from '@nestjs/common';
import request from 'supertest';
import type { App } from 'supertest/types.js';
import { DocumentDto } from '../src/documents/documents.controller.js';
import { DocumentsService } from '../src/documents/documents.service.js';
import { ADMIN, EDITOR, createApp, token } from './support.js';

describe('Documents (e2e)', () => {
  let app: INestApplication<App>;
  const ai = {
    ingest: vi.fn(async (form: FormData) => ({
      doc_id: form.get('doc_id'),
      chunk_count: 3,
      page_count: null,
      embedding_model: 'test-model',
    })),
    deleteDocument: vi.fn(async () => undefined),
    updateLabels: vi.fn(async () => undefined),
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

  const settled = (id: string, status: 'ready' | 'failed' | 'processing') =>
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

  it('editor upload → 202, ingested in the background → ready', async () => {
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
    });
    const form = ai.ingest.mock.calls.at(-1)![0];
    expect(form.get('doc_id')).toBe(doc.id);
    expect(form.getAll('domains')).toEqual(['devops', 'sre']);
    expect((form.get('file') as File).name).toBe('Übersicht.md');
  });

  it('topics from the taxonomy go along to the ingest; unknown ones → 400', async () => {
    const res = await upload('topics.md', `# T ${randomUUID()}`, 202, {
      topics: ['devops/ci-cd'],
    });

    expect((await settled(res.body.id, 'ready')).topics).toEqual(['devops/ci-cd']);
    expect(ai.ingest.mock.calls.at(-1)![0].getAll('topics')).toEqual(['devops/ci-cd']);
    const bad = await upload('bad.md', `# B ${randomUUID()}`, 400, { topics: ['devops/nope'] });
    expect(bad.body.detail).toBe('Unknown topics: devops/nope');
  });

  it('owners relabel without re-ingesting; others, viewers and bad labels are refused', async () => {
    const { body } = await upload('labels.md', `# L ${randomUUID()}`, 202, { sub: 'user-4' });
    await settled(body.id, 'ready');
    const ingests = ai.ingest.mock.calls.length;
    const labels = { domains: ['devops', 'sre'], topics: ['devops/deployment'] };

    const res = await relabel(body.id, labels, 200, EDITOR, 'user-4');

    expect(DocumentDto.parse(res.body)).toMatchObject(labels);
    expect(ai.updateLabels).toHaveBeenLastCalledWith(body.id, labels, expect.any(String));
    expect(ai.ingest.mock.calls.length).toBe(ingests);
    await relabel(body.id, { topics: [] }, 200, ADMIN);
    await relabel(body.id, { topics: [] }, 403);
    await relabel(body.id, { topics: [] }, 403, ['viewer'], 'user-4');
    await relabel(body.id, {}, 400, EDITOR, 'user-4');
    await relabel(body.id, { domains: [] }, 400, EDITOR, 'user-4');
    await relabel(body.id, { topics: ['sre/x'] }, 400, EDITOR, 'user-4');
    await relabel(randomUUID(), { topics: [] }, 404, ADMIN);
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

  it('a failed ingest → failed with the AI service detail', async () => {
    ai.ingest.mockRejectedValueOnce(
      new UnprocessableEntityException('No extractable text (scanned PDF?)'),
    );
    const res = await upload('scan.pdf', '%PDF-1.7 scanned', 202);

    const doc = await settled(res.body.id, 'failed');
    expect(doc.error).toBe('No extractable text (scanned PDF?)');
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

  it('delete during ingest → 409; boot recovery fails interrupted uploads', async () => {
    ai.ingest.mockImplementationOnce(() => new Promise(() => {}));
    const { body } = await upload('slow.txt', 'slow', 202);
    await settled(body.id, 'processing');

    await remove(body.id, EDITOR, 409);
    await relabel(body.id, { topics: [] }, 409);

    await app.get(DocumentsService).onApplicationBootstrap();
    const doc = await settled(body.id, 'failed');
    expect(doc.error).toMatch(/Interrupted by an API restart/);
  });
});
