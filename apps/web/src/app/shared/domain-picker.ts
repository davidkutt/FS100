import { Component, input, model } from '@angular/core';
import type { components } from '@grove/contracts/api';

export type Domain = components['schemas']['Document']['domains'][number];

/** The D22 taxonomy; the API rejects anything else. */
export const DOMAINS = [
  'db',
  'dev',
  'cloud',
  'devops',
  'mlops',
  'ai',
  'security',
  'architecture',
  'sre',
] as const satisfies readonly Domain[];

let nextId = 0;

/** Toggle buttons for taxonomy labels: the domains, or with `options` the `domain/topic` ids. */
@Component({
  selector: 'app-domain-picker',
  template: `
    <fieldset>
      <legend class="form-label fs-6 mb-1">{{ label() }}</legend>
      @for (domain of options(); track domain) {
        <input
          type="checkbox"
          class="btn-check"
          [id]="id + domain"
          [checked]="value().includes(domain)"
          (change)="toggle(domain)"
        />
        <label class="btn btn-sm btn-outline-primary me-1 mb-1" [for]="id + domain">
          {{ domain }}
        </label>
      }
    </fieldset>
  `,
})
export class DomainPicker {
  readonly label = input.required<string>();
  readonly options = input<readonly string[]>(DOMAINS);
  readonly value = model<string[]>([]);

  protected readonly id = `domain-${nextId++}-`;

  protected toggle(domain: string): void {
    this.value.update((v) => (v.includes(domain) ? v.filter((d) => d !== domain) : [...v, domain]));
  }
}
