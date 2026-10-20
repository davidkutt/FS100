import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import type { App } from 'supertest/types.js';
import { Taxonomy } from '../src/catalog/taxonomy.js';
import { EDITOR, createApp, token } from './support.js';

const MODELS = [
  { id: 'cheap', label: 'Cheap', supports_tools: true, tier: 'low', min_role: 'viewer' },
  { id: 'pricey', label: 'Pricey', supports_tools: true, tier: 'high', min_role: 'editor' },
];
const TOOLS = [
  {
    name: 'kb.search_knowledge_base',
    description: '',
    kind: 'read',
    risk: 'low',
    min_role: 'viewer',
  },
  { name: 'kb.ingest_url', description: '', kind: 'write', risk: 'medium', min_role: 'editor' },
];

describe('Catalog (e2e)', () => {
  let app: INestApplication<App>;
  const ai = { get: vi.fn(async (path: string) => (path === '/v1/models' ? MODELS : TOOLS)) };

  beforeAll(async () => {
    app = await createApp(ai);
  });

  afterAll(async () => {
    await app.close();
  });

  const get = async (path: string, roles: string[]) =>
    request(app.getHttpServer())
      .get(`/api${path}`)
      .auth(await token(roles), { type: 'bearer' })
      .expect(200);

  it.each([
    ['viewer', ['viewer'], ['cheap'], ['kb.search_knowledge_base']],
    ['editor', EDITOR, ['cheap', 'pricey'], ['kb.search_knowledge_base', 'kb.ingest_url']],
  ])('models and tools are cut to the role (%s)', async (_role, roles, models, tools) => {
    const ids = (await get('/models', roles)).body.map((m: { id: string }) => m.id);
    const names = (await get('/tools', roles)).body.map((t: { name: string }) => t.name);

    expect([ids, names]).toEqual([models, tools]);
  });

  it('the taxonomy lists every domain with its topics', async () => {
    const taxonomy = Taxonomy.parse((await get('/taxonomy', ['viewer'])).body);

    expect(taxonomy.domains.devops.topics).toHaveProperty('ci-cd');
  });
});
