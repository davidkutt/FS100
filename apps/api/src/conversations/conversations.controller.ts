import { once } from 'node:events';
import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Post,
  Req,
  Res,
} from '@nestjs/common';
import { ApiCreatedResponse, ApiOkResponse, ApiProduces } from '@nestjs/swagger';
import type { Response } from 'express';
import { z } from 'zod';
import { AiClient } from '../ai-client/ai-client.service.js';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { DomainSchema } from '../catalog/taxonomy.js';
import { ChatThrottle } from '../chat/chat-throttle.js';
import { ANSWER_STATUSES, type Conversation } from '../db/schema.js';
import { ConversationsService, type MessageWithFeedback } from './conversations.service.js';
import { applyEvent, type DoneEvent, type Part, sseParser } from './events.js';

const NewConversation = z
  .object({ title: z.string().max(200).optional(), modelId: z.string().optional() })
  .meta({ id: 'NewConversation' });

const NewMessage = z
  .object({
    text: z.string().trim().min(1).max(8000),
    modelId: z.string().optional(), // also becomes the conversation's model
    mode: z.enum(['agent', 'rag']).optional(),
    domains: z.array(DomainSchema).optional(),
  })
  .meta({ id: 'NewMessage' });

const Rating = z
  .object({ rating: z.enum(['up', 'down']), comment: z.string().max(2000).nullish() })
  .meta({ id: 'Rating' });

const timestamp = z.iso.datetime({ offset: true });

/** Response contracts for the OpenAPI document; `test/conversations.e2e-spec.ts` checks rows against them. */
export const ConversationDto = z
  .object({
    id: z.uuid(),
    title: z.string().nullable(),
    modelId: z.string().nullable(),
    createdAt: timestamp,
    updatedAt: timestamp,
  })
  .meta({ id: 'Conversation' });

export const MessageDto = z
  .object({
    id: z.uuid(),
    role: z.enum(['user', 'assistant']),
    // SSE v2 payloads (`@fs100/contracts/ai-service`) under their event name as `type`.
    parts: z.array(z.looseObject({ type: z.string() })),
    model: z.string().nullable(),
    promptVersion: z.string().nullable(),
    stopReason: z.string().nullable(),
    traceId: z.string().nullable(),
    answerStatus: z.enum(ANSWER_STATUSES).nullable(),
    topScore: z.number().nullable(),
    createdAt: timestamp,
    feedback: Rating.nullable(),
  })
  .meta({ id: 'Message' });

export const ConversationDetail = ConversationDto.extend({ messages: z.array(MessageDto) }).meta({
  id: 'ConversationDetail',
});

export const UsageToday = z
  .object({
    inputTokens: z.int(),
    cachedTokens: z.int(),
    outputTokens: z.int(),
    costUsd: z.number(),
    turns: z.int(),
  })
  .meta({ id: 'UsageToday' });

@Controller()
@Roles('viewer')
export class ConversationsController {
  constructor(
    private readonly conversations: ConversationsService,
    private readonly ai: AiClient,
    private readonly throttle: ChatThrottle,
  ) {}

  @Get('conversations')
  @ApiOkResponse({ standardSchema: z.array(ConversationDto) })
  list(@Req() req: AuthRequest): Promise<Conversation[]> {
    return this.conversations.list(req.user);
  }

  @Post('conversations')
  @ApiCreatedResponse({ standardSchema: ConversationDto })
  create(
    @Req() req: AuthRequest,
    @Body({ schema: NewConversation }) body: z.infer<typeof NewConversation>,
  ): Promise<Conversation> {
    return this.conversations.create(req.user, body);
  }

  @Get('conversations/:id')
  @ApiOkResponse({ standardSchema: ConversationDetail })
  async get(
    @Req() req: AuthRequest,
    @Param('id', ParseUUIDPipe) id: string,
  ): Promise<Conversation & { messages: MessageWithFeedback[] }> {
    const conversation = await this.conversations.own(req.user, id);
    return { ...conversation, messages: await this.conversations.messages(req.user, id) };
  }

  /** Owners delete their own, admins any (D42). */
  @Delete('conversations/:id')
  @HttpCode(204)
  remove(@Req() req: AuthRequest, @Param('id', ParseUUIDPipe) id: string): Promise<void> {
    return this.conversations.remove(req.user, id);
  }

  /**
   * One agent turn: the API adds the stored transcript, relays the AI service's SSE v2 bytes
   * unchanged and tees the events into the assistant message. A disconnect cancels the run.
   */
  @Post('conversations/:id/messages')
  @HttpCode(200)
  @ApiProduces('text/event-stream')
  @ApiOkResponse({
    description:
      'SSE v2: `step`, `tool_call`, `tool_result`, `sources`, `token`…, then `done` (with `error` before it on failures)',
  })
  async send(
    @Req() req: AuthRequest,
    @Res() res: Response,
    @Param('id', ParseUUIDPipe) id: string,
    @Body({ schema: NewMessage }) body: z.infer<typeof NewMessage>,
  ): Promise<void> {
    this.throttle.check(req.user.sub);
    const conversation = await this.conversations.own(req.user, id);
    const history = await this.conversations.transcript(id);
    let cancelled = false;
    const abort = new AbortController();
    res.on('close', () => {
      cancelled = !res.writableFinished;
      abort.abort();
    });
    const upstream = await this.ai
      .agent(
        {
          conversation_id: id,
          messages: [...history, { role: 'user', parts: [{ type: 'text', text: body.text }] }],
          mode: body.mode,
          model: body.modelId ?? conversation.modelId,
          domains: body.domains,
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
    // Stored only once the AI service accepted the turn, so a rejected one leaves no orphan.
    await this.conversations.addQuestion(conversation, body.text, body.modelId);
    res.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache, no-transform',
      'x-accel-buffering': 'no',
    });

    const parts: Part[] = [];
    let done: DoneEvent | undefined;
    const parse = sseParser((event, data) => {
      const payload = JSON.parse(data) as Record<string, unknown>;
      if (event === 'done') done = payload as unknown as DoneEvent;
      applyEvent(parts, event, payload);
    });
    // Not `pipeline`: it would destroy the response when the upstream breaks, which reads as a cancel.
    try {
      for await (const chunk of upstream.body as AsyncIterable<Uint8Array>) {
        parse(chunk);
        if (!res.write(chunk)) await once(res, 'drain', { signal: abort.signal });
      }
    } catch {
      // The upstream broke off, or the client left (which aborts the upstream).
    }
    const stopReason = done?.stopReason ?? (cancelled ? 'cancelled' : 'error');
    // Stored before the end, so a client that reloads on end finds the answer.
    await this.conversations
      .addAnswer(req.user, id, parts, done, stopReason)
      .finally(() => res.end());
  }

  @Post('messages/:id/feedback')
  @HttpCode(204)
  rate(
    @Req() req: AuthRequest,
    @Param('id', ParseUUIDPipe) id: string,
    @Body({ schema: Rating }) body: z.infer<typeof Rating>,
  ): Promise<void> {
    return this.conversations.rate(req.user, id, body);
  }

  @Get('me/usage')
  @ApiOkResponse({ standardSchema: UsageToday })
  usage(@Req() req: AuthRequest): Promise<z.infer<typeof UsageToday>> {
    return this.conversations.usageToday(req.user);
  }
}
