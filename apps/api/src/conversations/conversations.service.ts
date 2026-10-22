import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { and, asc, desc, eq, gte, sql } from 'drizzle-orm';
import type { AgentRequest } from '../ai-client/ai-client.service.js';
import { redact } from '../audit/redact.js';
import type { AuthUser } from '../auth/auth.guard.js';
import { DB, type Db } from '../db/db.module.js';
import {
  type Approval,
  approvals,
  auditLog,
  type Conversation,
  conversations,
  feedback,
  type Message,
  messages,
  usage,
} from '../db/schema.js';
import {
  type DoneEvent,
  type Part,
  partsOf,
  type ProposalPart,
  type ToolCallPart,
  type ToolResultPart,
} from './events.js';

const HISTORY_MESSAGES = 20; // the AI service trims further by token budget (D41)
const TURN_MAX_CHARS = 8000; // the AI service rejects longer turns

export type Rating = { rating: 'up' | 'down'; comment?: string | null };
export type MessageWithFeedback = Message & { feedback: Rating | null };
type Tx = Parameters<Parameters<Db['transaction']>[0]>[0];

/** A relayed turn; `done` is missing when the run was cancelled or broke off. */
export interface Answer {
  parts: Part[];
  done?: DoneEvent;
  stopReason: string;
  signedActions: Map<string, string>; // approvalId → signedAction of `approval_required`
}

/** Conversations are the system of record for agent turns (D28, D42); every query is per owner. */
@Injectable()
export class ConversationsService {
  constructor(@Inject(DB) private readonly db: Db) {}

  list(user: AuthUser): Promise<Conversation[]> {
    return this.db
      .select()
      .from(conversations)
      .where(eq(conversations.ownerId, user.sub))
      .orderBy(desc(conversations.updatedAt));
  }

  async create(user: AuthUser, body: { title?: string; modelId?: string }): Promise<Conversation> {
    const [conversation] = await this.db
      .insert(conversations)
      .values({ ownerId: user.sub, ...body })
      .returning();
    return conversation;
  }

  /** Someone else's conversation is a 404, so ids don't reveal that it exists. */
  async own(user: AuthUser, id: string): Promise<Conversation> {
    const [conversation] = await this.db
      .select()
      .from(conversations)
      .where(and(eq(conversations.id, id), eq(conversations.ownerId, user.sub)));
    if (!conversation) throw new NotFoundException(`Conversation ${id} not found`);
    return conversation;
  }

  async messages(user: AuthUser, id: string): Promise<MessageWithFeedback[]> {
    const rows = await this.db
      .select({
        message: messages,
        feedback: { rating: feedback.rating, comment: feedback.comment },
      })
      .from(messages)
      .leftJoin(feedback, and(eq(feedback.messageId, messages.id), eq(feedback.userId, user.sub)))
      .where(eq(messages.conversationId, id))
      .orderBy(asc(messages.createdAt));
    return rows.map((row) => ({ ...row.message, feedback: row.feedback }));
  }

  async remove(user: AuthUser, id: string): Promise<void> {
    const admin = user.roles.includes('admin');
    const deleted = await this.db
      .delete(conversations)
      .where(
        admin
          ? eq(conversations.id, id)
          : and(eq(conversations.id, id), eq(conversations.ownerId, user.sub)),
      )
      .returning({ id: conversations.id });
    if (!deleted.length) throw new NotFoundException(`Conversation ${id} not found`);
  }

  /** The last messages as text for the next turn; tool parts stay in the database only. */
  async transcript(id: string): Promise<AgentRequest['messages']> {
    const rows = await this.db
      .select({ role: messages.role, parts: messages.parts })
      .from(messages)
      .where(eq(messages.conversationId, id))
      .orderBy(desc(messages.createdAt))
      .limit(HISTORY_MESSAGES);
    return rows.reverse().flatMap(({ role, parts }) => {
      const text = (parts as Part[])
        .filter((part) => part.type === 'text' && part.text)
        .map((part) => part.text as string)
        .join('\n\n')
        .slice(0, TURN_MAX_CHARS);
      return text ? [{ role, parts: [{ type: 'text' as const, text }] }] : [];
    });
  }

  async addQuestion(conversation: Conversation, text: string, modelId?: string): Promise<void> {
    await this.db.transaction(async (tx) => {
      await tx
        .insert(messages)
        .values({ conversationId: conversation.id, role: 'user', parts: [{ type: 'text', text }] });
      await tx
        .update(conversations)
        .set({
          title: conversation.title ?? text.slice(0, 80),
          modelId: modelId ?? conversation.modelId,
        })
        .where(eq(conversations.id, conversation.id));
    });
  }

