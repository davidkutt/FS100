import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import Keycloak from 'keycloak-js';
import { APP_CONFIG } from '../../core/config';
import { Conversations } from './conversations';

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
const CALL = { id: 'c1', name: 'kb.search_knowledge_base', kind: 'read', risk: 'low', args: {} };
const RESULT = {
  id: 'c1',
  status: 'ok',
  summary: '1 hits',
  content: '…',
  truncated: false,
  durationMs: 12,
};
const MODELS = [
  { id: 'luna', label: 'Luna', supports_tools: true, tier: 'low', min_role: 'viewer' },
  { id: 'haiku', label: 'Haiku', supports_tools: true, tier: 'medium', min_role: 'editor' },
  { id: 'chatty', label: 'No tools', supports_tools: false, tier: 'low', min_role: 'viewer' },
];
const TODAY = {
  day: '2026-10-22',
  inputTokens: 1000,
  cachedTokens: 0,
  outputTokens: 234,
  costUsd: 0.0012,
  turns: 2,
};
const USAGE = { capUsd: 1, today: TODAY, days: [TODAY] };
const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const message = (id: string, role: string, parts: unknown[], extra = {}) => ({
  id,
  role,
  parts,
  model: null,
  promptVersion: null,
  stopReason: role === 'assistant' ? 'end' : null,
  traceId: role === 'assistant' ? 'abc' : null,
  answerStatus: null,
  topScore: null,
  createdAt: '2026-10-20T10:00:00Z',
  feedback: null,
  ...extra,
});
const detail = (
  id: string,
  messages: unknown[],
  modelId: string | null = null,
  approvals: unknown[] = [],
) => ({
  id,
  title: 'How do I roll back?',
  modelId,
  createdAt: '2026-10-20T10:00:00Z',
  updatedAt: '2026-10-20T10:00:00Z',
  messages,
  approvals,
});
const STORED = [
  message('m1', 'user', [{ type: 'text', text: 'How do I roll back?' }]),
  message('m2', 'assistant', [
    { type: 'tool_call', ...CALL },
    { type: 'tool_result', ...RESULT },
    { type: 'sources', sources: [SOURCE] },
    { type: 'text', text: 'Use **helm** rollback [1].' },
  ]),
];

