import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { APP_CONFIG } from '../../core/config';
import { Usage } from './usage';

const ROW = {
  userId: 'alice',
  day: '2026-10-22',
  inputTokens: 12000,
  cachedTokens: 4000,
  outputTokens: 800,
  costUsd: 0.0312,
  turns: 5,
};

describe('Usage', () => {
  it('lists usage per user and day and sends only the filters that are set', async () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: APP_CONFIG, useValue: { apiBaseUrl: 'http://api' } },
      ],
    });
    const fixture = TestBed.createComponent(Usage);
    const http = TestBed.inject(HttpTestingController);
    const page = fixture.nativeElement as HTMLElement;
    TestBed.tick();
    http.expectOne('http://api/api/admin/usage').flush([ROW]);
    await fixture.whenStable();

    expect(page.querySelector('tbody')?.textContent).toMatch(/alice\s*5\s*12,000\s*\(4,000\)/);
    expect(page.querySelector('tbody')?.textContent).toContain('$0.0312');

    const from = page.querySelector<HTMLInputElement>('#usage-from')!;
    from.value = '2026-10-01';
    from.dispatchEvent(new Event('input'));
    TestBed.tick();

    http.expectOne('http://api/api/admin/usage?from=2026-10-01').flush([]);
    await fixture.whenStable();
    expect(page.querySelector('tbody')?.textContent).toContain('No usage matches.');
  });
});
