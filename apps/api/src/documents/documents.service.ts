import { isUtf8 } from 'node:buffer';
import { createHash } from 'node:crypto';
import { extname } from 'node:path';
import {
  BadRequestException,
  ConflictException,
  ForbiddenException,
  Inject,
  Injectable,
  Logger,
  NotFoundException,
  type OnModuleInit,
  UnsupportedMediaTypeException,
} from '@nestjs/common';
import { and, desc, eq, inArray, isNotNull } from 'drizzle-orm';
import {
  AiClient,
  type Domain,
  type JobStatus,
  type ReindexRequest,
  type ReindexStatus,
  type Alias,
} from '../ai-client/ai-client.service.js';
import type { AuthUser } from '../auth/auth.guard.js';
import { TAXONOMY, type Taxonomy, unknownTopics } from '../catalog/taxonomy.js';
import { DB, type Db } from '../db/db.module.js';
import { CONFIG, type Config } from '../config.js';
import { auditLog, type Document, type DocumentStatus, documents } from '../db/schema.js';
import type { LabelsBody } from './documents.controller.js';
import { fetchDocument } from './fetch-url.js';

export interface Upload {
  originalname: string;
  buffer: Buffer;
  size: number;
}

const IN_WORK = ['queued', 'parsing', 'contextualizing', 'embedding'] satisfies DocumentStatus[];

// The AI service picks its parser by file extension, so the extension decides the type.
const MIME_BY_EXTENSION: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.md': 'text/markdown',
  '.markdown': 'text/markdown',
  '.txt': 'text/plain',
  '.html': 'text/html',
};

@Injectable()
export class DocumentsService implements OnModuleInit {
  private readonly logger = new Logger(DocumentsService.name);

  constructor(
    @Inject(DB) private readonly db: Db,
    private readonly ai: AiClient,
    @Inject(TAXONOMY) private readonly taxonomy: Taxonomy,
    @Inject(CONFIG) private readonly config: Config,
  ) {}

  /**
   * An upload not yet handed to the AI service dies with the process; queued jobs resume (D53).
   * Before any bootstrap hook, so the boot sync's new uploads are not caught.
   */
  async onModuleInit(): Promise<void> {
    // shortcut: assumes one API instance; a second one would fail the other's uploads in flight.
    const stuck = await this.db
      .update(documents)
      .set({ status: 'failed', error: 'Interrupted by an API restart; delete and upload again' })
      .where(eq(documents.status, 'pending'))
      .returning({ id: documents.id });
    if (stuck.length > 0) this.logger.warn(`Marked ${stuck.length} interrupted upload(s) failed`);
  }

  async list(requestId: string): Promise<Document[]> {
    await this.syncJobs(requestId);
    return this.db.select().from(documents).orderBy(desc(documents.createdAt));
  }

  async upload(
    user: AuthUser,
    file: Upload | undefined,
    domains: Domain[],
    topics: string[],
    requestId: string,
    source?: string,
  ): Promise<{ id: string }> {
    if (!file?.size) throw new BadRequestException('A non-empty `file` is required');
    const { mime, sha256 } = this.checked(file, topics);

    const [doc] = await this.db
      .insert(documents)
      .values({
        ownerId: user.sub,
        ownerName: user.name,
        filename: file.originalname,
        mime,
        sizeBytes: file.size,
        sha256,
        domains,
        topics,
        source,
        status: 'pending',
      })
      .onConflictDoNothing({ target: documents.sha256 })
      .returning();
    if (!doc) {
      const [existing] = await this.db
        .select({ filename: documents.filename, status: documents.status })
        .from(documents)
        .where(eq(documents.sha256, sha256));
      throw new ConflictException(
        existing
          ? `Already uploaded as "${existing.filename}" (${existing.status}); delete that one first`
          : 'Already uploaded',
      );
    }
    void this.ingest(doc, file.buffer, requestId);
    return { id: doc.id };
  }

  /** `kb.ingest_url`: a service account adds a document for a user (trusted subsystem, D36). */
  async fromUrl(
    service: AuthUser,
    owner: { sub: string; name: string },
    url: string,
    domains: Domain[],
    requestId: string,
  ): Promise<{ id: string; status: 'pending' | 'unchanged' }> {
    const source = new URL(url).href;
    const { id, changed } = await this.fromSource(
      owner,
      source,
      await this.fetch(source),
      domains,
      [],
      requestId,
    );
    await this.db.insert(auditLog).values({
      actorId: owner.sub,
      actorRoles: [],
      serviceIdentity: service.name,
      tool: 'documents.from_url',
      kind: 'write',
      argsRedacted: { docId: id, url, domains },
      outcome: 'ok',
    });
    return { id, status: changed ? 'pending' : 'unchanged' };
  }

