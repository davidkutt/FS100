import type { INestApplication } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import request from 'supertest';
import type { App } from 'supertest/types.js';
import { DB, type Db } from '../src/db/db.module.js';
import { auditLog, documents } from '../src/db/schema.js';
import { fetchDocument } from '../src/documents/fetch-url.js';
import { createApp, EDITOR, token } from './support.js';

// The SSRF guard has its own spec; here every allowed URL serves the same Markdown file.
vi.mock('../src/documents/fetch-url.js', () => ({
  fetchDocument: vi.fn(async (url: URL) => {
    const buffer = Buffer.from(`# Fetched from ${url.pathname}\n`);
    return { originalname: url.pathname.split('/').at(-1), buffer, size: buffer.length };
  }),
}));

describe('Internal ingest from a URL (e2e)', () => {
  let app: INestApplication<App>;
  let db: Db;
  const ai = {
    ingest: vi.fn(async (form: FormData) => ({
      doc_id: form.get('doc_id'),
      chunk_count: 1,
      page_count: null,
      embedding_model: 'test-model',
    })),
  };

  beforeAll(async () => {
    app = await createApp(ai);
    db = app.get(DB);
  });

  afterAll(async () => {
    await app.close();
  });

  const service = () =>
    token([], { sub: 'service-account-kb-ai', clientRoles: ['ingest-on-behalf'] });
  const fromUrl = async (bearer: string, body: object, path = '/internal/documents/from-url') =>
    request(app.getHttpServer()).post(path).auth(bearer, { type: 'bearer' }).send(body);
  const BODY = {
    url: 'https://raw.githubusercontent.com/davidkutt/FS100/main/runbook.md',
    domains: ['devops'],
    onBehalfOf: { sub: 'bob-sub', name: 'Bob Editor' },
  };

  it("adds the document as the named user's, audited with the service identity", async () => {
    const res = await fromUrl(await service(), BODY);

    expect(res.status).toBe(202);
    expect(res.body).toEqual({ id: expect.any(String), status: 'pending' });
    expect(vi.mocked(fetchDocument).mock.calls.at(-1)!.slice(1)).toEqual([
      ['raw.githubusercontent.com'],
      1024 * 1024,
    ]);
    await vi.waitFor(async () => {
      const [doc] = await db.select().from(documents).where(eq(documents.id, res.body.id));
      expect(doc).toMatchObject({
        ownerId: 'bob-sub',
        ownerName: 'Bob Editor',
        filename: 'runbook.md',
        domains: ['devops'],
        status: 'ready',
      });
    });
    const [entry] = await db.select().from(auditLog).where(eq(auditLog.tool, 'documents.from_url'));
    expect(entry).toMatchObject({
      actorId: 'bob-sub',
      serviceIdentity: 'Test User',
      kind: 'write',
      argsRedacted: { docId: res.body.id, url: BODY.url, domains: ['devops'] },
      outcome: 'ok',
    });
  });

  it.each([
    ['a user without the service role', () => token(EDITOR), 403],
    [
      'a token for another audience',
      () => token([], { aud: 'kb-ai', clientRoles: ['ingest-on-behalf'] }),
      401,
    ],
  ])('refuses %s', async (_case, bearer, status) => {
    expect((await fromUrl(await bearer(), BODY)).status).toBe(status);
  });

  it('validates the body and lives outside /api', async () => {
    const ftp = await fromUrl(await service(), { ...BODY, url: 'ftp://example.com/a.md' });
    const prefixed = await fromUrl(await service(), BODY, '/api/internal/documents/from-url');

    expect(ftp.status).toBe(400);
    expect(prefixed.status).toBe(404);
  });
});
