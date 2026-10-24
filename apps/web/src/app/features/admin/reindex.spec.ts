import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { APP_CONFIG } from '../../core/config';
import { Reindex } from './reindex';

const metrics = (ndcg: number) => ({ 'hit@5': 1, 'mrr@10': 0.9, 'ndcg@10': ndcg, n: 20 });
const RUN = {
  id: 7,
  state: 'ready',
  reason: 'new chunker',
  force: false,
  requested_by: 'alice',
  report: {
    reason: 'new chunker',
    force: false,
    requested_by: 'alice',
    collection: 'kb__v2__new',
    previous: 'kb__v2__old',
    documents: 30,
    chunks: 218,
    skipped: [],
    metrics: { test: { candidate: metrics(0.75), live: metrics(0.8) } },
    blockers: ['test ndcg@10 0.750 < baseline 0.800 - 0.02'],
    decision: 'kept',
    build_s: 95,
  },
};

describe('Reindex', () => {
  it('shows the gate of each run and starts a re-index with its reason', async () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: APP_CONFIG, useValue: { apiBaseUrl: 'http://api' } },
      ],
    });
    const fixture = TestBed.createComponent(Reindex);
    const http = TestBed.inject(HttpTestingController);
    const page = fixture.nativeElement as HTMLElement;
    TestBed.tick();
    http
      .expectOne('http://api/api/admin/reindex')
      .flush({ alias: 'kb_current', collection: 'kb__v2__old', runs: [RUN] });
    await fixture.whenStable();

    expect(page.textContent).toContain('kb_current points at kb__v2__old');
    const row = page.querySelector('tbody tr')!.textContent!;
    expect(row).toMatch(/kept/);
    expect(row).toMatch(/ndcg@10 0\.750\s*\(-0\.050\)/);
    expect(row).toContain('test ndcg@10 0.750 < baseline 0.800 - 0.02');

    const force = page.querySelector<HTMLInputElement>('#reindex-force')!;
    force.click();
    await fixture.whenStable();
    const submit = page.querySelector<HTMLButtonElement>('button[type=submit]')!;
    expect(submit.disabled).toBe(true); // forcing needs a reason
    const reason = page.querySelector<HTMLInputElement>('#reindex-reason')!;
    reason.value = 'accept the new chunker';
    reason.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    submit.click();

    const post = http.expectOne('http://api/api/admin/reindex');
    expect(post.request.body).toEqual({ reason: 'accept the new chunker', force: true });
    post.flush({ jobId: 8 });
    const reload = await vi.waitFor(() => http.expectOne('http://api/api/admin/reindex'));
    reload.flush({ alias: 'kb_current', collection: 'kb__v2__old', runs: [] });
    await fixture.whenStable();
    expect(page.textContent).toContain('No re-index yet.');
  });
});
