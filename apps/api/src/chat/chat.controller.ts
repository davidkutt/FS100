import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import type { ReadableStream } from 'node:stream/web';
import { Body, Controller, HttpCode, Post, Req, Res } from '@nestjs/common';
import { ApiOkResponse, ApiProduces } from '@nestjs/swagger';
import type { Response } from 'express';
import {
  AiClient,
  type ChatRequest,
  type SearchRequest,
  type SearchResponse,
} from '../ai-client/ai-client.service.js';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { ChatThrottle } from './chat-throttle.js';

/** Relays to the AI service, which validates the bodies; their types are in `@fs100/contracts/ai-service`. */
@Controller()
@Roles('viewer')
export class ChatController {
  constructor(
    private readonly ai: AiClient,
    private readonly throttle: ChatThrottle,
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
    this.throttle.check(req.user.sub);
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
}
