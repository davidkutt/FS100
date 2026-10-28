# plan-daily-use.md — Phase 3c: Daily use

> **Status:** Draft v1 · **Updated:** 2026-10-26 · replaces the rest of `plan-phase-3.md` (M3a.8–M3b.9) and parks
> `roadmap-phases-3-6.md` and `plan-phase-4.md` … `plan-phase-6.md`.
> **Goal change:** FS100 is no longer built toward a portfolio roadmap (Kubernetes, Azure, MLOps). It becomes a
> **tool you use every day**, on **your Markdown notes**, from **Claude Code / VS Code and the web UI**, on the
> **16 GB M1**. Decided 2026-10-26.

---

## 1. Why re-plan

The roadmap assumed 8–10 h/week, ending in December 2027. In practice P1 → M3a.7 took two weeks
(2026-10-12 → 10-26). The code got ahead of what is verified and runnable on the machine it runs on.

**Done in code, but not on the running stack (state 2026-10-26):**

| Item | Problem |
|---|---|
| M2.8 Claude Code / VS Code login | The live Keycloak runs without `--features=cimd,resource-indicators`, on a realm imported before M2.8 |
| M3a.7 | Was uncommitted on `main`; the Drizzle journal already listed `0006`, but its SQL file was untracked |
| Memory (D50) | Swap at 5.8 of 7.2 GB with `pnpm dev` + infra; no service has a memory limit; Mode B with bge-m3 was never measured |
| Playwright e2e | Never run locally; P1–P3 Definition-of-Done boxes unticked |
| Retrieval gate | CI and `pnpm eval:retrieval` index without `.env`, so they measure the plain index, not the contextual one in use |
| GitHub tools | PATs expire 2026-11-18 |

**Built, off or without measured gain:** the reranker, priorities, HyDE, the LLM router and Docling. The
`test` split has about 20 answerable items, so one item moves hit@5 by 0.05. **Freeze them** (no further
work); re-decide them on your own corpus in M3c.2, and delete what still doesn't win.

**Built for many users or for show:** two-hop token exchange, RBAC, approvals, audit, cost caps, Mode B
images. They work and are tested. Keep them and don't extend them.

---

## 2. Decisions

IDs continue after the parked plans (D76–D120), so nothing clashes.

| ID | Decision |
|---|---|
| D121 | **Goal:** daily use by one person on the 16 GB M1. No Kubernetes, no Azure, no public demo |
| D122 | **Corpus:** a Markdown notes folder (`NOTES_DIR`) plus URLs added through `kb.ingest_url`. Nothing confidential, so D25 stays as it is |
| D123 | **Clients:** Claude Code / VS Code through `/mcp`, and the web UI, with equal weight |
| D124 | **Done** means the milestone's hand check ran on the daily stack, not only in tests or on a throwaway stack |
| D125 | **Seed-user ids are pinned in `realm-kb.json`.** A realm change then means recreating only Keycloak's database; owners of documents and conversations survive |
| D126 | **Retrieval quality is measured on your notes** (`notes_v1`, built from feedback, kept out of git). The demo golden set stays as CI's engine regression test |

---

## 3. Milestones

Sizes at the current pace: S < half a day, M ≈ 1 day, L ≈ 2–3 days.

### M3c.0 Stabilize and make it real (M)

- [x] Commit M3a.7 with its migration, snapshot, `priorities_v1.json`, baselines and the `retrieval-sweep` skill
- [x] `pnpm stack:backup`: `pg_dumpall` into git-ignored `backups/`, checked by restoring into a throwaway Postgres
- [x] Pin the seed users' current `sub`s in `realm-kb.json`; realm checked on a throwaway Keycloak (token
  matrix plus the scripted Claude Code CIMD login)
- [ ] Recreate only Keycloak's database on the daily stack (`docs/setup/startup.md` §7) and confirm the
  documents are still listed under the same users
- [ ] Hand check: Claude Code and VS Code log in to `/mcp`, and `search_knowledge_base` returns hits
- [ ] Daily run mode: measure Mode B (`pnpm stack:up:full`) with bge-m3, contextual retrieval and a Docling PDF
  peak (`pnpm mem` plus `sysctl vm.swapusage`); add `mem_limit` per compose service. Only if D50 still fails,
  put Phoenix behind a profile, after checking that the AI service runs without it
