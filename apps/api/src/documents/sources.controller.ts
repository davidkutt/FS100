import { Controller, HttpCode, Post, Req } from '@nestjs/common';
import { ApiOkResponse } from '@nestjs/swagger';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { SourcesService, SyncResult } from './sources.service.js';

@Controller('admin/sources')
@Roles('admin')
export class SourcesController {
  constructor(private readonly sources: SourcesService) {}

  /** Notes and URLs now instead of at the next interval (M3c.1). */
  @Post('sync')
  @HttpCode(200)
  @ApiOkResponse({ standardSchema: SyncResult })
  sync(@Req() req: AuthRequest): Promise<SyncResult> {
    return this.sources.sync(req.id as string);
  }
}
