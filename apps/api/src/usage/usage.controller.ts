import { Controller, Get, Query, Req } from '@nestjs/common';
import { ApiOkResponse } from '@nestjs/swagger';
import { z } from 'zod';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { UsageService } from './usage.service.js';

const UsageFilter = z.object({
  user: z.string().optional(),
  from: z.iso.date().optional(), // UTC days, both inclusive
  to: z.iso.date().optional(),
});

export const UsageDay = z
  .object({
    day: z.iso.date(), // UTC
    inputTokens: z.int(),
    cachedTokens: z.int(),
    outputTokens: z.int(),
    costUsd: z.number(),
    turns: z.int(),
  })
  .meta({ id: 'UsageDay' });

export const MyUsage = z
  .object({ capUsd: z.number(), today: UsageDay, days: z.array(UsageDay) })
  .meta({ id: 'MyUsage' });

export const UserUsageDay = UsageDay.extend({ userId: z.string() }).meta({ id: 'UserUsageDay' });

@Controller()
export class UsageController {
  constructor(private readonly usage: UsageService) {}

  /** Today against the daily cap (D44), and the last 30 days. */
  @Get('me/usage')
  @ApiOkResponse({ standardSchema: MyUsage })
  mine(@Req() req: AuthRequest): Promise<z.infer<typeof MyUsage>> {
    return this.usage.mine(req.user);
  }

  @Get('admin/usage')
  @Roles('admin')
  @ApiOkResponse({ standardSchema: z.array(UserUsageDay) })
  perUser(
    @Query({ schema: UsageFilter }) filter: z.infer<typeof UsageFilter>,
  ): Promise<z.infer<typeof UserUsageDay>[]> {
    return this.usage.perUser(filter);
  }
}
