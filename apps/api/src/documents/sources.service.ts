import { readdir, readFile } from 'node:fs/promises';
import { basename, join, sep } from 'node:path';
import {
  Inject,
  Injectable,
  Logger,
  type OnApplicationBootstrap,
  type OnModuleDestroy,
} from '@nestjs/common';
import { isNotNull } from 'drizzle-orm';
import { load } from 'js-yaml';
import { z } from 'zod';
import type { Domain } from '../ai-client/ai-client.service.js';
import { DOMAINS, DomainSchema } from '../catalog/taxonomy.js';
import { CONFIG, type Config } from '../config.js';
import { DB, type Db } from '../db/db.module.js';
import { type Document, documents } from '../db/schema.js';
import { DocumentsService, type Upload } from './documents.service.js';

export const SyncResult = z
  .object({
    added: z.array(z.string()),
    updated: z.array(z.string()),
    deleted: z.array(z.string()),
    unchanged: z.int(),
    skipped: z.array(z.object({ source: z.string(), reason: z.string() })),
  })
  .meta({ id: 'SourcesSync' });
export type SyncResult = z.infer<typeof SyncResult>;

const NOTES = { sub: 'notes', name: 'Notes folder' };
// shortcut: notes without frontmatter domains or a domain-named top folder; becomes the catch-all
// domain if the M3c.1 kickoff adds one.
const DEFAULT_DOMAINS: Domain[] = ['dev'];
// A page whose markup changes on every fetch is re-ingested (and re-contextualized) at most daily.
const URL_REFRESH_MS = 24 * 60 * 60 * 1000;
const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;
const Frontmatter = z.object({
  domains: z
    .array(DomainSchema)
    .min(1)
    .or(DomainSchema.transform((domain) => [domain]))
    .optional(),
  topics: z
    .array(z.string())
    .or(z.string().transform((topic) => [topic]))
    .optional(),
});
// The sync runs unattended and sends whole notes to the LLM and the traces: a note with one of these
// stays out (M3c.1).
const SECRETS: Record<string, RegExp> = {
  'a private key': /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  'an AWS access key': /\bAKIA[0-9A-Z]{16}\b/,
  'a GitHub token': /\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_\w{22,})/,
  'an API key (sk-…)': /\bsk-[\w-]{20,}/,
  'a Slack token': /\bxox[abprs]-[\w-]{10,}/,
  'a Google API key': /\bAIza[\w-]{35}/,
  'a JWT': /\beyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,}/,
};

/** Keeps the documents of `NOTES_DIR` and of fetched URLs in step with their sources (M3c.1). */
@Injectable()
export class SourcesService implements OnApplicationBootstrap, OnModuleDestroy {
  private readonly logger = new Logger(SourcesService.name);
  private running?: Promise<SyncResult>;
  private timer?: NodeJS.Timeout;

  constructor(
    @Inject(DB) private readonly db: Db,
    @Inject(CONFIG) private readonly config: Config,
    private readonly documents: DocumentsService,
  ) {}

  onApplicationBootstrap(): void {
    void this.tick();
    const minutes = this.config.SOURCES_SYNC_MINUTES;
    if (minutes) this.timer = setInterval(() => void this.tick(), minutes * 60_000).unref();
  }

  onModuleDestroy(): void {
    clearInterval(this.timer);
  }

  /** One sync at a time: a call during a running one gets that one's result. */
  sync(requestId = 'sources-sync'): Promise<SyncResult> {
    this.running ??= this.run(requestId).finally(() => (this.running = undefined));
    return this.running;
  }

  private async tick(): Promise<void> {
    try {
      const { added, updated, deleted, skipped } = await this.sync();
      if (added.length || updated.length || deleted.length || skipped.length) {
        const counts = `${added.length} added, ${updated.length} updated, ${deleted.length} deleted`;
        this.logger.log(`Sources: ${counts}, ${skipped.length} skipped`);
      }
    } catch (error) {
      this.logger.warn(`Sources sync failed: ${String(error)}`);
    }
  }

