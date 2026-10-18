import { HttpErrorResponse } from '@angular/common/http';

/** The API answers errors as RFC 9457 problem+json (plan.md §7.2). */
export function problemDetail(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    return error.error?.detail ?? error.error?.title ?? error.message;
  }
  return error instanceof Error ? error.message : String(error);
}
