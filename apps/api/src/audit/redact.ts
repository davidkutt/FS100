const SECRET = /pass(word)?|secret|token|api[_-]?key|authorization|cookie|credential/i;
const MAX_CHARS = 200;

/** Audit args keep their shape, but no secrets and no long content such as issue bodies (D42). */
export function redact(value: unknown, key = ''): unknown {
  if (SECRET.test(key)) return '[redacted]';
  if (typeof value === 'string') {
    return value.length > MAX_CHARS ? `${value.slice(0, MAX_CHARS)}…` : value;
  }
  if (Array.isArray(value)) return value.map((item) => redact(item));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redact(v, k)]));
  }
  return value;
}
