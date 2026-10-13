import { randomUUID } from 'node:crypto';

export const REQUEST_ID_HEADER = 'x-request-id';

// Accept ids from upstream callers only if they are short and log-safe; otherwise mint a new one.
const SAFE_REQUEST_ID = /^[A-Za-z0-9._:-]{1,128}$/;

export function requestIdFrom(header: string | string[] | undefined): string {
  const value = Array.isArray(header) ? header[0] : header;
  return value !== undefined && SAFE_REQUEST_ID.test(value) ? value : randomUUID();
}
