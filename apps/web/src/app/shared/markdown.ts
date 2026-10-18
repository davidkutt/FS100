import { Pipe, type PipeTransform } from '@angular/core';
import { Marked } from 'marked';

const markdown = new Marked({
  extensions: [
    {
      // `[n]` → a link the chat turns into a source panel; `[n](url)` stays a normal link.
      name: 'citation',
      level: 'inline',
      start: (src) => src.indexOf('['),
      tokenizer: (src) => {
        const match = /^\[(\d+)\](?!\()/.exec(src);
        return match ? { type: 'citation', raw: match[0], n: match[1] } : undefined;
      },
      renderer: (token) => `<a href="#source-${token['n']}" class="citation">[${token['n']}]</a>`,
    },
  ],
});

/** Markdown → HTML. Bind it with `[innerHTML]`, whose sanitizer strips scripts and handlers (D16). */
@Pipe({ name: 'markdown' })
export class MarkdownPipe implements PipeTransform {
  transform(text: string): string {
    return markdown.parse(text, { async: false });
  }
}
