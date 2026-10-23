# ADR-0013: Prompts as versioned files in the repo, with a content hash on every record

- **Status:** Accepted (M2.7)
- **Date:** 2026-10-22
- **Plan reference:** D45, D46 ([plan-phase-2.md §3](../../plan-phase-2.md#3-decisions))

## Context

Answer quality changes with the prompt as much as with the model or retrieval. Until M2.6 the three
prompts (agent system prompt, Phase 1 RAG prompt, router classifier) were Python strings with a
hand-written `PROMPT_VERSION` next to them — only the agent's and the RAG prompt's versions reached the
`done` event, and nothing caught an edit without a version bump. The agent eval (D43) and the gap signals
(D49) are only comparable across runs if each record says which prompt produced it.

## Decision

- **Files.** Each prompt is a Markdown file in the AI service package
  (`apps/ai-service/src/ai_service/prompts/<id>.md`) with front matter `id` and `version` (an integer);
  the body is the prompt, sent verbatim (templates use `str.format` fields such as `{repo}`). The files
  ship inside the wheel, so the image needs no extra copy step.
- **Loading.** `prompts.load(id)` reads the file once at import and computes **`hash`**: the first 12 hex
  digits of the SHA-256 of the body (the template, before formatting). `ref` = `id@version`.
- **Version rule.** A change to the body bumps `version` in the same PR. The hash is the safety net: an
  edit without a bump still shows up as a second hash under the same version.
- **Where it is recorded:**
  - SSE `done`: `promptVersion` (`agent-system@2`) and `promptHash`; NestJS stores both on the assistant
    message (`messages.prompt_version`, `prompt_hash`).
  - Spans: `llm.prompt_template.version` (OpenInference) and `prompt.hash` on `agent.run` and every `llm`
    span; on the `route` span when `ROUTER=llm` (router prompt).
  - Eval reports: `kb-eval agent | redteam` list every prompt's `ref` and hash in the JSON and the
    Markdown header; `kb-eval routing` names the classifier prompt for the `llm` router.
- **Phoenix prompt management** is not the source of truth: prompts are reviewed in PRs like code, and
  Phoenix shows the version and hash it receives on spans.

## Alternatives considered

- **Phoenix (or another registry) as the prompt store** — prompts would change outside code review and
  tests, and the AI service would need the registry at startup; a self-hosted Phoenix is a dev tool here.
- **Version only, no hash** — relies on discipline; one forgotten bump makes two prompts indistinguishable
  in the eval history.
- **Hash only** — unique, but not readable in a report or a PR; the version says "this was intentional".
- **A lock file with expected hashes, checked by a test** — would force the bump, at the cost of a second
  edit per change; the recorded hash already makes a missed bump visible. Revisit if it happens.

## Consequences

- A prompt change is a reviewed diff of a `.md` file plus a version bump, and every message, trace and
  eval run since names the exact prompt; comparing two eval runs starts with comparing their prompt lines.
- The RAG prompt is still pinned by the snapshot test (`tests/fixtures/chat-prompt.txt`); moving the
  prompts into files did not change their text, so the versions stayed `agent-system@2`, `rag-system@1`
  and `router@1`.
- Prompt files are package data: a new prompt only needs a new file and a `load()` call.
