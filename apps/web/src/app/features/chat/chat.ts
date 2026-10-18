import { Component, DestroyRef, ElementRef, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { components } from '@fs100/contracts/ai-service';
import Keycloak from 'keycloak-js';
import { APP_CONFIG } from '../../core/config';
import { parseSse } from '../../core/sse';
import { type Domain, DomainPicker } from '../../shared/domain-picker';
import { MarkdownPipe } from '../../shared/markdown';

type Schemas = components['schemas'];
type Source = Schemas['Source'];

interface Turn {
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  traceId?: string | null;
  error?: string;
  stopped?: boolean;
}

/** Grounded chat: streams `POST /api/chat` (plan.md §7.3); history lives only in this page. */
@Component({
  selector: 'app-chat',
  imports: [DomainPicker, FormsModule, MarkdownPipe],
  templateUrl: './chat.html',
  styleUrl: './chat.scss',
})
export class Chat {
  private readonly config = inject(APP_CONFIG);
  private readonly keycloak = inject(Keycloak);
  private abort?: AbortController;

  protected readonly phoenixUrl = this.config.phoenixUrl;
  protected readonly turns = signal<Turn[]>([]);
  protected readonly question = signal('');
  protected readonly domains = signal<Domain[]>([]);
  protected readonly busy = signal(false);
  protected readonly source = signal<Source | undefined>(undefined);

  private readonly input = viewChild.required<ElementRef<HTMLInputElement>>('input');
  private readonly panel = viewChild.required<ElementRef<HTMLDialogElement>>('panel');

  constructor() {
    // Leaving the page must not keep an LLM call running (D24).
    inject(DestroyRef).onDestroy(() => this.abort?.abort());
  }

  protected async send(): Promise<void> {
    const question = this.question().trim();
    if (!question || this.busy()) return;
    const messages = [...this.turns(), { role: 'user', content: question } as const]
      .filter((turn) => turn.content)
      .map(({ role, content }) => ({ role, content }));
    this.turns.update((turns) => [
      ...turns,
      { role: 'user', content: question },
      { role: 'assistant', content: '' },
    ]);
    this.question.set('');
    this.input().nativeElement.focus();
    this.busy.set(true);
    const abort = (this.abort = new AbortController());
    try {
      await this.keycloak.updateToken(30);
      const res = await fetch(`${this.config.apiBaseUrl}/api/chat`, {
        method: 'POST',
        signal: abort.signal,
        headers: {
          'content-type': 'application/json',
          authorization: `Bearer ${this.keycloak.token}`,
        },
        body: JSON.stringify({
          messages,
          domains: this.domains().length ? this.domains() : undefined,
        }),
      });
      if (!res.ok || !res.body) {
        const problem = await res.json().catch(() => ({}));
        throw new Error(problem.detail ?? problem.title ?? `Chat failed (${res.status})`);
      }
      for await (const { event, data } of parseSse(res.body)) {
        const payload = JSON.parse(data);
        if (event === 'sources')
          this.patch({ sources: (payload as Schemas['SourcesEvent']).sources });
        else if (event === 'token') this.patch((t) => ({ content: t.content + payload.text }));
        else if (event === 'done')
          this.patch({ traceId: (payload as Schemas['DoneEvent']).traceId });
        else if (event === 'error') {
          const error = payload as Schemas['ErrorEvent'];
          this.patch({ error: error.detail || error.title });
        }
      }
    } catch (error) {
      if (abort.signal.aborted) this.patch({ stopped: true });
      else this.patch({ error: error instanceof Error ? error.message : String(error) });
    } finally {
      this.busy.set(false);
    }
  }

  protected stop(): void {
    this.abort?.abort();
    this.input().nativeElement.focus();
  }

  /** Delegated from the rendered answer: citations are `<a href="#source-n">`, so keyboard works. */
  protected cite(event: Event, turn: Turn): void {
    const link = (event.target as Element).closest('a.citation');
    if (!link) return;
    event.preventDefault();
    const n = Number(link.getAttribute('href')?.replace('#source-', ''));
    const source = turn.sources?.find((s) => s.n === n);
    if (source) this.show(source);
  }

  protected show(source: Source): void {
    this.source.set(source);
    this.panel().nativeElement.showModal();
  }

  private patch(change: Partial<Turn> | ((turn: Turn) => Partial<Turn>)): void {
    this.turns.update((turns) => {
      const last = turns[turns.length - 1];
      return [
        ...turns.slice(0, -1),
        { ...last, ...(typeof change === 'function' ? change(last) : change) },
      ];
    });
  }
}
