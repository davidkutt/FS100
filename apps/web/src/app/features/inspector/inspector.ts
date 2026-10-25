import { DecimalPipe } from '@angular/common';
import { httpResource } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { components } from '@fs100/contracts/ai-service';
import { APP_CONFIG } from '../../core/config';
import { problemDetail } from '../../core/problem';
import { type Domain, DomainPicker } from '../../shared/domain-picker';

type SearchRequest = components['schemas']['SearchRequest'];
type SearchResponse = components['schemas']['SearchResponse'];

/** Reranked hybrid hits with their ranks via `POST /api/search`, without the chat's threshold. */
@Component({
  selector: 'app-inspector',
  imports: [DecimalPipe, DomainPicker, FormsModule],
  templateUrl: './inspector.html',
})
export class Inspector {
  private readonly api = inject(APP_CONFIG).apiBaseUrl;
  private readonly request = signal<SearchRequest | undefined>(undefined);

  protected readonly query = signal('');
  protected readonly domains = signal<Domain[]>([]);
  protected readonly topK = signal(10);
  // Only for the notice; the chat uses the AI service's RETRIEVAL_SCORE_THRESHOLD (ADR-0004).
  protected readonly threshold = signal(0.55);

  protected readonly results = httpResource<SearchResponse>(() => {
    const body = this.request();
    return body && { url: `${this.api}/api/search`, method: 'POST', body };
  });
  // The chat abstains when even the best hit is below the threshold (ADR-0016).
  protected readonly abstains = computed(
    () =>
      this.results.hasValue() &&
      Math.max(0, ...this.results.value().hits.map((hit) => hit.score)) < this.threshold(),
  );
  protected readonly problemDetail = problemDetail;

  protected search(): void {
    const query = this.query().trim();
    if (!query) return;
    const domains = this.domains();
    this.request.set({
      query,
      top_k: this.topK(),
      domains: domains.length ? domains : null,
      explain: true,
    });
  }
}
