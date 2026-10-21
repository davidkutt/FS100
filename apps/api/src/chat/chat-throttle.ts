import { HttpException, HttpStatus, Inject, Injectable } from '@nestjs/common';
import { CONFIG, type Config } from '../config.js';

/** One budget per user for every LLM relay (`/chat`, conversation messages). */
@Injectable()
export class ChatThrottle {
  private window = 0;
  private readonly counts = new Map<string, number>();

  constructor(@Inject(CONFIG) private readonly config: Config) {}

  check(sub: string): void {
    // shortcut: per-instance fixed window in memory; move to a shared store before scaling out (P4).
    const window = Math.floor(Date.now() / 60_000);
    if (window !== this.window) {
      this.window = window;
      this.counts.clear();
    }
    const count = (this.counts.get(sub) ?? 0) + 1;
    this.counts.set(sub, count);
    if (count > this.config.CHAT_THROTTLE_PER_MIN) {
      throw new HttpException(
        `Chat limit of ${this.config.CHAT_THROTTLE_PER_MIN} per minute reached`,
        HttpStatus.TOO_MANY_REQUESTS,
      );
    }
  }
}
