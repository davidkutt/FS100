import {
  ConflictException,
  ForbiddenException,
  GoneException,
  Inject,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import type { components } from '@fs100/contracts/ai-service';
import { and, asc, desc, eq, getTableColumns, gt, lte, sql } from 'drizzle-orm';
import { AiClient } from '../ai-client/ai-client.service.js';
import type { AuthUser } from '../auth/auth.guard.js';
import { DB, type Db } from '../db/db.module.js';
import { type Approval, type ApprovalStatus, approvals } from '../db/schema.js';

// The signed action never leaves the API (D29).
const { signedAction: _, ...visible } = getTableColumns(approvals);
export type VisibleApproval = Omit<Approval, 'signedAction'>;

/** pending → approved | rejected | expired → executing → succeeded | failed | unknown (ADR-0008). */
@Injectable()
export class ApprovalsService {
  constructor(
    @Inject(DB) private readonly db: Db,
    private readonly ai: AiClient,
  ) {}

  /** Admins see everyone's, but decide only their own (plan-phase-2 §7.6). */
  async list(user: AuthUser, status?: ApprovalStatus): Promise<VisibleApproval[]> {
    await this.expire();
    return this.db
      .select(visible)
      .from(approvals)
      .where(
        and(
          status && eq(approvals.status, status),
          user.roles.includes('admin') ? undefined : eq(approvals.requesterId, user.sub),
        ),
      )
      .orderBy(desc(approvals.createdAt));
  }

  async ofConversation(conversationId: string): Promise<VisibleApproval[]> {
    await this.expire();
    return this.db
      .select(visible)
      .from(approvals)
      .where(eq(approvals.conversationId, conversationId))
      .orderBy(asc(approvals.createdAt));
  }

  /** Conditional, so a second click (or a replay) finds the row no longer `pending`. */
  async decide(
    user: AuthUser,
    id: string,
    decision: 'approve' | 'reject',
    note: string | undefined,
    requestId: string,
  ): Promise<Approval> {
    const [approval] = await this.db
      .select()
      .from(approvals)
      .where(and(eq(approvals.id, id), eq(approvals.requesterId, user.sub)));
    if (!approval) throw new NotFoundException(`Approval ${id} not found`);
    if (decision === 'approve') await this.checkRole(user, approval.tool, requestId);
    const [decided] = await this.db
      .update(approvals)
      .set({
        status: decision === 'approve' ? 'approved' : 'rejected',
        note,
        decidedAt: new Date(),
      })
      .where(
        and(
          eq(approvals.id, id),
          eq(approvals.status, 'pending'),
          gt(approvals.expiresAt, sql`now()`),
        ),
      )
      .returning();
    if (decided) return decided;
    await this.expire();
    const [{ status }] = await this.db
      .select({ status: approvals.status })
      .from(approvals)
      .where(eq(approvals.id, id));
    if (status === 'expired') {
      throw new GoneException({ type: 'approval_expired', message: `Approval ${id} has expired` });
    }
    throw new ConflictException({
      type: 'approval_state_conflict',
      message: `Approval ${id} is already ${status}`,
    });
  }

  /** approved → executing, right before the AI service gets the action. */
  async execute(approval: Approval): Promise<Approval> {
    const [executing] = await this.db
      .update(approvals)
      .set({ status: 'executing', executedAt: new Date() })
      .where(and(eq(approvals.id, approval.id), eq(approvals.status, 'approved')))
      .returning();
    return executing;
  }

  /** The role may have dropped since the proposal; the AI service checks it again (D30). */
  private async checkRole(user: AuthUser, tool: string, requestId: string): Promise<void> {
    const tools = await this.ai.get<components['schemas']['ToolInfo'][]>('/v1/tools', requestId);
    const minRole = tools.find((info) => info.name === tool)?.min_role;
    // Keycloak expands composite roles, so the minimum role is in the token if it is reached.
    if (!minRole || !user.roles.includes(minRole)) {
      throw new ForbiddenException({
        type: 'tool_not_permitted',
        message: `${tool} is not permitted for your role`,
      });
    }
  }

  /** Instead of a timer job: pending rows past `expiresAt` expire whenever approvals are read. */
  private expire() {
    return this.db
      .update(approvals)
      .set({ status: 'expired' })
      .where(and(eq(approvals.status, 'pending'), lte(approvals.expiresAt, sql`now()`)));
  }
}
