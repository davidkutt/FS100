import { Taxonomy, loadTaxonomy, unknownTopics } from './taxonomy.js';

describe('taxonomy', () => {
  const taxonomy = loadTaxonomy('../../config/taxonomy.yaml');

  it('the committed file has every domain and only domain/topic ids', () => {
    expect(Object.keys(taxonomy.domains)).toHaveLength(9);
    expect(unknownTopics(taxonomy, ['devops/ci-cd', 'devops/', 'devops/ci-cd/x', 'sre/x'])).toEqual(
      ['devops/', 'devops/ci-cd/x', 'sre/x'],
    );
  });

  it.each([
    ['a missing domain', { version: 1, domains: { db: { description: 'Databases' } } }],
    [
      'an unknown domain',
      { ...taxonomy, domains: { ...taxonomy.domains, cooking: { description: 'x' } } },
    ],
  ])('rejects %s', (_case, file) => {
    expect(Taxonomy.safeParse(file).success).toBe(false);
  });
});