describe('Conversations', () => {
  let fixture: ComponentFixture<Conversations>;
  let page: HTMLElement;
  let http: HttpTestingController;
  const fetchMock = vi.fn<typeof fetch>();

  async function render(id?: string, pending: unknown[] = []): Promise<void> {
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('confirm', () => true);
    HTMLDialogElement.prototype.showModal = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: APP_CONFIG, useValue: { apiBaseUrl: 'http://api', phoenixUrl: 'http://px' } },
        {
          provide: Keycloak,
          useValue: { token: 'jwt', subject: 'u1', updateToken: async () => true },
        },
      ],
    });
    fixture = TestBed.createComponent(Conversations);
    // The route param, as `withComponentInputBinding` sets it after a navigation.
    vi.spyOn(TestBed.inject(Router), 'navigate').mockImplementation(async (commands) => {
      fixture.componentRef.setInput('id', commands[1]);
      return true;
    });
    if (id) fixture.componentRef.setInput('id', id);
    page = fixture.nativeElement;
    http = TestBed.inject(HttpTestingController);
    TestBed.tick();
    http.expectOne('http://api/api/conversations').flush([]);
    http.expectOne('http://api/api/me/usage').flush(USAGE);
    http.expectOne('http://api/api/approvals?status=pending').flush(pending);
    http.expectOne('http://api/api/models').flush(MODELS);
    await fixture.whenStable();
  }

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

  it('a first question creates the conversation, streams the tool timeline, then shows the stored turn', async () => {
    await render();
    expect(Array.from(page.querySelectorAll('#model option')).map((o) => o.textContent)).toEqual([
      'Luna · low',
      'Haiku · medium',
    ]);
    expect(page.textContent).toContain('Today: $0.0012 of $1.00 · 1,234 tokens · 2 turns');
    fetchMock.mockResolvedValue(
      new Response(
        sse('step', { n: 1 }) +
          sse('tool_call', CALL) +
          sse('tool_result', RESULT) +
          sse('sources', { sources: [SOURCE] }) +
          sse('token', { text: 'Use **helm** ' }) +
          sse('token', { text: 'rollback [1].' }) +
          sse('done', { stopReason: 'end', traceId: 'abc' }),
      ),
    );

    await ask('How do I roll back?');
    http.expectOne({ method: 'POST', url: 'http://api/api/conversations' }).flush(detail('c1', []));
    await vi.waitFor(() =>
      http.expectOne('http://api/api/conversations/c1').flush(detail('c1', STORED)),
    );
    // The stored copy replaces the live turn: only stored messages can be rated.
    await vi.waitFor(() => expect(page.querySelector('button[aria-label=Helpful]')).not.toBeNull());
    http.expectOne('http://api/api/conversations').flush([detail('c1', [])]); // sidebar refresh
    http.expectOne('http://api/api/me/usage').flush(USAGE);
    http.expectOne('http://api/api/approvals?status=pending').flush([]);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://api/api/conversations/c1/messages');
    expect(init?.headers).toMatchObject({ authorization: 'Bearer jwt' });
    expect(JSON.parse(init?.body as string)).toEqual({
      text: 'How do I roll back?',
      modelId: 'luna',
    });
    expect(page.querySelector('app-timeline summary')?.textContent).toContain('1 hits · 12 ms');
    expect(page.querySelector('.answer')?.innerHTML).toContain('<strong>helm</strong>');
    expect(page.querySelectorAll('.user-turn')).toHaveLength(1);
    expect(page.querySelector<HTMLAnchorElement>('a[href^="http://px"]')?.href).toBe(
      'http://px/redirects/traces/abc',
    );
    page.querySelector<HTMLAnchorElement>('a.citation')?.click();
    await fixture.whenStable();
    expect(page.querySelector('dialog .source-text')?.textContent).toBe('Run helm rollback.');
  });

  it('opens a stored conversation with its model and rates an answer', async () => {
    await render('c2');
    http.expectOne('http://api/api/conversations/c2').flush(detail('c2', STORED, 'haiku'));
    await vi.waitFor(() => expect(page.querySelectorAll('.user-turn')).toHaveLength(1));
    expect(page.querySelector<HTMLSelectElement>('#model')?.value).toBe('haiku');

    page.querySelector<HTMLButtonElement>('button[aria-label="Not helpful"]')!.click();
    await fixture.whenStable();
    const comment = page.querySelector<HTMLInputElement>('input[id="comment-m2"]')!;
    comment.value = 'Wrong runbook';
    page.querySelector<HTMLButtonElement>('form button[type=submit]:not(.btn-primary)')!.click();

    const rating = http.expectOne('http://api/api/messages/m2/feedback');
    expect(rating.request.body).toEqual({ rating: 'down', comment: 'Wrong runbook' });
    rating.flush(null);
    await fixture.whenStable();
    expect(
      page.querySelector('button[aria-label="Not helpful"]')?.getAttribute('aria-pressed'),
    ).toBe('true');
  });

  it('shows the problem detail when the API refuses', async () => {
    await render('c3');
    http.expectOne('http://api/api/conversations/c3').flush(detail('c3', []));
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

  it('shows a proposed write with args, risk and time left; approving streams the rest', async () => {
    const expiresAt = new Date(Date.now() + 5 * 60_000).toISOString();
    const proposal = {
      approvalId: 'a1',
      callId: 'w1',
      tool: 'github_sandbox.create_issue',
      args: { title: 'Flaky test' },
      risk: 'medium',
      expiresAt,
    };
    const approval = {
      ...proposal,
      id: 'a1',
      conversationId: 'c5',
      messageId: 'm2',
      requesterId: 'u1',
      status: 'pending',
      note: null,
      error: null,
      createdAt: '2026-10-20T10:00:00Z',
      decidedAt: null,
      executedAt: null,
    };
    const call = {
      type: 'tool_call',
      id: 'w1',
      name: proposal.tool,
      kind: 'write',
      risk: 'medium',
    };
    const stored = [
      message('m1', 'user', [{ type: 'text', text: 'Open an issue' }]),
      message('m2', 'assistant', [
        { ...call, args: proposal.args },
        { type: 'approval_required', ...proposal },
      ]),
    ];
    await render('c5', [approval, { ...approval, id: 'a2', requesterId: 'someone-else' }]);
    http.expectOne('http://api/api/conversations/c5').flush(detail('c5', stored, null, [approval]));
    await vi.waitFor(() => expect(page.querySelector('app-approval button')).not.toBeNull());

    const card = page.querySelector('app-approval')!;
    expect(card.querySelector('pre')?.textContent).toContain('"title": "Flaky test"');
    expect(card.textContent).toMatch(/medium risk[\s\S]*Expires in [45]:\d\d/);
    expect(page.querySelectorAll('nav[aria-label=Conversations] code')).toHaveLength(1);
    fetchMock.mockResolvedValue(
      new Response(
        sse('tool_call', { ...call, args: proposal.args }) +
          sse('tool_result', { ...RESULT, id: 'w1', summary: 'created #7' }) +
          sse('token', { text: 'Created #7.' }) +
          sse('done', { stopReason: 'end' }),
      ),
    );
    card.querySelector('input')!.value = 'Looks right';
    card.querySelector<HTMLButtonElement>('button.btn-success')!.click();

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://api/api/approvals/a1');
    expect(JSON.parse(init?.body as string)).toEqual({ decision: 'approve', note: 'Looks right' });
    await vi.waitFor(() =>
      http
        .expectOne('http://api/api/conversations/c5')
        .flush(detail('c5', stored, null, [{ ...approval, status: 'succeeded' }])),
    );
    await vi.waitFor(() => expect(card.textContent).toContain('Approved and done.'));
    expect(card.querySelector('button')).toBeNull();
  });

  it('stops the stream, aborts the request and keeps the partial answer', async () => {
    await render('c4');
    http.expectOne('http://api/api/conversations/c4').flush(detail('c4', []));
    let signal: AbortSignal | undefined;
    fetchMock.mockImplementation(async (_url, init) => {
      signal = init?.signal ?? undefined;
      const body = new ReadableStream({
        start: (controller) => {
          controller.enqueue(new TextEncoder().encode(sse('token', { text: 'Partial' })));
          signal?.addEventListener('abort', () => controller.error(signal?.reason));
        },
      });
      return new Response(body);
    });

    await ask('Hi');
    await vi.waitFor(() => expect(page.querySelector('.answer')?.textContent).toContain('Partial'));
    page.querySelector<HTMLButtonElement>('button.btn-outline-danger:not([disabled])')?.click();

    await vi.waitFor(() => expect(page.textContent).toContain('Stopped.'));
    expect(signal?.aborted).toBe(true);
    expect(page.querySelector('.answer')?.textContent).toContain('Partial');
  });
});
