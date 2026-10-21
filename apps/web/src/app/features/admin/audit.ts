import { DatePipe, JsonPipe } from '@angular/common';
import { httpResource } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { components } from '@fs100/contracts/api';
import { APP_CONFIG } from '../../core/config';
import { problemDetail } from '../../core/problem';

type AuditEntry = components['schemas']['AuditEntry'];

/** `GET /api/admin/audit`: every tool call, newest first (D42). */
@Component({
  selector: 'app-audit',
  imports: [DatePipe, FormsModule, JsonPipe],
  templateUrl: './audit.html',
})
export class Audit {
  private readonly api = inject(APP_CONFIG).apiBaseUrl;

  protected readonly phoenixUrl = inject(APP_CONFIG).phoenixUrl;
  protected readonly user = signal('');
  protected readonly tool = signal('');
  protected readonly outcome = signal('');
  protected readonly from = signal('');
  protected readonly to = signal('');
  protected readonly outcomes = ['ok', 'error', 'denied', 'rejected', 'failed', 'unknown'];
  protected readonly entries = httpResource<AuditEntry[]>(() => {
    const filters = {
      user: this.user().trim(),
      tool: this.tool().trim(),
      outcome: this.outcome(),
      from: this.from(),
      to: this.to(),
    };
    const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
    return { url: `${this.api}/api/admin/audit`, params };
  });
  protected readonly problemDetail = problemDetail;
}
