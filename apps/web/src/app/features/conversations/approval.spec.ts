import { TestBed } from '@angular/core/testing';
import { ApprovalCard, type Decision } from './approval';
import type { Proposal } from './parts';

const proposal = (msLeft: number): Proposal => ({
  type: 'approval_required',
  approvalId: 'a1',
  callId: 'w1',
  tool: 'github_sandbox.create_issue',
  args: { title: 'Flaky test' },
  risk: 'medium',
  expiresAt: new Date(Date.now() + msLeft).toISOString(),
});

describe('ApprovalCard', () => {
  async function render(msLeft: number, status = 'pending', error: string | null = null) {
    const fixture = TestBed.createComponent(ApprovalCard);
    fixture.componentRef.setInput('proposal', proposal(msLeft));
    fixture.componentRef.setInput('approval', { status, error });
    const decided: Decision[] = [];
    fixture.componentInstance.decided.subscribe((decision) => decided.push(decision));
    await fixture.whenStable();
    return { page: fixture.nativeElement as HTMLElement, decided };
  }

  it('rejects with the note', async () => {
    const { page, decided } = await render(60_000);
    page.querySelector('input')!.value = 'Wrong repo';

    page.querySelector<HTMLButtonElement>('button.btn-outline-danger')!.click();

    expect(decided).toEqual([{ decision: 'reject', note: 'Wrong repo' }]);
  });

  it('a pending action past its expiry shows as expired, without buttons', async () => {
    const { page } = await render(-1000);

    expect(page.textContent).toContain('Expired.');
    expect(page.querySelector('button')).toBeNull();
  });

  it('an unknown outcome says it is never retried', async () => {
    const { page } = await render(60_000, 'unknown');

    expect(page.textContent).toContain('It is never retried.');
  });
});
