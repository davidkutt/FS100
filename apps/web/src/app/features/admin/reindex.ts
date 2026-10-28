import { DecimalPipe } from '@angular/common';
import { HttpClient, httpResource } from '@angular/common/http';
import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { components } from '@grove/contracts/ai-service';
import { firstValueFrom } from 'rxjs';
import { APP_CONFIG } from '../../core/config';
import { problemDetail } from '../../core/problem';

type ReindexStatus = components['schemas']['ReindexStatus'];
type ReindexReport = components['schemas']['ReindexReport'];

/** `/api/admin/reindex`: build from the stored originals, gate, swap or roll back (D55). */
@Component({
  selector: 'app-reindex',
  imports: [DecimalPipe, FormsModule],
  templateUrl: './reindex.html',
})
export class Reindex {
  private readonly api = inject(APP_CONFIG).apiBaseUrl;
  private readonly http = inject(HttpClient);

  protected readonly status = httpResource<ReindexStatus>(() => `${this.api}/api/admin/reindex`);
  protected readonly reason = signal('');
  protected readonly force = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly metrics = ['hit@5', 'mrr@10', 'ndcg@10', 'abstention'];
  protected readonly decisionBadge: Record<ReindexReport['decision'], string> = {
    swapped: 'text-bg-success',
    forced: 'text-bg-warning',
    kept: 'text-bg-secondary',
  };
  protected readonly problemDetail = problemDetail;

  constructor() {
    // A run is a job: poll while one is in work.
    effect((onCleanup) => {
      const runs = this.status.hasValue() ? this.status.value().runs : [];
      if (runs.every((run) => ['ready', 'failed', 'cancelled'].includes(run.state))) return;
      const timer = setTimeout(() => this.status.reload(), 2000);
      onCleanup(() => clearTimeout(timer));
    });
  }

  protected start(): Promise<void> {
    return this.post('/api/admin/reindex', { reason: this.reason().trim(), force: this.force() });
  }

  protected rollback(): Promise<void> {
    if (!confirm('Point the alias back at the collection the last swap replaced?')) {
      return Promise.resolve();
    }
    return this.post('/api/admin/reindex/rollback', {});
  }

  /** `test` candidate − live, the numbers the gate compares. */
  protected delta(report: ReindexReport, metric: string): number | undefined {
    const { candidate, live } = report.metrics['test'] ?? {};
    return candidate?.[metric] !== undefined && live?.[metric] !== undefined
      ? candidate[metric] - live[metric]
      : undefined;
  }

  private async post(path: string, body: object): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await firstValueFrom(this.http.post(`${this.api}${path}`, body));
    } catch (error) {
      this.error.set(problemDetail(error));
    }
    this.busy.set(false);
    this.status.reload();
  }
}
