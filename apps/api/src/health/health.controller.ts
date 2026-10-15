import { Controller, Get, Logger, Req } from '@nestjs/common';
import type { Request } from 'express';
import { AiClient } from '../ai-client/ai-client.service.js';
import { Public, Roles } from '../auth/auth.guard.js';

export interface HealthStatus {
  status: 'ok';
}

export interface StatusReport {
  api: 'ok';
  aiService: 'ok' | 'down';
}

@Controller()
export class HealthController {
  private readonly logger = new Logger(HealthController.name);

  constructor(private readonly ai: AiClient) {}

  /** Liveness probe. `/readyz` (Postgres + AI service reachable) follows with M1.4. */
  @Public()
  @Get('healthz')
  healthz(): HealthStatus {
    return { status: 'ok' };
  }

  /** Admin status card; Qdrant and Postgres join in M1.4. */
  @Roles('admin')
  @Get('status')
  async status(@Req() req: Request): Promise<StatusReport> {
    const aiService = await this.ai.get<HealthStatus>('/v1/status', req.id as string).then(
      () => 'ok' as const,
      (error: unknown) => {
        this.logger.warn(`AI service status failed: ${String(error)}`);
        return 'down' as const;
      },
    );
    return { api: 'ok', aiService };
  }
}
