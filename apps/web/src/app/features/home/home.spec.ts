import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { APP_CONFIG } from '../../core/config';
import { Home } from './home';

describe('Home', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: APP_CONFIG, useValue: { apiBaseUrl: 'http://api' } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  async function render(roles: string[]): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(Home);
    TestBed.tick();
    http.expectOne('http://api/api/me').flush({ sub: '1', name: 'Alice Admin', roles });
    await Promise.resolve();
    TestBed.tick();
    if (roles.includes('admin')) {
      http.expectOne('http://api/api/status').flush({ api: 'ok', aiService: 'down' });
    }
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('greets the user with their roles', async () => {
    const page = await render(['viewer']);

    expect(page.querySelector('h1')?.textContent).toMatch(/Hello Alice Admin\s+· viewer/);
    expect(page.querySelector('#status-heading')).toBeNull();
  });

  it('shows the status card to admins', async () => {
    const page = await render(['admin', 'editor', 'viewer']);

    const items = Array.from(page.querySelectorAll('section.card li')).map((li) =>
      li.textContent?.replace(/\s+/g, ' ').trim(),
    );
    expect(items).toEqual(['aiService: down', 'api: ok']);
  });
});
