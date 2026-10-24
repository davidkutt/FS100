# ADR-0018: Docling parsing and parent-child chunking

- **Status:** Proposed (draft, M3a.0; decided in M3a.5)
- **Date:** 2026-10-23
- **Plan reference:** D59, D50 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

pypdf (Phase 1) loses headings, tables and reading order. Docling returns a structured DoclingDocument,
but brings PyTorch and layout models onto a 16 GB laptop whose AI service already holds bge-m3.

## Spike notes (M3a.0)

NIST SP 800-218 (36 pages, text PDF with tables, public domain), Docling 2.141.0, `do_ocr=False`, table
structure on, MacBook Air M1 16 GB:

| Run | Convert | Wall | Peak RSS | Result |
|---|---|---|---|---|
| first (downloads layout + table models, ~0.5 GB) | 55.8 s | 70 s | 2.02 GB | 36 pages, 23 tables, 22 headings, JSON 0.61 MB |
| warm | 24.6 s (0.7 s/page) | 28 s | 1.96 GB | same |

- The table of contents is detected as a table (dot leaders in the cells) — filter or accept in M3a.5.
- Dependencies: `torch` 2.14.1 and `transformers` 5.20.2 come with Docling; `docling-core` already pulls
  tree-sitter and the Python / JavaScript / TypeScript / C grammars (relevant for ADR-0020). Pinned:
  `docling==2.141.0` (2.142 is days old).

## Decision (proposed)

- Docling for PDF and HTML without OCR/VLM extras; pypdf stays as the fallback; PyMuPDF stays out (AGPL).
- **Parse in a child process per ingest job** (spawn, `DOCLING_TIMEOUT_S`): the ~2 GB peak returns to the
  OS after each document instead of staying in the in-process worker (D53) next to bge-m3. A plan
  refinement of D50's "one at a time".
- Child chunks of ~350–500 tokens indexed, parent sections ≤ 2,000 tokens to the LLM; HybridChunker vs. the
  own heading-aware chunker compared on `dev`.

## Alternatives considered

- **Docling in the API process** — keeps ~2 GB resident after the first PDF.
- **Docling Serve as a container** — one more image and service in the 4 GB Docker VM budget.

## Consequences

To be written in M3a.5.
