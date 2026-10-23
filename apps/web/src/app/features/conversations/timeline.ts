import { DecimalPipe, JsonPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import type { Part, Route, ToolCall, ToolResult } from './parts';

/** Route and tool activity of one answer; args and results stay collapsed until asked for. */
@Component({
  selector: 'app-timeline',
  imports: [DecimalPipe, JsonPipe],
  template: `
    @if (route(); as route) {
      <p class="route small text-body-secondary mb-1">
        Route
        <span class="badge rounded-pill text-bg-info">{{
          route.domains.length ? route.domains.join(', ') : 'all domains'
        }}</span>
        {{ route.router }} · {{ route.confidence | number: '1.2-2' }}
      </p>
    }
    <ol class="list-unstyled small mb-3">
      @for (call of calls(); track call.id) {
        @let result = results().get(call.id);
        <li class="tool mb-1">
          <details>
            <summary>
              <code>{{ call.name }}</code>
              @if (call.kind === 'write') {
                <span class="badge text-bg-warning ms-1">write</span>
              }
              @if (result) {
                <span
                  class="badge ms-1"
                  [class]="result.status === 'ok' ? 'text-bg-success' : 'text-bg-danger'"
                  >{{ result.status }}</span
                >
                <span class="text-body-secondary ms-1"
                  >{{ result.summary }} · {{ result.durationMs }} ms</span
                >
              } @else if (live()) {
                <span class="spinner-border spinner-border-sm ms-1" aria-hidden="true"></span>
                <span class="text-body-secondary ms-1">running…</span>
              } @else {
                <span class="text-body-secondary ms-1">no result</span>
              }
            </summary>
            <div class="ps-3 pt-1">
              <div class="text-body-secondary">Arguments</div>
              <pre
                class="bg-body-tertiary rounded p-2 mb-2"
              ><code>{{ call.args | json }}</code></pre>
              @if (result) {
                <div class="text-body-secondary">
                  Result{{ result.truncated ? ' (truncated to its budget)' : '' }}
                </div>
                <pre
                  class="bg-body-tertiary rounded p-2 mb-0"
                ><code>{{ result.content }}</code></pre>
              }
            </div>
          </details>
        </li>
      }
    </ol>
  `,
  styles: `
    pre {
      max-height: 16rem;
      white-space: pre-wrap;
    }
  `,
})
export class Timeline {
  readonly parts = input.required<Part[]>();
  /** Calls without a result are still running only while the answer streams. */
  readonly live = input(false);

  protected readonly route = computed(() =>
    this.parts().find((part): part is Route => part.type === 'route'),
  );
  protected readonly calls = computed(() =>
    this.parts().filter((part): part is ToolCall => part.type === 'tool_call'),
  );
  protected readonly results = computed(
    () =>
      new Map(
        this.parts()
          .filter((part): part is ToolResult => part.type === 'tool_result')
          .map((result) => [result.id, result]),
      ),
  );
}
