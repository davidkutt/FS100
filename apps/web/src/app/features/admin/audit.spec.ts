import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { APP_CONFIG } from '../../core/config';
import { Audit } from './audit';

const ENTRY = {
  id: 1,
  ts: '2026-10-20T10:00:00Z',
  actorId: 'alice',
  actorRoles: ['viewer', 'editor'],
  serviceIdentity: null,
  conversationId: null,
  approvalId: null,
  tool: 'github_sandbox.create_issue',
  kind: 'write',
  argsRedacted: { title: 'Flaky test' },
  outcome: 'ok',
  traceId: 'abc',
};

describe('Audit', () => {
  it('lists entries and sends only the filters that are set', async () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: APP_CONFIG, useValue: { apiBaseUrl: 'http://api', phoenixUrl: 'http://px' } },
      ],
    });
    const fixture = TestBed.createComponent(Audit);
    const http = TestBed.inject(HttpTestingController);
    const page = fixture.nativeElement as HTMLElement;
    TestBed.tick();
    http.expectOne('http://api/api/admin/audit').flush([ENTRY]);
    await fixture.whenStable();

    expect(page.querySelector('tbody')?.textContent).toContain('github_sandbox.create_issue');
    expect(page.querySelector<HTMLAnchorElement>('a[href^="http://px"]')?.href).toBe(
      'http://px/redirects/traces/abc',
    );

    const outcome = page.querySelector<HTMLSelectElement>('#audit-outcome')!;
    outcome.value = 'unknown';
    outcome.dispatchEvent(new Event('change'));
    TestBed.tick();

    http.expectOne('http://api/api/admin/audit?outcome=unknown').flush([]);
    await fixture.whenStable();
    expect(page.querySelector('tbody')?.textContent).toContain('No tool calls match.');
  });
});
