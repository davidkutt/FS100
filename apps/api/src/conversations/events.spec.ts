import { applyEvent, type Part, sseBlock, sseParser } from './events.js';

describe('sseParser', () => {
  it('emits complete events only, across chunk and multi-byte boundaries', () => {
    const events: [string, string][] = [];
    const parse = sseParser((event, data) => {
      events.push([event, data]);
    });
    const bytes = new TextEncoder().encode(
      ': ping\n\nevent: token\ndata: {"text":"Grüße"}\n\nevent: done\r\ndata: {}\r\n\r\nevent: tok',
    );

    let forwarded = '';
    for (let i = 0; i < bytes.length; i += 5) forwarded += parse(bytes.subarray(i, i + 5));

    expect(events).toEqual([
      ['token', '{"text":"Grüße"}'],
      ['done', '{}'],
    ]);
    expect(forwarded).toBe(
      ': ping\n\nevent: token\ndata: {"text":"Grüße"}\n\nevent: done\r\ndata: {}\n\n',
    );
  });

  it('forwards the block onEvent returns instead of the event', () => {
    const parse = sseParser((event) => (event === 'secret' ? sseBlock('secret', {}) : undefined));

    const forwarded = parse(new TextEncoder().encode('event: secret\ndata: {"key":1}\n\n'));

    expect(forwarded).toBe('event: secret\ndata: {}\n\n');
  });
});

describe('applyEvent', () => {
  it('keeps the arrival order, merges tokens and keeps only the newest sources', () => {
    const parts: Part[] = [];
    const events: [string, Record<string, unknown>][] = [
      ['step', { n: 1 }],
      ['token', { text: 'Let me ' }],
      ['token', { text: 'search.' }],
      ['tool_call', { id: 'c1', name: 'kb.search_knowledge_base', type: 'ignored' }],
      ['tool_result', { id: 'c1', status: 'ok' }],
      ['sources', { sources: [1] }],
      ['tool_result', { id: 'c2', status: 'error' }],
      ['sources', { sources: [1, 2] }],
      ['token', { text: 'Answer [2].' }],
      ['error', { type: 'llm', title: 'LLM request failed', detail: 'timeout' }],
      ['done', { stopReason: 'error' }],
    ];

    for (const [event, data] of events) applyEvent(parts, event, data);

    expect(parts).toEqual([
      { type: 'text', text: 'Let me search.' },
      { type: 'tool_call', id: 'c1', name: 'kb.search_knowledge_base' },
      { type: 'tool_result', id: 'c1', status: 'ok' },
      { type: 'sources', sources: [1, 2] },
      { type: 'tool_result', id: 'c2', status: 'error' },
      { type: 'text', text: 'Answer [2].' },
      { type: 'error', title: 'LLM request failed', detail: 'timeout' },
    ]);
  });
});
