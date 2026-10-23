import { HttpException, HttpStatus, Inject, Injectable } from '@nestjs/common';
import { and, desc, eq, gte, lt, type SQL, sql } from 'drizzle-orm';
import type { AuthUser } from '../auth/auth.guard.js';
import { CONFIG, type Config } from '../config.js';
import { DB, type Db } from '../db/db.module.js';
import { usage } from '../db/schema.js';

const DAY_MS = 86_400_000;
const LIMIT = 200; // shortcut: newest 200 user-days only, page with a cursor once admins need more

const day = sql<string>`to_char(${usage.createdAt} at time zone 'UTC', 'YYYY-MM-DD')`;
const totals = {
  inputTokens: sql<number>`coalesce(sum(${usage.inputTokens}), 0)::int`,
  cachedTokens: sql<number>`coalesce(sum(${usage.cachedTokens}), 0)::int`,
  outputTokens: sql<number>`coalesce(sum(${usage.outputTokens}), 0)::int`,
  costUsd: sql<number>`coalesce(sum(${usage.costUsd}), 0)::float8`,
  turns: sql<number>`count(*)::int`,
};

const startOfToday = () => new Date(Math.floor(Date.now() / DAY_MS) * DAY_MS);

export interface UsageFilter {
  user?: string;
  from?: string; // UTC days, both inclusive
  to?: string;
}

/** LLM spend per user and UTC day, from the `done` events (D44). */
@Injectable()
export class UsageService {
  constructor(
    @Inject(DB) private readonly db: Db,
    @Inject(CONFIG) private readonly config: Config,
  ) {}

  /** The highest role's cap counts. */
  capUsd(user: AuthUser): number {
    const caps = {
      viewer: this.config.DAILY_COST_CAP_USD_VIEWER,
      editor: this.config.DAILY_COST_CAP_USD_EDITOR,
      admin: this.config.DAILY_COST_CAP_USD_ADMIN,
    };
    return Math.max(0, ...user.roles.map((role) => caps[role]));
  }

  /** Before every LLM relay; the turn that crosses the cap may overshoot by its per-run cap. */
  async assertUnderCap(user: AuthUser): Promise<void> {
    const cap = this.capUsd(user);
    const [today] = await this.db
      .select({ costUsd: totals.costUsd })
      .from(usage)
      .where(and(eq(usage.userId, user.sub), gte(usage.createdAt, startOfToday())));
    if (today.costUsd >= cap) {
      throw new HttpException(
        {
          type: 'daily_cap_exceeded',
          message: `Daily cost cap of ${cap.toFixed(2)} USD reached; it resets at 00:00 UTC`,
        },
        HttpStatus.TOO_MANY_REQUESTS,
      );
    }
  }

  /** For relays outside a conversation (`/api/chat`). */
  async record(
    user: AuthUser,
    model: string,
    used: { inputTokens: number; outputTokens: number; costUsd: number | null },
  ): Promise<void> {
    const { inputTokens, outputTokens, costUsd } = used;
    await this.db
      .insert(usage)
      .values({ userId: user.sub, model, inputTokens, outputTokens, costUsd });
  }

  /** Today against the cap, and the last 30 days with usage, newest first. */
  async mine(user: AuthUser) {
    const today = startOfToday();
    const from = new Date(today.getTime() - 29 * DAY_MS);
    const days = await this.days(and(eq(usage.userId, user.sub), gte(usage.createdAt, from)));
    const iso = today.toISOString().slice(0, 10);
    const none = {
      day: iso,
      inputTokens: 0,
      cachedTokens: 0,
      outputTokens: 0,
      costUsd: 0,
      turns: 0,
    };
    return { capUsd: this.capUsd(user), today: days.find((d) => d.day === iso) ?? none, days };
  }

  /** Per user and day, newest first. */
  perUser(filter: UsageFilter) {
    return this.db
      .select({ userId: usage.userId, day, ...totals })
      .from(usage)
      .where(
        and(
          filter.user ? eq(usage.userId, filter.user) : undefined,
          filter.from ? gte(usage.createdAt, new Date(filter.from)) : undefined,
          filter.to ? lt(usage.createdAt, new Date(Date.parse(filter.to) + DAY_MS)) : undefined,
        ),
      )
      .groupBy(usage.userId, day)
      .orderBy(desc(day), usage.userId)
      .limit(LIMIT);
  }

  private days(where: SQL | undefined) {
    return this.db
      .select({ day, ...totals })
      .from(usage)
      .where(where)
      .groupBy(day)
      .orderBy(desc(day));
  }
}
