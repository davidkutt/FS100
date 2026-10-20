import { answerOf, applyEvent, errorOf, type Part, sourcesOf } from './parts';

const SOURCE = { n: 1, title: 'Runbook' };

describe('applyEvent', () => {
  it('folds SSE v2 events into parts like the API stores them', () => {
    const events: [string, Record<string, unknown>][] = [
      ['step', { n: 1 }],
      ['token', { text: 'Let me ' }],
      ['token', { text: 'search.' }],
      ['tool_call', { id: 'c1', name: 'kb.search_knowledge_base' }],
      ['tool_result', { id: 'c1', status: 'ok' }],
      ['sources', { sources: [SOURCE] }],
      ['sources', { sources: [SOURCE, { ...SOURCE, n: 2 }] }],
      ['token', { text: 'Answer [2].' }],
      ['error', { type: 'llm', title: 'LLM request failed', detail: 'timeout' }],
      ['done', { stopReason: 'error' }],
    ];

    const parts = events.reduce<Part[]>((acc, [event, data]) => applyEvent(acc, event, data), []);

    expect(parts.map((part) => part.type)).toEqual([
      'text',
      'tool_call',
      'tool_result',
      'sources',
      'text',
      'error',
    ]);
    expect(answerOf(parts)).toBe('Let me search.\n\nAnswer [2].');
    expect(sourcesOf(parts).map((source) => source.n)).toEqual([1, 2]);
    expect(errorOf(parts)).toBe('timeout');
  });

  it('never mutates the parts it is given (signals compare by reference)', () => {
    const parts: Part[] = [{ type: 'text', text: 'a' }];

    const next = applyEvent(parts, 'token', { text: 'b' });

    expect(parts).toEqual([{ type: 'text', text: 'a' }]);
    expect(next).toEqual([{ type: 'text', text: 'ab' }]);
  });
});
