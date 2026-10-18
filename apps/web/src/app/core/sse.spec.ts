import { parseSse, type SseEvent } from './sse';

function stream(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(body: ReadableStream<Uint8Array>): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of parseSse(body)) events.push(event);
  return events;
}

describe('parseSse', () => {
  it('parses events split across chunks, with CRLF, comments and multi-line data', async () => {
    const events = await collect(
      stream(
        ': ping\n\nevent: sour',
        'ces\ndata: {"sources":[]}\r\n\r',
        '\nevent: token\ndata:{"text":"a"}\n\ndata: line 1\ndata: line 2\n\n',
      ),
    );

    expect(events).toEqual([
      { event: 'sources', data: '{"sources":[]}' },
      { event: 'token', data: '{"text":"a"}' },
      { event: 'message', data: 'line 1\nline 2' },
    ]);
  });

  it('drops an unterminated event at the end of the stream', async () => {
    expect(await collect(stream('event: done\ndata: {}'))).toEqual([]);
  });
});
