import { Controller, Get } from '@nestjs/common';

export interface HealthStatus {
  status: 'ok';
}

@Controller()
export class HealthController {
  /** Liveness probe. `/readyz` (Postgres + AI service reachable) follows with M1.4. */
  @Get('healthz')
  healthz(): HealthStatus {
    return { status: 'ok' };
  }
}
