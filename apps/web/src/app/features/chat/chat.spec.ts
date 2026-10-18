import { TestBed, type ComponentFixture } from '@angular/core/testing';
import Keycloak from 'keycloak-js';
import { APP_CONFIG } from '../../core/config';
import { Chat } from './chat';

const SOURCE = {
  n: 1,
  docId: '00000000-0000-0000-0000-000000000001',
  title: 'Rollback runbook',
  page: 2,
  heading: 'Rollback',
  domains: ['devops'],
  text: 'Run helm rollback.',
  score: 0.8,
};

describe('Chat', () => {
  let fixture: ComponentFixture<Chat>;
  let page: HTMLElement;
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(async () => {
    vi.stubGlobal('fetch', fetchMock);
    HTMLDialogElement.prototype.showModal = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: APP_CONFIG, useValue: { apiBaseUrl: 'http://api', phoenixUrl: 'http://px' } },
        { provide: Keycloak, useValue: { token: 'jwt', updateToken: async () => true } },
      ],
    });
    fixture = TestBed.createComponent(Chat);
    page = fixture.nativeElement;
    await fixture.whenStable();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  async function ask(question: string): Promise<void> {
    const input = page.querySelector('input#question') as HTMLInputElement;
    input.value = question;
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    page.querySelector<HTMLButtonElement>('button[type=submit]')?.click();
  }

  it('streams the answer, links citations to their source and the trace to Phoenix', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        `event: sources\ndata: ${JSON.stringify({ sources: [SOURCE] })}\n\n` +
          'event: token\ndata: {"text":"Use **helm** "}\n\n' +
          'event: token\ndata: {"text":"rollback [1]."}\n\n' +
          'event: done\ndata: {"usage":null,"model":"m","traceId":"abc"}\n\n',
      ),
    );

    await ask('How do I roll back?');

    await vi.waitFor(() => expect(page.querySelector('a.citation')).not.toBeNull());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://api/api/chat');
    expect(init?.headers).toMatchObject({ authorization: 'Bearer jwt' });
    expect(JSON.parse(init?.body as string)).toEqual({
      messages: [{ role: 'user', content: 'How do I roll back?' }],
    });
    expect(page.querySelector('.answer')?.innerHTML).toContain('<strong>helm</strong>');
    expect(page.querySelector<HTMLAnchorElement>('a[href^="http://px"]')?.href).toBe(
      'http://px/redirects/traces/abc',
    );

    page.querySelector<HTMLAnchorElement>('a.citation')?.click();
    await fixture.whenStable();
    expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();
    expect(page.querySelector('dialog .source-text')?.textContent).toBe('Run helm rollback.');
  });

  it('shows the problem detail when the API refuses', async () => {
    fetchMock.mockResolvedValue(
      Response.json(
        { status: 429, detail: 'Chat limit of 20 per minute reached' },
        { status: 429 },
      ),
    );

    await ask('Hi');

    await vi.waitFor(() =>
      expect(page.querySelector('[role=alert]')?.textContent).toContain('Chat limit of 20'),
    );
  });

  it('stops the stream and aborts the request', async () => {
    let signal: AbortSignal | undefined;
    fetchMock.mockImplementation(async (_url, init) => {
      signal = init?.signal ?? undefined;
      const body = new ReadableStream({
        start: (controller) =>
          signal?.addEventListener('abort', () => controller.error(signal?.reason)),
      });
      return new Response(body);
    });

    await ask('Hi');
    await vi.waitFor(() => expect(page.querySelector('.btn-outline-danger')).not.toBeNull());
    page.querySelector<HTMLButtonElement>('.btn-outline-danger')?.click();

    await vi.waitFor(() => expect(page.textContent).toContain('Stopped.'));
    expect(signal?.aborted).toBe(true);
  });
});
