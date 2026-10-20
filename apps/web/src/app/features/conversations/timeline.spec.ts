import { TestBed } from '@angular/core/testing';
import type { Part } from './parts';
import { Timeline } from './timeline';

const call = (id: string, name: string) =>
  ({ type: 'tool_call', id, name, kind: 'read', risk: 'low', args: { query: 'rollback' } }) as Part;

describe('Timeline', () => {
  async function render(parts: Part[], live = false): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(Timeline);
    fixture.componentRef.setInput('parts', parts);
    fixture.componentRef.setInput('live', live);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('shows each call with status, summary and duration; args and result collapsed', async () => {
    const page = await render([
      { type: 'text', text: 'ignored' },
      call('c1', 'kb.search_knowledge_base'),
      {
        type: 'tool_result',
        id: 'c1',
        status: 'error',
        summary: 'Timed out',
        content: '<tool_result>Error</tool_result>',
        truncated: true,
        durationMs: 412,
      } as Part,
    ]);

    const item = page.querySelector('li.tool details')!;
    expect(page.querySelectorAll('li.tool')).toHaveLength(1);
    expect(item.hasAttribute('open')).toBe(false);
    expect(item.querySelector('summary')?.textContent).toMatch(
      /kb\.search_knowledge_base\s*error\s*Timed out · 412 ms/,
    );
    expect(item.textContent).toContain('"query": "rollback"');
    expect(item.textContent).toContain('truncated to its budget');
  });

  it('marks calls without a result as running only while the answer streams', async () => {
    const parts = [call('c1', 'kb.search_knowledge_base')];

    expect((await render(parts, true)).textContent).toContain('running…');
    expect((await render(parts)).textContent).toContain('no result');
  });
});
