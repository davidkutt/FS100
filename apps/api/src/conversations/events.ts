import type { components } from '@fs100/contracts/ai-service';

/** An SSE v2 payload under its event name as `type`; `token`s merge into `text` parts. */
export type Part = { type: string; [field: string]: unknown };
export type DoneEvent = components['schemas']['AgentDoneEvent'];

/** Push-style `text/event-stream` parser for a relayed body; calls `onEvent` per complete event. */
export function sseParser(
  onEvent: (event: string, data: string) => void,
): (chunk: Uint8Array) => void {
  const decoder = new TextDecoder();
  let buffer = '';
  return (chunk) => {
    buffer += decoder.decode(chunk, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? '';
    for (const block of blocks) {
      let event = 'message';
      const data: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        const colon = line.indexOf(':');
        if (colon === 0) continue;
        const field = colon < 0 ? line : line.slice(0, colon);
        const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
        if (field === 'event') event = value;
        else if (field === 'data') data.push(value);
      }
      if (data.length) onEvent(event, data.join('\n'));
    }
  };
}

/** Folds one event into a message's parts, in arrival order (D42). */
export function applyEvent(parts: Part[], event: string, data: Record<string, unknown>): void {
  const last = parts.at(-1);
  if (event === 'token') {
    if (last?.type === 'text') last.text = `${last.text as string}${data.text as string}`;
    else parts.push({ type: 'text', text: data.text });
  } else if (event === 'sources') {
    // Cumulative with stable numbers: the newest event replaces the older one.
    const index = parts.findIndex((part) => part.type === 'sources');
    if (index < 0) parts.push({ type: 'sources', ...data });
    else parts[index] = { type: 'sources', ...data };
  } else if (event === 'error') {
    parts.push({ type: 'error', title: data.title, detail: data.detail });
  } else if (event !== 'step' && event !== 'done') {
    parts.push({ ...data, type: event });
  }
}
