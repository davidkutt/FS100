import { sql } from 'drizzle-orm';
import { char, check, integer, pgTable, text, timestamp, uuid } from 'drizzle-orm/pg-core';

export const DOCUMENT_STATUSES = ['pending', 'processing', 'ready', 'failed'] as const;

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
    status: text({ enum: DOCUMENT_STATUSES }).notNull(),
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
    check('documents_status_check', sql`${t.status} in ('pending','processing','ready','failed')`),
  ],
);

export type Document = typeof documents.$inferSelect;
