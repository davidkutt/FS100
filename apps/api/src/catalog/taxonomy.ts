import { readFileSync } from 'node:fs';
import { load } from 'js-yaml';
import { z } from 'zod';
import type { Domain } from '../ai-client/ai-client.service.js';

export const DOMAINS = [
  'db',
  'dev',
  'cloud',
  'devops',
  'mlops',
  'ai',
  'security',
  'architecture',
  'sre',
] as const satisfies readonly Domain[];
export const DomainSchema = z.enum(DOMAINS);

/** `config/taxonomy.yaml` (D48); an enum-keyed record requires every domain. */
export const Taxonomy = z
  .object({
    version: z.int(),
    domains: z.record(
      DomainSchema,
      z.object({
        description: z.string(),
        topics: z.record(z.string(), z.string()).default({}),
      }),
    ),
  })
  .meta({ id: 'Taxonomy' });
export type Taxonomy = z.infer<typeof Taxonomy>;

export const TAXONOMY = Symbol('TAXONOMY');

export const loadTaxonomy = (path: string): Taxonomy =>
  Taxonomy.parse(load(readFileSync(path, 'utf8')));

export function unknownTopics(taxonomy: Taxonomy, topics: string[]): string[] {
  const known = new Set(
    Object.entries(taxonomy.domains).flatMap(([domain, { topics }]) =>
      Object.keys(topics).map((topic) => `${domain}/${topic}`),
    ),
  );
  return topics.filter((topic) => !known.has(topic));
}