- [ ] GitHub tools: rotate the PATs before 2026-11-18, or clear `GITHUB_PAT_READ` if you don't use them
- [x] Docs: startup.md (backup, Keycloak recreate, CI-gate note), README status, CLAUDE.md

### M3c.1 Notes and URLs as sources (L)

- **Reuse:** a new `submit` under the same `doc_id` is a new version, and `KnowledgeBase` deletes the old
  version's points (`knowledge_base.py`, after the upsert). The work is in NestJS.
- `documents.source` (text, unique, nullable; migration 0007): `notes:<relative path>` or the URL.
  - The same source with a new `sha256` gives a new version of the same `id`; the same sha is a no-op.
  - `fromUrl` stores its URL as `source`.
- `apps/api/src/documents/sources.service.ts`:
  - Syncs `NOTES_DIR` (`*.md`: add, change, delete by `source`).
  - Re-fetches URL sources with `fetchDocument` (SSRF guard and allow-list unchanged).
  - Runs at boot, every `SOURCES_SYNC_MINUTES`, and from an admin "Sync now" button
    (`POST /api/admin/sources/sync`).
  - In Mode B, `NOTES_DIR` is bind-mounted read-only.
- **HTML by URL:** `fromUrl` accepted only `.md` / `.txt` / `.pdf` paths, so an ordinary docs page was
  rejected (415). A `text/html` response is now ingested as `.html`, with headings kept for chunks and
  citations. Moved here from the curator (M3a.5 deferred it to M3b.9).
- **Secret guard:** the sync is automatic and contextual retrieval sends whole notes to OpenRouter (and
  traces to Phoenix), so a note that looks like it holds a secret (private key; `sk-…`, GitHub, AWS, Slack or
  Google key; a JWT) is skipped and listed in the sync result instead of ingested. Presidio stays parked (M3b.5).
- Domains of a note: frontmatter `domains:` / `topics:`, else a folder → domain map, else a default.
  - **Kickoff:** look at the notes and decide whether a tenth catch-all domain is needed. That touches the
    `Domain` enums of both apps, `taxonomy.yaml` and the contracts.
- Prompts: change the persona from "assistant for software, platform and operations engineers" to your
  knowledge base (`rag-system@3`, `agent-system@4`, `tests/fixtures/chat-prompt.txt`).
- Cost: contextual retrieval is about 0.002 USD per document, so 1,000 notes is about 2 USD one-off.
- Tests: API e2e for a new, changed and deleted note and a changed URL.
- **Hand check:** edit a note; after a sync, the answer cites the new text in the web UI and in Claude Code.

**State 2026-10-28: code-complete; the kickoff decision and the hand check are open.**
- [x] Migration 0007 `source`; `fromSource` in `documents.service.ts` (add, new version, no-op), used by `fromUrl`
  (which now answers `unchanged` for the same URL and content instead of 409)
- [x] `sources.service.ts` + `POST /api/admin/sources/sync` + *Sync notes and URLs* on the documents page;
  the source path shows under the file name
- [x] HTML, secret guard, persona (`rag-system@3`, `agent-system@4`), Mode B mount, docs; tests (API e2e
  `test/sources.e2e-spec.ts`, AI service HTML and label tests)
- [ ] Kickoff: look at the notes, decide on a catch-all domain (the default is `dev` until then)
- [ ] Hand check on the daily stack (D124)

Deviations:
- HTML is parsed with the stdlib parser `web.fetch` already used (moved to `ingest.py`, headings now emitted
  as Markdown), then split like a note, instead of Docling's HTML backend: that needs the `format-html`
  extra (beautifulsoup4) and a child process, for the same headings.
- **Found while building:** a new version reset `lifecycle`, `priority` and `priority_topics` in Qdrant to the
  defaults, while NestJS kept them. `KnowledgeBase.index` now carries them over from the document's previous
  points; reindex is unaffected (it reconciles labels after the build).
- URL sources are re-fetched only when their row is a day old: a page whose markup changes on every fetch
  would otherwise be re-ingested and re-contextualized every `SOURCES_SYNC_MINUTES`.
