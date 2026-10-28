import { once } from 'node:events';
import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  HttpException,
  Param,
  ParseUUIDPipe,
  Post,
  Query,
  Req,
  Res,
} from '@nestjs/common';
import { ApiCreatedResponse, ApiOkResponse, ApiProduces } from '@nestjs/swagger';
import type { Response } from 'express';
import { z } from 'zod';
import { AiClient, type AgentRequest } from '../ai-client/ai-client.service.js';
import { type AuthRequest, Roles } from '../auth/auth.guard.js';
import { DomainSchema } from '../catalog/taxonomy.js';
import { ChatThrottle } from '../chat/chat-throttle.js';
import {
  ANSWER_STATUSES,
  APPROVAL_STATUSES,
  type Approval,
  type Conversation,
} from '../db/schema.js';
import { UsageService } from '../usage/usage.service.js';
import { ApprovalsService, type VisibleApproval } from './approvals.service.js';
import {
  type Answer,
  ConversationsService,
  type MessageWithFeedback,
} from './conversations.service.js';
import { applyEvent, type DoneEvent, sseBlock, sseParser } from './events.js';

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

const Decision = z
  .object({
    decision: z.enum(['approve', 'reject']),
    note: z.string().trim().max(2000).optional(),
  })
  .meta({ id: 'Decision' });

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
    // SSE v2 payloads (`@grove/contracts/ai-service`) under their event name as `type`.
    parts: z.array(z.looseObject({ type: z.string() })),
    model: z.string().nullable(),
    promptVersion: z.string().nullable(),
    promptHash: z.string().nullable(),
    stopReason: z.string().nullable(),
    traceId: z.string().nullable(),
    answerStatus: z.enum(ANSWER_STATUSES).nullable(),
    topScore: z.number().nullable(),
    createdAt: timestamp,
    feedback: Rating.nullable(),
  })
  .meta({ id: 'Message' });

/** Never with `signedAction` (D29). */
export const ApprovalDto = z
  .object({
    id: z.uuid(),
    conversationId: z.uuid(),
    messageId: z.uuid(),
    requesterId: z.string(),
    callId: z.string(),
    tool: z.string(),
    args: z.record(z.string(), z.unknown()),
    risk: z.string(),
    status: z.enum(APPROVAL_STATUSES),
    note: z.string().nullable(),
    error: z.string().nullable(),
    createdAt: timestamp,
    expiresAt: timestamp,
    decidedAt: timestamp.nullable(),
    executedAt: timestamp.nullable(),
  })
  .meta({ id: 'Approval' });

export const ConversationDetail = ConversationDto.extend({
  messages: z.array(MessageDto),
  approvals: z.array(ApprovalDto),
}).meta({ id: 'ConversationDetail' });

@Controller()
@Roles('viewer')
export class ConversationsController {
  constructor(
    private readonly conversations: ConversationsService,
    private readonly approvals: ApprovalsService,
    private readonly ai: AiClient,
    private readonly throttle: ChatThrottle,
    private readonly usage: UsageService,
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
  ): Promise<Conversation & { messages: MessageWithFeedback[]; approvals: VisibleApproval[] }> {
    const conversation = await this.conversations.own(req.user, id);
    return {
      ...conversation,
      messages: await this.conversations.messages(req.user, id),
      approvals: await this.approvals.ofConversation(id),
    };
  }

  /** Owners delete their own, admins any (D42). */
  @Delete('conversations/:id')
  @HttpCode(204)
  remove(@Req() req: AuthRequest, @Param('id', ParseUUIDPipe) id: string): Promise<void> {
    return this.conversations.remove(req.user, id);
  }

  /**
   * One agent turn: the API adds the stored transcript, relays the AI service's SSE v2 and tees
   * the events into the assistant message. A disconnect cancels the run.
   */
  @Post('conversations/:id/messages')
  @HttpCode(200)
  @ApiProduces('text/event-stream')
  @ApiOkResponse({
    description:
      'SSE v2: `step`, `tool_call`, `tool_result`, `sources`, `token`…, `approval_required` (without `signedAction`), then `done` (with `error` before it on failures)',
  })
  async send(
    @Req() req: AuthRequest,
    @Res() res: Response,
    @Param('id', ParseUUIDPipe) id: string,
    @Body({ schema: NewMessage }) body: z.infer<typeof NewMessage>,
  ): Promise<void> {
    this.throttle.check(req.user.sub);
    await this.usage.assertUnderCap(req.user);
    const conversation = await this.conversations.own(req.user, id);
    const history = await this.conversations.transcript(id);
    const turn = {
      conversation_id: id,
      messages: [
        ...history,
        { role: 'user' as const, parts: [{ type: 'text' as const, text: body.text }] },
      ],
      mode: body.mode,
      model: body.modelId ?? conversation.modelId,
      domains: body.domains,
    };
    // Stored only once the AI service accepted the turn, so a rejected one leaves no orphan.
    await this.relay(req, res, turn, () =>
      this.conversations.addQuestion(conversation, body.text, body.modelId),
    );
  }

