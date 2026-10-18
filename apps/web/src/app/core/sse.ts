export interface SseEvent {
  event: string;
  data: string;
}

/** Parses a `text/event-stream` body; EventSource can't POST or send headers (D12). */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
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
        if (data.length) yield { event, data: data.join('\n') };
      }
    }
  } finally {
    // Closes the upstream request when the consumer stops early.
    await reader.cancel().catch(() => undefined);
  }
}