  private async run(requestId: string): Promise<SyncResult> {
    const result: SyncResult = { added: [], updated: [], deleted: [], unchanged: 0, skipped: [] };
    const rows = await this.db.select().from(documents).where(isNotNull(documents.source));
    const known = new Set(rows.map((doc) => doc.source));
    const put = async (
      source: string,
      owner: { sub: string; name: string },
      read: () => Promise<{ file: Upload; domains: Domain[]; topics: string[] }>,
    ) => {
      try {
        const { file, domains, topics } = await read();
        const { changed } = await this.documents.fromSource(
          owner,
          source,
          file,
          domains,
          topics,
          requestId,
        );
        if (!changed) result.unchanged++;
        else (known.has(source) ? result.updated : result.added).push(source);
      } catch (error) {
        result.skipped.push({ source, reason: reason(error) });
      }
    };

    const dir = this.config.NOTES_DIR;
    const skip = (error: unknown) =>
      result.skipped.push({ source: 'notes:', reason: reason(error) });
    const paths = dir ? await notes(dir).catch((error: unknown) => void skip(error)) : undefined;
    if (paths) {
      for (const path of paths) await put(`notes:${path}`, NOTES, () => note(dir, path));
      const seen = new Set(paths.map((path) => `notes:${path}`));
      const gone = rows.filter((doc) => doc.source!.startsWith('notes:') && !seen.has(doc.source!));
      if (!paths.length && gone.length) {
        // An unmounted or emptied folder must not wipe the knowledge base.
        skip(`${dir} has no notes; its ${gone.length} indexed ones stay`);
      } else {
        for (const doc of gone) await this.remove(doc, requestId, result);
      }
    }

    const due = Date.now() - URL_REFRESH_MS;
    for (const doc of rows.filter((row) => !row.source!.startsWith('notes:'))) {
      if (doc.updatedAt.getTime() > due) continue;
      await put(doc.source!, { sub: doc.ownerId, name: doc.ownerName }, async () => ({
        file: await this.documents.fetch(doc.source!),
        domains: doc.domains as Domain[],
        topics: doc.topics,
      }));
    }
    return result;
  }

  private async remove(doc: Document, requestId: string, result: SyncResult): Promise<void> {
    try {
      await this.documents.remove({ ...NOTES, roles: [] }, doc.id, requestId);
      result.deleted.push(doc.source!);
    } catch (error) {
      result.skipped.push({ source: doc.source!, reason: reason(error) });
    }
  }
}

const reason = (error: unknown) => (error instanceof Error ? error.message : String(error));

/** `*.md` below `dir` as POSIX paths, without hidden files and folders (`.obsidian`, `.git`). */
async function notes(dir: string): Promise<string[]> {
  const paths = await readdir(dir, { recursive: true });
  return paths
    .map((path) => path.split(sep))
    .filter((parts) => parts.at(-1)!.endsWith('.md') && !parts.some((p) => p.startsWith('.')))
    .map((parts) => parts.join('/'))
    .sort();
}

/** Domains from the frontmatter, else a top folder named after a domain, else the default. */
async function note(dir: string, path: string) {
  const buffer = await readFile(join(dir, path));
  const text = buffer.toString('utf8');
  const secret = Object.keys(SECRETS).find((kind) => SECRETS[kind].test(text));
  if (secret) throw new Error(`Looks like it holds ${secret}; not sent to the knowledge base`);
  const meta = FRONTMATTER.exec(text)?.[1];
  const front = Frontmatter.safeParse((meta && load(meta)) ?? {});
  if (!front.success) throw new Error(`Frontmatter: ${z.prettifyError(front.error)}`);
  const top = path.includes('/') ? path.split('/')[0] : undefined;
  const folder = DOMAINS.find((domain) => domain === top);
  return {
    file: { originalname: basename(path), buffer, size: buffer.length },
    domains: front.data.domains ?? (folder ? [folder] : DEFAULT_DOMAINS),
    topics: front.data.topics ?? [],
  };
}