  /**
   * The event tee (D42), in one transaction: the message, its usage, the proposed approvals, the
   * resumed write's outcome and one audit row per tool result.
   */
  async addAnswer(
    user: AuthUser,
    conversationId: string,
    { parts, done, stopReason, signedActions }: Answer,
    resumed?: Approval,
  ): Promise<void> {
    await this.db.transaction(async (tx) => {
      const [message] = await tx
        .insert(messages)
        .values({
          conversationId,
          role: 'assistant',
          parts,
          stopReason,
          model: done?.model,
          promptVersion: done?.promptVersion,
          traceId: done?.traceId,
          answerStatus: done?.answerStatus,
          topScore: done?.topScore,
        })
        .returning({ id: messages.id });
      if (done?.model) {
        await tx.insert(usage).values({
          userId: user.sub,
          conversationId,
          messageId: message.id,
          model: done.model,
          inputTokens: done.usage.inputTokens,
          cachedTokens: done.usage.cachedTokens,
          outputTokens: done.usage.outputTokens,
          costUsd: done.usage.costUsd,
        });
      }
      const proposals = partsOf<ProposalPart>(parts, 'approval_required');
      if (proposals.length) {
        await tx.insert(approvals).values(
          proposals.map((proposal) => ({
            id: proposal.approvalId,
            conversationId,
            messageId: message.id,
            requesterId: user.sub,
            callId: proposal.callId,
            tool: proposal.tool,
            args: proposal.args,
            risk: proposal.risk,
            signedAction: signedActions.get(proposal.approvalId)!,
            expiresAt: new Date(proposal.expiresAt),
          })),
        );
      }
      const results = partsOf<ToolResultPart>(parts, 'tool_result');
      const executed = resumed && results.find((result) => result.id === resumed.callId);
      const calls = new Map(partsOf<ToolCallPart>(parts, 'tool_call').map((c) => [c.id, c]));
      const audited = results.flatMap((result) => {
        const call = calls.get(result.id);
        if (!call) return [];
        return [
          {
            actorId: user.sub,
            actorRoles: user.roles,
            conversationId,
            approvalId: result === executed ? resumed?.id : null,
            tool: call.name,
            kind: call.kind,
            serviceIdentity: call.serviceIdentity ?? null, // absent in parts stored before M2.5
            argsRedacted: redact(call.args),
            outcome: result.status,
            traceId: done?.traceId,
          },
        ];
      });
      if (audited.length) await tx.insert(auditLog).values(audited);
      if (resumed?.status === 'executing') {
        const identity = calls.get(resumed.callId)?.serviceIdentity;
        await this.settle(tx, user, resumed, executed, done?.traceId, undefined, identity);
      }
      await tx
        .update(conversations)
        .set({ updatedAt: new Date() })
        .where(eq(conversations.id, conversationId));
    });
  }

  /**
   * executing → succeeded | failed | unknown (ADR-0008). Without a result the write may have run,
   * unless `refused` says the AI service turned it down; both get the write's audit row here.
   */
  private async settle(
    tx: Tx,
    user: AuthUser,
    approval: Approval,
    result?: ToolResultPart,
    traceId?: string | null,
    refused?: string,
    serviceIdentity?: string | null,
  ): Promise<void> {
    const status = result?.status === 'ok' ? 'succeeded' : result || refused ? 'failed' : 'unknown';
    await tx
      .update(approvals)
      .set({ status, error: status === 'failed' ? (result?.summary ?? refused) : null })
      .where(and(eq(approvals.id, approval.id), eq(approvals.status, 'executing')));
    if (result) return; // audited with the other tool results
    await tx.insert(auditLog).values({
      actorId: user.sub,
      actorRoles: user.roles,
      conversationId: approval.conversationId,
      approvalId: approval.id,
      tool: approval.tool,
      kind: 'write',
      serviceIdentity,
      argsRedacted: redact(approval.args),
      outcome: status,
      traceId,
    });
  }

  /** A resumed write whose stream never started. */
  settleUnstarted(user: AuthUser, approval: Approval, refused?: string): Promise<void> {
    return this.db.transaction((tx) =>
      this.settle(tx, user, approval, undefined, undefined, refused),
    );
  }

  async rate(user: AuthUser, messageId: string, rating: Rating): Promise<void> {
    const [message] = await this.db
      .select({ id: messages.id })
      .from(messages)
      .innerJoin(conversations, eq(conversations.id, messages.conversationId))
      .where(
        and(
          eq(messages.id, messageId),
          eq(messages.role, 'assistant'),
          eq(conversations.ownerId, user.sub),
        ),
      );
    if (!message) throw new NotFoundException(`Message ${messageId} not found`);
    const values = { rating: rating.rating, comment: rating.comment ?? null };
    await this.db
      .insert(feedback)
      .values({ messageId, userId: user.sub, ...values })
      .onConflictDoUpdate({ target: [feedback.messageId, feedback.userId], set: values });
  }

  /** Today (UTC) from the `usage` rows; daily caps build on this in M2.7. */
  async usageToday(user: AuthUser) {
    const [today] = await this.db
      .select({
        inputTokens: sql<number>`coalesce(sum(${usage.inputTokens}), 0)::int`,
        cachedTokens: sql<number>`coalesce(sum(${usage.cachedTokens}), 0)::int`,
        outputTokens: sql<number>`coalesce(sum(${usage.outputTokens}), 0)::int`,
        costUsd: sql<number>`coalesce(sum(${usage.costUsd}), 0)::float8`,
        turns: sql<number>`count(*)::int`,
      })
      .from(usage)
      .where(and(eq(usage.userId, user.sub), gte(usage.createdAt, sql`date_trunc('day', now())`)));
    return today;
  }
}
