import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import type { ReadableStream } from 'node:stream/web';
import {
  Body,
  Controller,
  HttpCode,
  HttpException,
  HttpStatus,
  Inject,
  Post,
  Req,
  Res,
} from '@nestjs/common';
import { ApiOkResponse, ApiProduces } from '@nestjs/swagger';
import type { Response } from 'express';
import {
  AiClient,
  type ChatRequest,
  type SearchRequest,
  type SearchResponse,
} from '../ai-client/ai-client.service.js';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { CONFIG, type Config } from '../config.js';

/** Relays to the AI service, which validates the bodies; their types are in `@fs100/contracts/ai-service`. */
@Controller()
@Roles('viewer')
export class ChatController {
  private window = 0;
  private readonly counts = new Map<string, number>();

  constructor(
    private readonly ai: AiClient,
    @Inject(CONFIG) private readonly config: Config,
  ) {}

  /** SSE events pass through unchanged (D12); a client disconnect aborts the upstream request. */
  @Post('chat')
  @HttpCode(200)
  @ApiProduces('text/event-stream')
  @ApiOkResponse({ description: 'SSE: `SourcesEvent`, `TokenEvent`…, `DoneEvent` or `ErrorEvent`' })
  async chat(
    @Req() req: AuthRequest,
    @Res() res: Response,
    @Body() body: Partial<Omit<ChatRequest, 'user'>> | undefined,
  ): Promise<void> {
    this.throttle(req.user.sub);
    const abort = new AbortController();
    res.on('close', () => abort.abort());
    const upstream = await this.ai
      .chat(
        {
          messages: body?.messages ?? [],
          domains: body?.domains,
          user: { sub: req.user.sub, roles: req.user.roles },
        },
        req.id as string,
        abort.signal,
      )
      .catch((error: unknown) => {
        if (abort.signal.aborted) return undefined; // the client left before the first event
        throw error;
      });
    if (!upstream) return;
    res.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache, no-transform',
      'x-accel-buffering': 'no',
    });
    // Rejects when either side hangs up; the response is committed, so there is nothing to send.
    await pipeline(Readable.fromWeb(upstream.body as ReadableStream), res).catch(() => undefined);
  }

  @Post('search')
  @HttpCode(200)
  search(@Req() req: AuthRequest, @Body() body: SearchRequest): Promise<SearchResponse> {
    return this.ai.search(body, req.id as string);
  }

  private throttle(sub: string): void {
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
