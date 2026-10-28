import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { INestApplication } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import request from 'supertest';
import type { App } from 'supertest/types.js';
import { DB, type Db } from '../src/db/db.module.js';
import { documents } from '../src/db/schema.js';
import { SourcesService, SyncResult } from '../src/documents/sources.service.js';
import { ADMIN, EDITOR, createApp, token } from './support.js';

// Every allowed URL serves `page`, as HTML.
let page = '<h1>Service</h1><p>v1</p>';
vi.mock('../src/documents/fetch-url.js', () => ({
  fetchDocument: vi.fn(async () => {
    const buffer = Buffer.from(page);
    return { originalname: 'service.html', buffer, size: buffer.length };
  }),
}));

describe('Sources: notes folder and URLs (e2e)', () => {
  let app: INestApplication<App>;
  let db: Db;
  let dir: string;
  let lastJob = 0;
  const ai = {
    submit: vi.fn(async (_form: FormData) => ({ job_id: ++lastJob, version: lastJob })),
    job: vi.fn(async (id: string) => ({
      id: Number(id),
      state: 'ready',
      result: { doc_id: '', chunk_count: 1, page_count: null, embedding_model: 'test-model' },
    })),
    deleteDocument: vi.fn(async () => undefined),
  };

  beforeAll(async () => {
    dir = await mkdtemp(join(tmpdir(), 'notes-'));
    vi.stubEnv('NOTES_DIR', dir);
    vi.stubEnv('SOURCES_SYNC_MINUTES', '0');
    app = await createApp(ai);
    db = app.get(DB);
    await app.get(SourcesService).sync(); // the boot sync, on the empty folder
  });

  afterAll(async () => {
    await app.close();
    vi.unstubAllEnvs();
    await rm(dir, { recursive: true });
  });

  const post = async (roles: string[]) =>
    request(app.getHttpServer())
      .post('/api/admin/sources/sync')
      .auth(await token(roles), { type: 'bearer' });
  const sync = async () => {
    const res = await post(ADMIN);
    expect(res.status).toBe(200);
    return SyncResult.parse(res.body);
  };
  const note = async (path: string, text: string) => {
    await mkdir(join(dir, path, '..'), { recursive: true });
    await writeFile(join(dir, path), text);
  };
  const row = async (source: string) => {
    const [doc] = await db.select().from(documents).where(eq(documents.source, source));
    return doc;
  };
  // The ingest is handed over in the background; a source in work is left for the next sync.
  const handedOver = (source: string) =>
    vi.waitFor(async () => expect((await row(source)).status).not.toBe('pending'));

  it('adds notes with domains from the frontmatter, a domain folder or the default', async () => {
    await note('a.md', '---\ndomains: [sre]\ntopics: sre/incidents\n---\n# Pager\nAck it.');
    await note('devops/deploy.md', '# Deploy\nmake deploy');
    await note('misc/idea.md', '# Idea\nWrite more.');
    await note('.obsidian/workspace.md', '# not a note');
    await note('draft.txt', 'not Markdown');

    const result = await sync();

    expect(result).toMatchObject({ unchanged: 0, deleted: [], skipped: [] });
    expect(result.added.sort()).toEqual([
      'notes:a.md',
      'notes:devops/deploy.md',
      'notes:misc/idea.md',
    ]);
    expect(await row('notes:a.md')).toMatchObject({
      ownerId: 'notes',
      filename: 'a.md',
      domains: ['sre'],
      topics: ['sre/incidents'],
    });
    expect((await row('notes:devops/deploy.md')).domains).toEqual(['devops']);
    expect((await row('notes:misc/idea.md')).domains).toEqual(['dev']);
    await Promise.all(result.added.map(handedOver));
  });

  it('a changed note is a new version of the same document; unchanged ones stay', async () => {
    const before = await row('notes:devops/deploy.md');
    await note('devops/deploy.md', '# Deploy\nmake deploy, then check the dashboards');

    const result = await sync();
    await handedOver('notes:devops/deploy.md');

    expect(result).toMatchObject({ added: [], updated: ['notes:devops/deploy.md'], unchanged: 2 });
    const form = ai.submit.mock.calls.at(-1)![0];
    expect(form.get('doc_id')).toBe(before.id);
    const after = await row('notes:devops/deploy.md');
    expect([after.id, after.version]).toEqual([before.id, lastJob]);
    expect(after.sha256).not.toBe(before.sha256);
  });

  it('a deleted note leaves the knowledge base; an emptied folder deletes nothing', async () => {
    const idea = await row('notes:misc/idea.md');
    await rm(join(dir, 'misc'), { recursive: true });

    expect((await sync()).deleted).toEqual(['notes:misc/idea.md']);
    expect(ai.deleteDocument).toHaveBeenLastCalledWith(idea.id, expect.any(String));
    expect(await row('notes:misc/idea.md')).toBeUndefined();

    await rm(join(dir, 'a.md'));
    await rm(join(dir, 'devops'), { recursive: true });
    const emptied = await sync();

    expect(emptied.deleted).toEqual([]);
    expect(emptied.skipped).toEqual([
      { source: 'notes:', reason: `${dir} has no notes; its 2 indexed ones stay` },
    ]);
  });

  it('skips a note that looks like it holds a secret or has bad frontmatter', async () => {
    const submitted = ai.submit.mock.calls.length;
    await note('keys.md', `# Keys\nOPENROUTER=sk-or-v1-${'a'.repeat(32)}`);
    await note('bad.md', '---\ndomains: [cooking]\n---\n# Soup');

    const { skipped } = await sync();

    expect(skipped.map((s) => s.source)).toEqual(['notes:bad.md', 'notes:keys.md']);
    expect(skipped[1].reason).toBe(
      'Looks like it holds an API key (sk-…); not sent to the knowledge base',
    );
    expect(ai.submit.mock.calls.length).toBe(submitted);
  });

  it('re-fetches URL sources once a day: new content is a new version', async () => {
    const service = await token([], { sub: 'svc', clientRoles: ['ingest-on-behalf'] });
    const add = () =>
      request(app.getHttpServer())
        .post('/internal/documents/from-url')
        .auth(service, { type: 'bearer' })
        .send({
          url: 'https://raw.githubusercontent.com/x/service',
          domains: ['cloud'],
          onBehalfOf: { sub: 'bob-sub', name: 'Bob' },
        })
        .expect(202);
    const url = 'https://raw.githubusercontent.com/x/service';
    const { id } = (await add()).body;
    await handedOver(url);

    expect((await add()).body).toEqual({ id, status: 'unchanged' });
    page = '<h1>Service</h1><p>v2</p>';
    expect((await sync()).updated).toEqual([]); // fetched less than a day ago
    await db
      .update(documents)
      .set({ updatedAt: new Date(Date.now() - 25 * 60 * 60 * 1000) })
      .where(eq(documents.id, id));

    expect((await sync()).updated).toEqual([url]);
    await handedOver(url);
    expect(await row(url)).toMatchObject({
      id,
      ownerId: 'bob-sub',
      domains: ['cloud'],
      mime: 'text/html',
    });
  });

  it('only admins sync', async () => {
    expect((await post(EDITOR)).status).toBe(403);
  });
});
