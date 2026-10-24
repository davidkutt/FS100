import { sql } from 'drizzle-orm';
import {
  bigserial,
  char,
  check,
  index,
  integer,
  jsonb,
  numeric,
  pgTable,
  primaryKey,
  real,
  text,
  timestamp,
  uuid,
} from 'drizzle-orm/pg-core';

/** `pending` until the AI service accepted the upload; then its job's states (plan-phase-3 §7.1). */
export const DOCUMENT_STATUSES = [
  'pending',
  'queued',
  'parsing',
  'embedding',
  'ready',
  'failed',
] as const;
export type DocumentStatus = (typeof DOCUMENT_STATUSES)[number];

/** plan.md §7.4. After a change: `pnpm --filter @fs100/api db:generate`; the API migrates on boot. */
export const documents = pgTable(
  'documents',
  {
    id: uuid().primaryKey().defaultRandom(),
    ownerId: text().notNull(),
    ownerName: text().notNull(),
    filename: text().notNull(),
    mime: text().notNull(),
    sizeBytes: integer().notNull(),
    sha256: char({ length: 64 }).notNull().unique(),
    domains: text()
      .array()
      .notNull()
      .default(sql`'{}'`),
    topics: text()
      .array()
      .notNull()
      .default(sql`'{}'`),
    status: text({ enum: DOCUMENT_STATUSES }).notNull(),
    version: integer().notNull().default(1),
    jobId: text(), // the AI service's ingest job
    error: text(),
    chunkCount: integer(),
    pageCount: integer(),
    embeddingModel: text(),
    createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp({ withTimezone: true })
      .notNull()
      .defaultNow()
      .$onUpdate(() => new Date()),
  },
  (t) => [
    check(
      'documents_status_check',
      sql`${t.status} in ('pending','queued','parsing','embedding','ready','failed')`,
    ),
  ],
);

export type Document = typeof documents.$inferSelect;

export const ANSWER_STATUSES = ['answered', 'abstained', 'no_kb'] as const;

/** plan-phase-2.md §7.4. */
export const conversations = pgTable(
  'conversations',
  {
    id: uuid().primaryKey().defaultRandom(),
    ownerId: text().notNull(),
    title: text(),
    modelId: text(),
    createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp({ withTimezone: true })
      .notNull()
      .defaultNow()
      .$onUpdate(() => new Date()),
  },
  (t) => [index().on(t.ownerId, t.updatedAt)],
);

export const messages = pgTable(
  'messages',
  {
    id: uuid().primaryKey().defaultRandom(),
    conversationId: uuid()
      .notNull()
      .references(() => conversations.id, { onDelete: 'cascade' }),
    role: text({ enum: ['user', 'assistant'] }).notNull(),
    parts: jsonb().notNull(),
    model: text(),
    promptVersion: text(),
    promptHash: text(),
    stopReason: text(),
    traceId: text(),
    answerStatus: text({ enum: ANSWER_STATUSES }),
    topScore: real(),
    createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    index().on(t.conversationId, t.createdAt),
    check('messages_role_check', sql`${t.role} in ('user','assistant')`),
    check(
      'messages_answer_status_check',
      sql`${t.answerStatus} in ('answered','abstained','no_kb')`,
    ),
  ],
);

export const usage = pgTable(
  'usage',
  {
    id: uuid().primaryKey().defaultRandom(),
    userId: text().notNull(),
    // No foreign keys: usage outlives a deleted conversation (cost accounting, D44).
    conversationId: uuid(),
    messageId: uuid(),
    model: text().notNull(),
    inputTokens: integer().notNull(),
    cachedTokens: integer().notNull().default(0),
    outputTokens: integer().notNull(),
    costUsd: numeric({ precision: 10, scale: 6, mode: 'number' }),
    createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index().on(t.userId, t.createdAt)],
);

export const feedback = pgTable(
  'feedback',
  {
    messageId: uuid()
      .notNull()
      .references(() => messages.id, { onDelete: 'cascade' }),
    userId: text().notNull(),
    rating: text({ enum: ['up', 'down'] }).notNull(),
    comment: text(),
    createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    primaryKey({ columns: [t.messageId, t.userId] }),
    check('feedback_rating_check', sql`${t.rating} in ('up','down')`),
  ],
);

export const APPROVAL_STATUSES = [
  'pending',
  'approved',
  'rejected',
  'expired',
  'executing',
  'succeeded',
  'failed',
  'unknown',
] as const;
export type ApprovalStatus = (typeof APPROVAL_STATUSES)[number];

/** State machine of ADR-0008; `id` is the AI service's `approvalId`, which the signed action names. */
export const approvals = pgTable(
  'approvals',
  {
    id: uuid().primaryKey(),
    conversationId: uuid()
      .notNull()
      .references(() => conversations.id, { onDelete: 'cascade' }),
    messageId: uuid()
      .notNull()
      .references(() => messages.id, { onDelete: 'cascade' }),
    requesterId: text().notNull(),
    callId: text().notNull(),
    tool: text().notNull(),
    args: jsonb().$type<Record<string, unknown>>().notNull(),
    risk: text().notNull(),
    signedAction: text().notNull(),
    status: text({ enum: APPROVAL_STATUSES }).notNull().default('pending'),
    note: text(),
    error: text(),
    createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
    expiresAt: timestamp({ withTimezone: true }).notNull(),
    decidedAt: timestamp({ withTimezone: true }),
    executedAt: timestamp({ withTimezone: true }),
  },
  (t) => [
    index().on(t.requesterId, t.status),
    index().on(t.conversationId),
    check(
      'approvals_status_check',
      sql`${t.status} in ('pending','approved','rejected','expired','executing','succeeded','failed','unknown')`,
    ),
  ],
);

/** Append-only (a trigger in the migration rejects UPDATE and DELETE); outlives conversations (D42). */
export const auditLog = pgTable(
  'audit_log',
  {
    id: bigserial({ mode: 'number' }).primaryKey(),
    ts: timestamp({ withTimezone: true }).notNull().defaultNow(),
    actorId: text().notNull(),
    actorRoles: text().array().notNull(),
    serviceIdentity: text(), // the credential's variable, e.g. GITHUB_PAT_READ; null = the user's token
    conversationId: uuid(),
    approvalId: uuid(),
    tool: text().notNull(),
    kind: text().notNull(),
    argsRedacted: jsonb(),
    outcome: text().notNull(),
    traceId: text(),
  },
  (t) => [index().on(t.ts), index().on(t.actorId, t.ts)],
);

export type Conversation = typeof conversations.$inferSelect;
export type Message = typeof messages.$inferSelect;
export type Approval = typeof approvals.$inferSelect;
export type AuditEntry = typeof auditLog.$inferSelect;
