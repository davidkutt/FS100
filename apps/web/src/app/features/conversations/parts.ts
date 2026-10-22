import type { components as Ai } from '@fs100/contracts/ai-service';
import type { components as Api } from '@fs100/contracts/api';

type Events = Ai['schemas'];
export type ToolCall = { type: 'tool_call' } & Events['ToolCallEvent'];
export type ToolResult = { type: 'tool_result' } & Events['ToolResultEvent'];
export type Source = Events['Source'];
export type Route = { type: 'route' } & Events['RouteEvent'];
/** The API strips `signedAction` (D29). */
export type Proposal = { type: 'approval_required' } & Omit<
  Events['ApprovalRequiredEvent'],
  'signedAction'
>;

/** SSE v2 payloads under their event name, as the API stores them (`Message.parts`). */
export type Part =
  | { type: 'text'; text: string }
  | Route
  | ToolCall
  | ToolResult
  | ({ type: 'sources' } & Events['SourcesEvent'])
  | Proposal
  | { type: 'error'; title: string; detail: string };

/** A stored message, or the turn still streaming (no id yet). */
export type Turn = Omit<Partial<Api['schemas']['Message']>, 'parts'> & {
  role: 'user' | 'assistant';
  parts: Part[];
  error?: string;
};

/** Same folding as the API's event tee, so a live turn looks like its stored copy. */
export function applyEvent(parts: Part[], event: string, data: Record<string, unknown>): Part[] {
  const last = parts.at(-1);
  if (event === 'token') {
    return last?.type === 'text'
      ? [...parts.slice(0, -1), { ...last, text: last.text + (data['text'] as string) }]
      : [...parts, { type: 'text', text: data['text'] as string }];
  }
  if (event === 'sources') {
    // Cumulative with stable numbers: the newest event replaces the older one.
    const sources = { type: 'sources', ...data } as Part;
    const index = parts.findIndex((part) => part.type === 'sources');
    return index < 0 ? [...parts, sources] : parts.map((part, i) => (i === index ? sources : part));
  }
  if (event === 'error') {
    return [...parts, { type: 'error', title: data['title'], detail: data['detail'] } as Part];
  }
  if (event === 'step' || event === 'done') return parts;
  return [...parts, { ...data, type: event } as Part];
}

export const answerOf = (parts: Part[]): string =>
  parts.flatMap((part) => (part.type === 'text' ? [part.text] : [])).join('\n\n');

export const sourcesOf = (parts: Part[]): Source[] =>
  parts.flatMap((part) => (part.type === 'sources' ? part.sources : []));

export const proposalsOf = (parts: Part[]): Proposal[] =>
  parts.filter((part): part is Proposal => part.type === 'approval_required');

export const errorOf = (parts: Part[]): string | undefined =>
  parts.flatMap((part) => (part.type === 'error' ? [part.detail || part.title] : [])).at(-1);
