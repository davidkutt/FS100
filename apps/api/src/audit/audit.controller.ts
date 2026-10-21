import { Controller, Get, Inject, Query } from '@nestjs/common';
import { ApiOkResponse } from '@nestjs/swagger';
import { and, desc, eq, gte, lt } from 'drizzle-orm';
import { z } from 'zod';
import { Roles } from '../auth/auth.guard.js';
import { DB, type Db } from '../db/db.module.js';
import { type AuditEntry, auditLog } from '../db/schema.js';

const DAY_MS = 86_400_000;
const LIMIT = 200; // shortcut: newest 200 only, page with a cursor once admins need older rows

const AuditFilter = z.object({
  user: z.string().optional(),
  tool: z.string().optional(),
  outcome: z.string().optional(),
  from: z.iso.date().optional(), // UTC days, both inclusive
  to: z.iso.date().optional(),
});

const timestamp = z.iso.datetime({ offset: true });

export const AuditEntryDto = z
  .object({
    id: z.int(),
    ts: timestamp,
    actorId: z.string(),
    actorRoles: z.array(z.string()),
    serviceIdentity: z.string().nullable(),
    conversationId: z.uuid().nullable(),
    approvalId: z.uuid().nullable(),
    tool: z.string(),
    kind: z.string(),
    argsRedacted: z.unknown(),
    outcome: z.string(),
    traceId: z.string().nullable(),
  })
  .meta({ id: 'AuditEntry' });

/** The append-only tool audit (D42), newest first. */
@Controller('admin/audit')
@Roles('admin')
export class AuditController {
  constructor(@Inject(DB) private readonly db: Db) {}

  @Get()
  @ApiOkResponse({ standardSchema: z.array(AuditEntryDto) })
  list(@Query({ schema: AuditFilter }) filter: z.infer<typeof AuditFilter>): Promise<AuditEntry[]> {
    return this.db
      .select()
      .from(auditLog)
      .where(
        and(
          filter.user ? eq(auditLog.actorId, filter.user) : undefined,
          filter.tool ? eq(auditLog.tool, filter.tool) : undefined,
          filter.outcome ? eq(auditLog.outcome, filter.outcome) : undefined,
          filter.from ? gte(auditLog.ts, new Date(filter.from)) : undefined,
          filter.to ? lt(auditLog.ts, new Date(Date.parse(filter.to) + DAY_MS)) : undefined,
        ),
      )
      .orderBy(desc(auditLog.ts), desc(auditLog.id))
      .limit(LIMIT);
  }
}