  /** Through the SSRF guard and host allow-list (D36). */
  fetch(url: string): Promise<Upload> {
    const maxBytes = this.config.UPLOAD_MAX_MB * 1024 * 1024;
    return fetchDocument(new URL(url), this.config.INGEST_URL_ALLOWED_HOSTS, maxBytes);
  }

  /**
   * The document of a note or URL (M3c.1): added, or a new version of the same id once its content
   * changed; the same content changes nothing. Its labels follow the source.
   */
  async fromSource(
    owner: { sub: string; name: string },
    source: string,
    file: Upload,
    domains: Domain[],
    topics: string[],
    requestId: string,
  ): Promise<{ id: string; changed: boolean }> {
    const user = { ...owner, roles: [] };
    const [doc] = await this.db.select().from(documents).where(eq(documents.source, source));
    if (!doc) {
      const { id } = await this.upload(user, file, domains, topics, requestId, source);
      return { id, changed: true };
    }
    const { mime, sha256 } = this.checked(file, topics);
    if (doc.sha256 === sha256) return { id: doc.id, changed: false };
    await this.settled(user, doc.id, 'change', requestId);
    const [same] = await this.db.select().from(documents).where(eq(documents.sha256, sha256));
    if (same) throw new ConflictException(`Same content as "${same.filename}"`);
    const [changed] = await this.db
      .update(documents)
      .set({
        filename: file.originalname,
        mime,
        sizeBytes: file.size,
        sha256,
        domains,
        topics,
        status: 'pending',
        error: null,
        chunkCount: null,
        pageCount: null,
      })
      .where(eq(documents.id, doc.id))
      .returning();
    void this.ingest(changed, file.buffer, requestId);
    return { id: doc.id, changed: true };
  }

  async relabel(
    user: AuthUser,
    id: string,
    labels: LabelsBody,
    requestId: string,
  ): Promise<Document> {
    this.checkTopics([...(labels.topics ?? []), ...(labels.priorityTopics ?? [])]);
    await this.settled(user, id, 'change', requestId);
    // Vectors first, like delete: if that fails, the row keeps the labels Qdrant still has.
    const { priorityTopics, ...rest } = labels;
    await this.ai.updateLabels(id, { ...rest, priority_topics: priorityTopics }, requestId);
    return this.db.transaction(async (tx) => {
      const [doc] = await tx.update(documents).set(labels).where(eq(documents.id, id)).returning();
      await tx.insert(auditLog).values({
        actorId: user.sub,
        actorRoles: user.roles,
        tool: 'documents.relabel',
        kind: 'write',
        argsRedacted: { docId: id, ...labels },
        outcome: 'ok',
      });
      return doc;
    });
  }

  async remove(user: AuthUser, id: string, requestId: string): Promise<void> {
    await this.settled(user, id, 'delete', requestId);
    // Vectors and original first (a queued job is cancelled): if that fails, the row stays.
    await this.ai.deleteDocument(id, requestId);
    await this.db.delete(documents).where(eq(documents.id, id));
  }

  /** Re-index from the stored originals behind the eval gate (D55); audited like a write. */
  async reindex(
    user: AuthUser,
    body: ReindexRequest,
    token: string,
    requestId: string,
  ): Promise<{ jobId: number }> {
    const jobId = await this.ai.reindex(body, requestId, token);
    await this.audit(user, 'kb.reindex', { jobId, ...body });
    return { jobId };
  }

  reindexStatus(token: string, requestId: string): Promise<ReindexStatus> {
    return this.ai.reindexStatus(requestId, token);
  }

  async rollback(user: AuthUser, token: string, requestId: string): Promise<Alias> {
    const alias = await this.ai.rollback(requestId, token);
    await this.audit(user, 'kb.rollback', alias);
    return alias;
  }

  /** The caller's own (or, for admins, any) document whose ingest is not running. */
  private async settled(
    user: AuthUser,
    id: string,
    action: 'change' | 'delete',
    requestId: string,
  ): Promise<void> {
    await this.syncJobs(requestId, id);
    const [doc] = await this.db.select().from(documents).where(eq(documents.id, id));
    if (!doc) throw new NotFoundException(`Document ${id} not found`);
    if (doc.ownerId !== user.sub && !user.roles.includes('admin')) {
      throw new ForbiddenException(`Editors can only ${action} their own documents`);
    }
    // An ingest upserts its vectors (and the labels it was given) when it runs; a queued one can
    // still be cancelled.
    const busy: DocumentStatus[] =
      action === 'delete'
        ? ['pending', 'parsing', 'contextualizing', 'embedding']
        : ['pending', ...IN_WORK];
    if (busy.includes(doc.status)) {
      throw new ConflictException(
        'The document is still being ingested; try again when it is done',
      );
    }
  }

