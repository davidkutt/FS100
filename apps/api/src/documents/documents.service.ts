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
  type OnApplicationBootstrap,
  UnsupportedMediaTypeException,
} from '@nestjs/common';
import { desc, eq, inArray } from 'drizzle-orm';
import { AiClient, type Domain } from '../ai-client/ai-client.service.js';
import type { AuthUser } from '../auth/auth.guard.js';
import { TAXONOMY, type Taxonomy, unknownTopics } from '../catalog/taxonomy.js';
import { DB, type Db } from '../db/db.module.js';
import { CONFIG, type Config } from '../config.js';
import { auditLog, type Document, documents } from '../db/schema.js';
import type { LabelsBody } from './documents.controller.js';
import { fetchDocument } from './fetch-url.js';

export interface Upload {
  originalname: string;
  buffer: Buffer;
  size: number;
}

// The AI service picks its parser by file extension, so the extension decides the type.
const MIME_BY_EXTENSION: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.md': 'text/markdown',
  '.markdown': 'text/markdown',
  '.txt': 'text/plain',
};

@Injectable()
export class DocumentsService implements OnApplicationBootstrap {
  private readonly logger = new Logger(DocumentsService.name);

  constructor(
    @Inject(DB) private readonly db: Db,
    private readonly ai: AiClient,
    @Inject(TAXONOMY) private readonly taxonomy: Taxonomy,
    @Inject(CONFIG) private readonly config: Config,
  ) {}

  /** Originals are not kept (D7), so an ingest cut off by a restart cannot resume. */
  async onApplicationBootstrap(): Promise<void> {
    // shortcut: assumes one API instance; needs a job queue with leases (P3) before scaling out.
    const stuck = await this.db
      .update(documents)
      .set({ status: 'failed', error: 'Interrupted by an API restart; delete and upload again' })
      .where(inArray(documents.status, ['pending', 'processing']))
      .returning({ id: documents.id });
    if (stuck.length > 0) this.logger.warn(`Marked ${stuck.length} interrupted upload(s) failed`);
  }

  list(): Promise<Document[]> {
    return this.db.select().from(documents).orderBy(desc(documents.createdAt));
  }

  async upload(
    user: AuthUser,
    file: Upload | undefined,
    domains: Domain[],
    topics: string[],
    requestId: string,
  ): Promise<{ id: string }> {
    if (!file?.size) throw new BadRequestException('A non-empty `file` is required');
    this.checkTopics(topics);
    const mime = MIME_BY_EXTENSION[extname(file.originalname).toLowerCase()];
    if (!mime || !hasExpectedContent(mime, file.buffer)) {
      throw new UnsupportedMediaTypeException(
        'Only PDF, Markdown and plain-text files are accepted',
      );
    }
    const sha256 = createHash('sha256').update(file.buffer).digest('hex');

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
  ): Promise<{ id: string; status: 'pending' }> {
    const maxBytes = this.config.UPLOAD_MAX_MB * 1024 * 1024;
    const file = await fetchDocument(new URL(url), this.config.INGEST_URL_ALLOWED_HOSTS, maxBytes);
    const { id } = await this.upload({ ...owner, roles: [] }, file, domains, [], requestId);
    await this.db.insert(auditLog).values({
      actorId: owner.sub,
      actorRoles: [],
      serviceIdentity: service.name,
      tool: 'documents.from_url',
      kind: 'write',
      argsRedacted: { docId: id, url, domains },
      outcome: 'ok',
    });
    return { id, status: 'pending' };
  }

  async relabel(
    user: AuthUser,
    id: string,
    labels: LabelsBody,
    requestId: string,
  ): Promise<Document> {
    this.checkTopics(labels.topics ?? []);
    await this.settled(user, id, 'change');
    // Vectors first, like delete: if that fails, the row keeps the labels Qdrant still has.
    await this.ai.updateLabels(id, labels, requestId);
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
    await this.settled(user, id, 'delete');
    // Vectors first: if that fails, the row stays and the delete can be retried.
    await this.ai.deleteDocument(id, requestId);
    await this.db.delete(documents).where(eq(documents.id, id));
  }

  /** The caller's own (or, for admins, any) document whose ingest has finished. */
  private async settled(user: AuthUser, id: string, action: string): Promise<void> {
    const [doc] = await this.db.select().from(documents).where(eq(documents.id, id));
    if (!doc) throw new NotFoundException(`Document ${id} not found`);
    if (doc.ownerId !== user.sub && !user.roles.includes('admin')) {
      throw new ForbiddenException(`Editors can only ${action} their own documents`);
    }
    // A running ingest would upsert its vectors (and old labels) afterwards.
    if (doc.status === 'pending' || doc.status === 'processing') {
      throw new ConflictException(
        'The document is still being ingested; try again when it is done',
      );
    }
  }

  private checkTopics(topics: string[]): void {
    const unknown = unknownTopics(this.taxonomy, topics);
    if (unknown.length) throw new BadRequestException(`Unknown topics: ${unknown.join(', ')}`);
  }

  private async ingest(doc: Document, data: Buffer, requestId: string): Promise<void> {
    try {
      await this.db.update(documents).set({ status: 'processing' }).where(eq(documents.id, doc.id));
      const form = new FormData();
      form.set('file', new Blob([new Uint8Array(data)], { type: doc.mime }), doc.filename);
      form.set('doc_id', doc.id);
      form.set('owner_id', doc.ownerId);
      for (const domain of doc.domains) form.append('domains', domain);
      for (const topic of doc.topics) form.append('topics', topic);
      const result = await this.ai.ingest(form, requestId);
      await this.db
        .update(documents)
        .set({
          status: 'ready',
          chunkCount: result.chunk_count,
          pageCount: result.page_count,
          embeddingModel: result.embedding_model,
        })
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

/** Magic bytes for PDF; text must be UTF-8 without NUL bytes, so renamed binaries are rejected. */
function hasExpectedContent(mime: string, data: Buffer): boolean {
  if (mime === 'application/pdf') return data.toString('latin1', 0, 5) === '%PDF-';
  return !data.includes(0) && isUtf8(data);
}