- Notes are owned by a pseudo-user `notes` (*Notes folder*): admins change them, editors don't.
- The boot recovery of interrupted uploads moved to `onModuleInit`, so it runs before the boot sync adds
  `pending` rows.

### M3c.2 Feedback becomes eval items (M)

- **Reuse:** `feedback` (up/down plus comment), `messages.answerStatus` (`abstained` / `no_kb`) and `topScore`.
- **New:**
  - An admin "Review" list of thumbs-down and abstained questions with their cited sources.
  - A JSONL export in the `retrieval_v1` format, with `relevant` prefilled from the citations.
  - You curate the export into git-ignored `evals/local/notes_v1.jsonl`.
  - **Synthetic bootstrap** (M3b.2 trimmed): a cheap model writes questions from note chunks (direct,
    paraphrase without keyword overlap, unanswerable near-miss); a review CLI accepts, edits or rejects them
    into `notes_v1` with `source: synthetic`. One-off, cents per 100 items; reported apart from feedback items.
    Feedback alone from one user would take months to reach 40 items.
- **Run:** `kb-eval retrieval --corpus $NOTES_DIR --dataset evals/local/notes_v1.jsonl`, then the
  `retrieval-sweep` skill.
- **Once it has about 40 items:** decide the reranker, HyDE, priorities and the LLM router on it; delete
  whatever still loses. Recalibrate `RETRIEVAL_SCORE_THRESHOLD` (0.55, set on the demo corpus) on its
  unanswerable items: it was left for golden v2 (M3a.6), which `notes_v1` replaces.

### M3c.3 Skills (M)

- M3a.9 (D63) trimmed: the `skills/` loader, `load_skill` / `read_skill_file`, tool narrowing, and the skill
  name and hash on spans.
- 2–3 skills for notes, picked at kickoff (e.g. `rag-debugging` and "what do my notes say about X / where are
  the gaps"). `ci-failure-triage` only if the GitHub tools stay.
- The skills are also exposed as MCP prompts on `/mcp`, so Claude Code gets them.
- About 5 skill tasks in `agent_v2`.

### M3c.4 Long-term memory (M)

- M3b.7 (D72) as planned: `user_memory` plus proposals, a confirmation chip, a memory page, `memory.propose`.
- The ADR takes the next free number.

### M3c.5 Close-out (S)

- Tick the Definition-of-Done boxes that now hold.
- README: daily-use quickstart and the GIF.
- A short retrospective here.

---

## 4. Parked

| Item | Why | Back when |
|---|---|---|
| M3a.8 code-aware RAG | Claude Code already searches code locally | You want search across several repos |
| M3a.10 golden v2 on the demo corpus | Replaced by `notes_v1` (D126) | — |
| M3b.1–M3b.3 judge, synthetic data, judge gate | Paid per run, portfolio rigor | Answer quality regresses unnoticed |
| M3b.4 ACL | One user | A second user |
| M3b.5 guardrails | Own notes, allow-listed hosts; the notes sync skips likely secrets (M3c.1) | Untrusted web sources at scale |
| M3b.6 cascade, semantic cache | One user; `/admin/usage` first | Monthly cost nears the 20 USD key limit |
| M3b.8 compaction | History is cut silently, never at the context limit: `history_messages` keeps the newest ~2,000 tokens (`HISTORY_TOKEN_BUDGET`, `rag.py`) | The assistant forgets earlier turns; raise the budget first |
| M3b.9 curator | URL refresh plus `ingest_url` (with HTML from M3c.1) cover it | — |
| 3b options (D75): code execution, text-to-SQL, per-user GitHub | No use for notes; one user | — |
| Phase 4 Kubernetes, Phase 5 Azure | D121 | — |
| Phase 6 MLOps, BFF, supply chain, video | Needs the cloud, and a reranker that is off | — |
| Phase 6 local models | No room next to the stack on 16 GB | New hardware |

## 5. Definition of Done

- [ ] Every milestone above ticked, each hand check run on the daily stack (D124)
- [ ] `pnpm lint && pnpm test && pnpm build` green, CI green
- [ ] A day of normal use with the daily stack stays within D50 and swap doesn't keep growing
