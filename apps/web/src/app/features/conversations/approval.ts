import { JsonPipe } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import type { components } from '@grove/contracts/api';
import type { Proposal } from './parts';

type Approval = components['schemas']['Approval'];
export interface Decision {
  decision: 'approve' | 'reject';
  note?: string;
}

const OUTCOMES: Record<Approval['status'], string> = {
  pending: 'Waiting for your decision.',
  approved: 'Approved.',
  executing: 'Approved, running…',
  succeeded: 'Approved and done.',
  failed: 'Approved, but it failed.',
  rejected: 'Rejected.',
  expired: 'Expired. Ask again if it is still needed.',
  unknown: 'Outcome unknown: check the target before asking again. It is never retried.',
};

/** A proposed write (ADR-0008): the exact arguments, the risk and the time left to decide. */
@Component({
  selector: 'app-approval',
  imports: [JsonPipe],
  template: `
    @let id = proposal().approvalId;
    <section class="card border-warning mb-3" [attr.aria-labelledby]="'approval-' + id">
      <div class="card-body">
        <h2 class="h6 card-title" [id]="'approval-' + id">
          Run <code>{{ proposal().tool }}</code
          >?
          <span
            class="badge ms-1"
            [class]="proposal().risk === 'low' ? 'text-bg-secondary' : 'text-bg-warning'"
            >{{ proposal().risk }} risk</span
          >
        </h2>
        <pre class="bg-body-tertiary rounded p-2"><code>{{ proposal().args | json }}</code></pre>
        @if (status() === 'pending') {
          <p class="small text-body-secondary">Expires in {{ left() }}.</p>
          <label class="form-label small" [for]="'note-' + id">Note for the agent (optional)</label>
          <input
            #note
            class="form-control form-control-sm mb-2"
            maxlength="2000"
            [id]="'note-' + id"
          />
          <div class="d-flex gap-2">
            <button
              type="button"
              class="btn btn-sm btn-success"
              [disabled]="disabled()"
              (click)="decided.emit({ decision: 'approve', note: note.value })"
            >
              Approve
            </button>
            <button
              type="button"
              class="btn btn-sm btn-outline-danger"
              [disabled]="disabled()"
              (click)="decided.emit({ decision: 'reject', note: note.value })"
            >
              Reject
            </button>
          </div>
        } @else {
          <p class="small mb-0">{{ outcomes[status()] }}</p>
          @if (approval()?.error; as error) {
            <p class="small text-danger mb-0">{{ error }}</p>
          }
        }
      </div>
    </section>
  `,
  styles: `
    pre {
      max-height: 16rem;
      white-space: pre-wrap;
    }
  `,
})
export class ApprovalCard {
  readonly proposal = input.required<Proposal>();
  /** The stored state; missing while the proposing turn still streams. */
  readonly approval = input<Approval>();
  readonly disabled = input(false);
  readonly decided = output<Decision>();

  protected readonly outcomes = OUTCOMES;
  private readonly now = signal(Date.now());
  private readonly msLeft = computed(() =>
    Math.max(0, Date.parse(this.proposal().expiresAt) - this.now()),
  );
  /** Expired on screen when the clock runs out; the API agrees on its next read. */
  protected readonly status = computed(() => {
    const status = this.approval()?.status ?? 'pending';
    return status === 'pending' && !this.msLeft() ? 'expired' : status;
  });
  protected readonly left = computed(() => {
    const seconds = Math.ceil(this.msLeft() / 1000);
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  });

  constructor() {
    const timer = setInterval(() => this.now.set(Date.now()), 1000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }
}
