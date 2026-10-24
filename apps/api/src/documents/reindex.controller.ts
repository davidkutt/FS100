import { Body, Controller, Get, HttpCode, Post, Req } from '@nestjs/common';
import { ApiAcceptedResponse } from '@nestjs/swagger';
import { z } from 'zod';
import type { Alias, ReindexStatus } from '../ai-client/ai-client.service.js';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { DocumentsService } from './documents.service.js';

const ReindexBody = z
  .object({ reason: z.string().max(500).default(''), force: z.boolean().default(false) })
  .refine((body) => !body.force || body.reason.trim(), 'Forcing a swap needs a `reason` (D55)')
  .meta({ id: 'ReindexBody' });

/** Relays to the AI service's re-index (D55); the body of `GET` is its `ReindexStatus`. */
@Controller('admin/reindex')
@Roles('admin')
export class ReindexController {
  constructor(private readonly documents: DocumentsService) {}

  @Get()
  status(@Req() req: AuthRequest): Promise<ReindexStatus> {
    return this.documents.reindexStatus(req.accessToken, req.id as string);
  }

  /** 202: build, gate and swap run as a job; poll `GET` for its report. */
  @Post()
  @HttpCode(202)
  @ApiAcceptedResponse({ standardSchema: z.object({ jobId: z.int() }) })
  start(
    @Req() req: AuthRequest,
    @Body({ schema: ReindexBody }) body: z.infer<typeof ReindexBody>,
  ): Promise<{ jobId: number }> {
    return this.documents.reindex(req.user, body, req.accessToken, req.id as string);
  }

  @Post('rollback')
  @HttpCode(200)
  rollback(@Req() req: AuthRequest): Promise<Alias> {
    return this.documents.rollback(req.user, req.accessToken, req.id as string);
  }
}
