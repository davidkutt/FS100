import { Controller, Get, Inject, Logger, Req, ServiceUnavailableException } from '@nestjs/common';
import { ApiOkResponse } from '@nestjs/swagger';
import { sql } from 'drizzle-orm';
import type { Request } from 'express';
import { z } from 'zod';
import { AiClient, type ServiceStatus } from '../ai-client/ai-client.service.js';
import { Public, Roles } from '../auth/auth.guard.js';
import { DB, type Db } from '../db/db.module.js';

const HealthStatus = z.object({ status: z.literal('ok') });
type HealthStatus = z.infer<typeof HealthStatus>;

const StatusReport = z
  .object({
    api: z.literal('ok'),
    db: z.enum(['ok', 'down']),
    aiService: z.enum(['ok', 'down']),
    qdrant: z.enum(['ok', 'down', 'unknown']), // unknown = AI service down, which reports Qdrant
  })
  .meta({ id: 'StatusReport' });
type StatusReport = z.infer<typeof StatusReport>;

@Controller()
export class HealthController {
  private readonly logger = new Logger(HealthController.name);

  constructor(
    private readonly ai: AiClient,
    @Inject(DB) private readonly db: Db,
  ) {}

  /** Liveness probe. */
  @Public()
  @Get('healthz')
  @ApiOkResponse({ standardSchema: HealthStatus })
  healthz(): HealthStatus {
    return { status: 'ok' };
  }

  /** Readiness: Postgres only; without the AI service, documents still list and chat fails fast. */
  @Public()
  @Get('readyz')
  @ApiOkResponse({ standardSchema: HealthStatus })
  async readyz(): Promise<HealthStatus> {
    if ((await this.dbStatus()) === 'down') throw new ServiceUnavailableException('Postgres down');
    return { status: 'ok' };
  }

  /** Admin status card. */
  @Roles('admin')
  @Get('status')
  @ApiOkResponse({ standardSchema: StatusReport })
  async status(@Req() req: Request): Promise<StatusReport> {
    const [db, ai] = await Promise.all([
      this.dbStatus(),
      this.ai.get<ServiceStatus>('/v1/status', req.id as string).catch((error: unknown) => {
        this.logger.warn(`AI service status failed: ${String(error)}`);
        return undefined;
      }),
    ]);
    return { api: 'ok', db, aiService: ai ? 'ok' : 'down', qdrant: ai?.qdrant ?? 'unknown' };
  }

  private dbStatus(): Promise<'ok' | 'down'> {
    return this.db.execute(sql`select 1`).then(
      () => 'ok' as const,
      (error: unknown) => {
        this.logger.warn(`Postgres check failed: ${String(error)}`);
        return 'down' as const;
      },
    );
  }
}
