import { CurrencyPipe, DecimalPipe } from '@angular/common';
import { HttpClient, httpResource } from '@angular/common/http';
import {
  Component,
  computed,
  DestroyRef,
  effect,
  ElementRef,
  inject,
  input,
  linkedSignal,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import type { components as Ai } from '@fs100/contracts/ai-service';
import type { components as Api } from '@fs100/contracts/api';
import Keycloak from 'keycloak-js';
import { firstValueFrom } from 'rxjs';
import { APP_CONFIG } from '../../core/config';
import { problemDetail } from '../../core/problem';
import { parseSse } from '../../core/sse';
import { DomainPicker } from '../../shared/domain-picker';
import { MarkdownPipe } from '../../shared/markdown';
import {
  answerOf,
  applyEvent,
  errorOf,
  type Part,
  type Source,
  sourcesOf,
  type Turn,
} from './parts';
import { Timeline } from './timeline';

type Schemas = Api['schemas'];

/** Agent chat over stored conversations: `POST /api/conversations/:id/messages` streams SSE v2. */
@Component({
  selector: 'app-conversations',
  imports: [
    CurrencyPipe,
    DecimalPipe,
    DomainPicker,
    FormsModule,
    MarkdownPipe,
    RouterLink,
    Timeline,
  ],
  templateUrl: './conversations.html',
  styleUrl: './conversations.scss',
})
export class Conversations {
  private readonly api = inject(APP_CONFIG).apiBaseUrl;
  private readonly http = inject(HttpClient);
  private readonly keycloak = inject(Keycloak);
  private readonly router = inject(Router);
  private abort?: AbortController;
  /** The conversation on screen; the route change after creating one must not reload it. */
  private shown?: string;

  /** Route parameter; empty on `/chat` until the first question creates a conversation. */
  readonly id = input<string>();

  protected readonly phoenixUrl = inject(APP_CONFIG).phoenixUrl;
  protected readonly list = httpResource<Schemas['Conversation'][]>(
    () => `${this.api}/api/conversations`,
  );
  protected readonly usage = httpResource<Schemas['UsageToday']>(() => `${this.api}/api/me/usage`);
  private readonly models = httpResource<Ai['schemas']['ModelInfo'][]>(
    () => `${this.api}/api/models`,
  );
  /** Agent mode needs tool calls (D40). */
  protected readonly toolModels = computed(() =>
    (this.models.hasValue() ? this.models.value() : []).filter((model) => model.supports_tools),
  );
  private readonly storedModel = signal<string | null>(null);
  protected readonly modelId = linkedSignal(
    () => this.storedModel() ?? this.toolModels()[0]?.id ?? '',
  );

  protected readonly messages = signal<Turn[]>([]);
  protected readonly live = signal<Turn[]>([]);
  protected readonly turns = computed(() => [...this.messages(), ...this.live()]);
  protected readonly loadError = signal('');
  protected readonly question = signal('');
  protected readonly domains = signal<string[]>([]);
  protected readonly busy = signal(false);
  protected readonly source = signal<Source | undefined>(undefined);
  protected readonly commenting = signal<string | undefined>(undefined);

  protected readonly answerOf = answerOf;
  protected readonly sourcesOf = sourcesOf;
  protected readonly errorOf = errorOf;

  private readonly input = viewChild.required<ElementRef<HTMLInputElement>>('input');
  private readonly panel = viewChild.required<ElementRef<HTMLDialogElement>>('panel');

  constructor() {
    // Leaving the page must not keep an LLM call running (D24).
    inject(DestroyRef).onDestroy(() => this.abort?.abort());
    effect(() => {
      const id = this.id();
      untracked(() => {
        if (id === this.shown) return;
        this.shown = id;
        this.abort?.abort();
        this.messages.set([]);
        this.live.set([]);
        this.storedModel.set(null);
        this.loadError.set('');
        if (id) void this.open(id);
      });
    });
  }

  protected async send(): Promise<void> {
    const text = this.question().trim();
    if (!text || this.busy()) return;
    // A stopped or failed turn stays visible; the next reload brings the stored copy.
    this.messages.update((messages) => [...messages, ...this.live()]);
    this.live.set([
      { role: 'user', parts: [{ type: 'text', text }] },
      { role: 'assistant', parts: [] },
    ]);
    this.question.set('');
    this.input().nativeElement.focus();
    this.busy.set(true);
    const abort = (this.abort = new AbortController());
    let id = this.id();
    let streamed = false;
    try {
      if (!id) {
        const created = this.http.post<Schemas['Conversation']>(
          `${this.api}/api/conversations`,
          {},
        );
        id = this.shown = (await firstValueFrom(created)).id;
        await this.router.navigate(['/chat', id], { replaceUrl: true });
      }
      await this.keycloak.updateToken(30);
      const res = await fetch(`${this.api}/api/conversations/${id}/messages`, {
        method: 'POST',
        signal: abort.signal,
        headers: {
          'content-type': 'application/json',
          authorization: `Bearer ${this.keycloak.token}`,
        },
        body: JSON.stringify({
          text,
          modelId: this.modelId() || undefined,
          domains: this.domains().length ? this.domains() : undefined,
        }),
      });
      if (!res.ok || !res.body) {
        const problem = await res.json().catch(() => ({}));
        throw new Error(problem.detail ?? problem.title ?? `Chat failed (${res.status})`);
      }
      streamed = true;
      for await (const { event, data } of parseSse(res.body)) {
        const payload = JSON.parse(data);
        this.patch((turn) => ({
          parts: applyEvent(turn.parts, event, payload),
          ...(event === 'done' && { stopReason: payload.stopReason, traceId: payload.traceId }),
        }));
      }
    } catch (error) {
      streamed = false;
      if (abort.signal.aborted) this.patch(() => ({ stopReason: 'cancelled' }));
      else this.patch(() => ({ error: problemDetail(error) }));
    } finally {
      this.busy.set(false);
      if (streamed && id && id === this.id()) await this.open(id);
      this.list.reload();
      this.usage.reload();
    }
  }

  protected stop(): void {
    this.abort?.abort();
    this.input().nativeElement.focus();
  }

  protected async remove(): Promise<void> {
    const id = this.id();
    if (!id || !confirm('Delete this conversation?')) return;
    try {
      await firstValueFrom(this.http.delete(`${this.api}/api/conversations/${id}`));
      this.list.reload();
      await this.router.navigate(['/chat']);
    } catch (error) {
      this.loadError.set(problemDetail(error));
    }
  }

  protected async rate(turn: Turn, rating: 'up' | 'down', comment?: string): Promise<void> {
    const feedback = { rating, comment: comment?.trim() || undefined };
    this.commenting.set(undefined);
    try {
      await firstValueFrom(
        this.http.post(`${this.api}/api/messages/${turn.id}/feedback`, feedback),
      );
      this.messages.update((messages) =>
        messages.map((m) => (m.id === turn.id ? { ...m, feedback } : m)),
      );
    } catch (error) {
      this.loadError.set(problemDetail(error));
    }
  }

  /** Delegated from the rendered answer: citations are `<a href="#source-n">`, so keyboard works. */
  protected cite(event: Event, turn: Turn): void {
    const link = (event.target as Element).closest('a.citation');
    if (!link) return;
    event.preventDefault();
    const n = Number(link.getAttribute('href')?.replace('#source-', ''));
    const source = sourcesOf(turn.parts).find((s) => s.n === n);
    if (source) this.show(source);
  }

  protected show(source: Source): void {
    this.source.set(source);
    this.panel().nativeElement.showModal();
  }

  private async open(id: string): Promise<void> {
    try {
      const url = `${this.api}/api/conversations/${id}`;
      const detail = await firstValueFrom(this.http.get<Schemas['ConversationDetail']>(url));
      if (id !== this.id()) return; // another conversation was opened meanwhile
      this.messages.set(detail.messages.map((m) => ({ ...m, parts: m.parts as Part[] })));
      this.live.set([]);
      this.storedModel.set(detail.modelId);
    } catch (error) {
      this.loadError.set(problemDetail(error));
    }
  }

  private patch(change: (turn: Turn) => Partial<Turn>): void {
    this.live.update((turns) => {
      const last = turns.at(-1);
      if (!last) return turns; // another conversation was opened mid-stream
      return [...turns.slice(0, -1), { ...last, ...change(last) }];
    });
  }
}