  /** Own approvals; admins see all, but decide only their own. */
  @Get('approvals')
  @ApiOkResponse({ standardSchema: z.array(ApprovalDto) })
  listApprovals(
    @Req() req: AuthRequest,
    @Query({ schema: z.object({ status: z.enum(APPROVAL_STATUSES).optional() }) })
    query: { status?: Approval['status'] },
  ): Promise<VisibleApproval[]> {
    return this.approvals.list(req.user, query.status);
  }

  /**
   * The requester decides a proposed write (ADR-0008); the turn then continues like `send`,
   * starting with the decided `tool_call` and its `tool_result`.
   */
  @Post('approvals/:id')
  @HttpCode(200)
  @ApiProduces('text/event-stream')
  @ApiOkResponse({ description: 'SSE v2 continuation of the turn that proposed the action' })
  async decide(
    @Req() req: AuthRequest,
    @Res() res: Response,
    @Param('id', ParseUUIDPipe) id: string,
    @Body({ schema: Decision }) body: z.infer<typeof Decision>,
  ): Promise<void> {
    this.throttle.check(req.user.sub);
    // Before the decision, so a capped user's approval stays pending.
    await this.usage.assertUnderCap(req.user);
    let approval = await this.approvals.decide(
      req.user,
      id,
      body.decision,
      body.note,
      req.id as string,
    );
    const conversation = await this.conversations.own(req.user, approval.conversationId);
    if (approval.status === 'approved') approval = await this.approvals.execute(approval);
    const history = await this.conversations.transcript(conversation.id);
    // The continuation follows the question, not the answer that stopped for approval.
    while (history.at(-1)?.role === 'assistant') history.pop();
    const turn = {
      conversation_id: conversation.id,
      messages: history,
      model: conversation.modelId,
      resume: {
        signed_action: approval.signedAction,
        decision: body.decision,
        note: body.note,
        args: approval.args,
      },
    };
    await this.relay(req, res, turn, async () => undefined, approval);
  }

  /** Relays one run and stores it; `signedAction` is cut from the browser's copy (D29). */
  private async relay(
    req: AuthRequest,
    res: Response,
    turn: AgentRequest,
    accepted: () => Promise<void>,
    resumed?: Approval,
  ): Promise<void> {
    let cancelled = false;
    const abort = new AbortController();
    res.on('close', () => {
      cancelled = !res.writableFinished;
      abort.abort();
    });
    const upstream = await this.ai
      .agent(turn, req.id as string, abort.signal, req.accessToken, resumed !== undefined)
      .catch(async (error: unknown) => {
        if (resumed?.status === 'executing') {
          // An error status means the AI service refused the action before running it.
          const refused = error instanceof HttpException ? error.message : undefined;
          await this.conversations.settleUnstarted(req.user, resumed, refused);
        }
        if (abort.signal.aborted) return undefined; // the client left before the first event
        throw error;
      });
    if (!upstream) return;
    await accepted();
    res.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache, no-transform',
      'x-accel-buffering': 'no',
    });

    const answer: Answer = { parts: [], stopReason: 'error', signedActions: new Map() };
    let done: DoneEvent | undefined;
    const parse = sseParser((event, data) => {
      const payload = JSON.parse(data) as Record<string, unknown>;
      if (event === 'done') done = payload as unknown as DoneEvent;
      if (event === 'approval_required') {
        const { signedAction, ...visible } = payload;
        answer.signedActions.set(visible.approvalId as string, signedAction as string);
        applyEvent(answer.parts, event, visible);
        return sseBlock(event, visible);
      }
      applyEvent(answer.parts, event, payload);
    });
    // Not `pipeline`: it would destroy the response when the upstream breaks, which reads as a cancel.
    try {
      for await (const chunk of upstream.body as AsyncIterable<Uint8Array>) {
        const forward = parse(chunk);
        if (forward && !res.write(forward)) await once(res, 'drain', { signal: abort.signal });
      }
    } catch {
      // The upstream broke off, or the client left (which aborts the upstream).
    }
    answer.done = done;
    answer.stopReason = done?.stopReason ?? (cancelled ? 'cancelled' : 'error');
    // Stored before the end, so a client that reloads on end finds the answer.
    await this.conversations
      .addAnswer(req.user, turn.conversation_id, answer, resumed)
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
}
