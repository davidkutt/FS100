import { CurrencyPipe, DecimalPipe } from '@angular/common';
import { httpResource } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { components } from '@grove/contracts/api';
import { APP_CONFIG } from '../../core/config';
import { problemDetail } from '../../core/problem';

type UserUsageDay = components['schemas']['UserUsageDay'];

/** `GET /api/admin/usage`: LLM spend per user and UTC day (D44), newest first. */
@Component({
  selector: 'app-usage',
  imports: [CurrencyPipe, DecimalPipe, FormsModule],
  templateUrl: './usage.html',
})
export class Usage {
  private readonly api = inject(APP_CONFIG).apiBaseUrl;

  protected readonly user = signal('');
  protected readonly from = signal('');
  protected readonly to = signal('');
  protected readonly rows = httpResource<UserUsageDay[]>(() => {
    const filters = { user: this.user().trim(), from: this.from(), to: this.to() };
    const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
    return { url: `${this.api}/api/admin/usage`, params };
  });
  protected readonly problemDetail = problemDetail;
}