  /** Copies the AI service's job states into the rows still in work (D52). */
  // shortcut: syncs when documents are read; add a poller if rows must change unread.
  private async syncJobs(requestId: string, id?: string): Promise<void> {
    const working = await this.db
      .select()
      .from(documents)
      .where(
        and(
          inArray(documents.status, IN_WORK),
          isNotNull(documents.jobId),
          id ? eq(documents.id, id) : undefined,
        ),
      );
    await Promise.all(
      working.map(async (doc) => {
        const job = await this.ai.job(doc.jobId!, requestId).catch((error: unknown) => {
          this.logger.warn(`Job ${doc.jobId} of ${doc.id}: ${String(error)}`);
        });
        const update = job && fromJob(job);
        if (update && update.status !== doc.status) {
          await this.db.update(documents).set(update).where(eq(documents.id, doc.id));
        }
      }),
    );
  }

  private async audit(user: AuthUser, tool: string, args: Record<string, unknown>): Promise<void> {
    await this.db.insert(auditLog).values({
      actorId: user.sub,
      actorRoles: user.roles,
      tool,
      kind: 'write',
      argsRedacted: args,
      outcome: 'ok',
    });
  }

  private checked(file: Upload, topics: string[]): { mime: string; sha256: string } {
    this.checkTopics(topics);
    const mime = MIME_BY_EXTENSION[extname(file.originalname).toLowerCase()];
    if (!mime || !hasExpectedContent(mime, file.buffer)) {
      throw new UnsupportedMediaTypeException(
        'Only PDF, Markdown, HTML and plain-text files are accepted',
      );
    }
    return { mime, sha256: createHash('sha256').update(file.buffer).digest('hex') };
  }

  private checkTopics(topics: string[]): void {
    const unknown = unknownTopics(this.taxonomy, topics);
    if (unknown.length) throw new BadRequestException(`Unknown topics: ${unknown.join(', ')}`);
  }

  /** Hands the file to the AI service, which stores it and queues the ingest (D52). */
  private async ingest(doc: Document, data: Buffer, requestId: string): Promise<void> {
    try {
      const form = new FormData();
      form.set('file', new Blob([new Uint8Array(data)], { type: doc.mime }), doc.filename);
      form.set('doc_id', doc.id);
      form.set('owner_id', doc.ownerId);
      for (const domain of doc.domains) form.append('domains', domain);
      for (const topic of doc.topics) form.append('topics', topic);
      const { job_id, version } = await this.ai.submit(form, requestId);
      await this.db
        .update(documents)
        .set({ status: 'queued', jobId: String(job_id), version })
        .where(eq(documents.id, doc.id));
    } catch (error) {
      this.logger.warn(`Ingest of ${doc.id} failed: ${String(error)}`);
      await this.db
        .update(documents)
        .set({ status: 'failed', error: error instanceof Error ? error.message : String(error) })
        .where(eq(documents.id, doc.id))
        // DB down too: the row stays non-terminal until the next boot recovery.
        .catch((dbError: unknown) =>
          this.logger.error(`Marking ${doc.id} failed: ${String(dbError)}`),
        );
    }
  }
}

function fromJob(job: JobStatus): Partial<Document> | undefined {
  const result = job.result && 'chunk_count' in job.result ? job.result : undefined;
  switch (job.state) {
    case 'queued':
    case 'parsing':
    case 'contextualizing':
    case 'embedding':
      return { status: job.state };
    case 'ready':
      return {
        status: 'ready',
        chunkCount: result?.chunk_count ?? null,
        pageCount: result?.page_count ?? null,
        embeddingModel: result?.embedding_model ?? null,
      };
    case 'failed':
    case 'cancelled':
      return { status: 'failed', error: job.error ?? `Ingest ${job.state}` };
    default:
      return undefined;
  }
}

/** Magic bytes for PDF; text must be UTF-8 without NUL bytes, so renamed binaries are rejected. */
function hasExpectedContent(mime: string, data: Buffer): boolean {
  if (mime === 'application/pdf') return data.toString('latin1', 0, 5) === '%PDF-';
  return !data.includes(0) && isUtf8(data);
}
