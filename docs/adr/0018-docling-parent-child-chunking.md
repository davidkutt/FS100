# ADR-0018: Docling parsing and parent-child chunking

- **Status:** Accepted (M3a.5)
- **Date:** 2026-10-26
- **Plan reference:** D59, D50, D55 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

pypdf (Phase 1) loses headings, tables and reading order. Docling returns a structured DoclingDocument,
but brings PyTorch and layout models onto a 16 GB laptop whose AI service already holds bge-m3. Chunks
of 1000/150 characters (ADR-0004) match precisely but give the LLM only part of a long section, and two
overlapping chunks of one section can take two of the five source slots.

## Decision

- **PDFs go through Docling** (`docling-slim[convert-core,feat-chunking,format-pdf,models-local]==2.141.0`,
  no OCR/VLM extras, `do_ocr=False`) **in a child process per document** (`python -I -m
  ai_service.ingest IN OUT`, `DOCLING_TIMEOUT_S` = 300 s, a constant): Docling's peak goes back to the OS
  when the child exits, instead of staying in the in-process worker (D53) next to bge-m3. The parent
  process only reads the result with `docling-core` (pydantic models, no torch).
- **pypdf stays as the fallback**: a crash or timeout of the child logs a warning and the PDF is indexed
  page by page as before. PyMuPDF stays out (AGPL). Markdown and TXT keep their own parsers; HTML is not
  accepted yet (it arrives with the curator, M3b.9).
- **Sections from the DoclingDocument**: the body in reading order, a new section at every heading and
  page break, under its heading path (title level 0, then the header levels, like `#`/`##` in
  Markdown); tables as Markdown tables without Docling's cell padding; pictures left out. Page labels
  stay exact, as with pypdf. A table of contents comes out as a table and is kept, its dot leaders
  shortened to `…`.
- **The parse is stored** with the original (`ai.source_documents.parsed` jsonb + `parser`, migration
  `0003_parsed`): the upload's ingest job converts, a re-index reuses the stored DoclingDocument while
  `parser` is the installed `docling <version>` and converts again after a Docling upgrade (D55). A
  fallback is not stored, so the next ingest or re-index tries Docling again.
- **Parent-child**: parents are each section cut to `PARENT_SIZE` (**2000** characters ≈ 500 tokens),
  chunks of `CHUNK_SIZE`/`CHUNK_OVERLAP` (1000/150, unchanged) are cut inside them and indexed. Every
  point carries `parent_id` (`doc_id:version:n`) and `parent_text`. Search fetches the fused top 50,
  keeps the best chunk of each parent, then reranks/cuts to `top_k`; a hit's `text` is its parent's, and
  `explain` adds `chunk_text` (the inspector shows the chunk and opens the whole section). The agent
  numbers a section once per turn even if a later search finds another of its chunks. `get_document`
  pages through sections (`sections`, `section_count`, `next_offset`), not chunks. `PARENT_SIZE=0` turns
  it off (each chunk its own parent); points indexed before M3a.5 have no `parent_id` and behave so.
- **torch from PyTorch's CPU index** (`tool.uv.sources`, so `torch`/`torchvision` are direct
  dependencies): PyPI's Linux wheels bring ~3 GB of CUDA libraries into CI and the image.
  `docling-ibm-models[opencv-python-headless]` because TableFormer imports cv2.

## Evidence

`kb-eval retrieval`, bge-m3, BM25 English, `rrf:2:0.5`, no reranker, top 10, in-memory Qdrant, MacBook
Air M1 16 GB. "Top-5 chars" = characters the chat puts into the prompt per question (`RETRIEVAL_TOP_K`).

`dev` (36 items, 30 answerable):

| Chunking | Points | hit@1 | hit@5 | MRR@10 | nDCG@10 | Abstention at 0.55 | Top-5 chars |
|---|---|---|---|---|---|---|---|
| pypdf, 1000/150 (`m3a2-hybrid`) | 218 | 0.80 | 1.00 | 0.90 | 0.912 | — | — |
| Docling, 1000/150 | 221 | 0.83 | 1.00 | 0.92 | 0.925 | 0.82 | 2,625 |
| **Docling, 1000/150 in parents ≤ 2000** | 224 | 0.83 | 1.00 | 0.92 | 0.924 | 0.82 | **3,601** |
| … in parents ≤ 4000 | 222 | 0.83 | 1.00 | 0.92 | 0.925 | 0.82 | 4,163 |
| … in parents ≤ 8000 | 222 | 0.83 | 1.00 | 0.92 | 0.925 | 0.82 | 5,023 |
| Docling, 500/75 in parents ≤ 2000 | 380 | 0.83 | 1.00 | 0.92 | 0.929 | 0.75 | 3,804 |
| … in parents ≤ 4000 | 380 | 0.83 | 1.00 | 0.92 | 0.929 | 0.75 | 4,572 |
| Docling, 1800/200 in parents ≤ 8000 (D59's ~450 / ≤ 2000 tokens) | 171 | 0.80 | 1.00 | 0.89 | 0.915 | 0.77 | 5,280 |
| Docling HybridChunker, 256 tokens (bge-m3 tokenizer) | 254 | 0.80 | 0.97 | 0.87 | 0.884 | — | 2,621 |
| Docling HybridChunker, 512 tokens | 180 | 0.80 | 0.97 | 0.87 | 0.882 | — | 3,465 |

- **Docling** gains a little on `dev`: the PDF's chunks follow its sections, the PDF items score higher
  (top-1 similarity 0.58–0.62 → 0.62–0.68), and `r-040` moves 2 → 1 because a page-sized PDF chunk no
  longer outranks the Azure runbook.
- **Parents do not move retrieval** in this corpus: 158 of its 160 sections are under 2000 characters,
  so a parent is mostly the section a 1000-character chunk already sat in. What they change is what the
  LLM reads — whole sections, one slot each — at +37 % prompt text per answer (≈ +250 tokens). Larger
  parents only add text. 2000 also keeps five sources inside the agent's 3,000-token search budget
  (12,000 characters), so no source is truncated.
- **Smaller chunks** (500/75, D59's lower end) gain 0.004 nDCG@10, under the 0.02 bar, and lower the
  abstention accuracy at the 0.55 threshold (0.82 → 0.75); larger ones (1800/200) lose hit@1.
- **HybridChunker** (all files through Docling, its Markdown backend included; `contextualize()` text)
  loses 0.04 nDCG@10 and `r-021` (a schema in a code block) falls out of the top 5.

`test` (24 items, 20 answerable), once:

| Chunking | hit@1 | hit@5 | MRR@10 | nDCG@10 | Exact terms (3) hit@5 / nDCG@10 | Abstention at 0.55 | Top-5 chars | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|
| pypdf, 1000/150 (`m3a2-hybrid`) | 0.70 | 0.95 | 0.79 | 0.813 | 1.00 / 0.59 | 0.95 | — | 67 / 79 |
| Docling, 1000/150 | 0.70 | 0.95 | 0.78 | 0.810 | 1.00 / 0.57 | 0.95 | 2,500 | 65 / 82 |
| **Docling, 1000/150 in parents ≤ 2000** (`m3a5-parents`) | 0.70 | 0.95 | 0.78 | 0.809 | 1.00 / 0.57 | 0.95 | 3,373 | 66 / 81 |

Neutral within the gate's 0.02: `r-015` (*no space left on device*, exact term) moves 3 → 4 because the
PDF's section-sized chunks now compete, `r-035` (multi-chunk) 7 → 8; nothing leaves the top 5. Full set
(the CI gate, 50 answerable): hit@5 0.98, nDCG@10 0.88 (baseline 0.98 / 0.86).

### Tables (5 public NIST PDFs)

SP 800-218 (36 pages), SP 800-61r3 (48), CSWP 29 / CSF 2.0 (32), SP 800-190 (63), SP 800-204 (50), all
public domain, converted by the service's `convert_pdf`: 23, 30, 4, 15 and 15 tables, 16–31 s each.
The data tables survive: CSF 2.0's *Table 1* (Function | Category | Identifier, 23 rows) and SSDF's
practice tables (Practices | Tasks | Examples | References) keep their rows and columns, merged cells
are repeated per row, captions stay above the table; pypdf runs the same cells together line by line.
Two flaws, both accepted: a table continued from the previous page starts with empty cells, and
tables of contents come out as tables (SP 800-190's with each entry three times). Docling pads every
cell to its column's width (36–58 % of the table characters), so the padding, rules and dot leaders
are compacted before chunking.

### Memory and time (D50)

The Docling child, warm, measured with `/usr/bin/time -l`: 1.72 GB peak RSS for 36 pages, 1.90 GB for
63, 28–30 s wall each (≈ 5 s of it loading the models); the macOS footprint (compressed pages
included) peaks at ~4.2 GB. The AI service never imports torch: `ai_service.ingest` loads in 0.7 s with
`docling-core` only. End to end (re-index check with the real bge-m3, uploads built without parents,
then `kb-admin reindex` with `PARENT_SIZE=2000`): 17 uploads through the queue in 208 s, none failed, the
PDF through Docling; the gate swapped (`test` nDCG@10 0.807, −0.001; hit@5 and abstention unchanged;
`dev` −0.001), rollback 0.05 s (API) / 2.5 s (CLI). The AI process idles at 1.84 GB and peaks at 2.05 GB
while ingesting and 2.42 GB while the gate evaluates — within D50, Docling's child not included.

## Alternatives considered

- **Docling in the API process** — keeps ~2 GB resident after the first PDF.
- **Docling Serve as a container** — one more image and service in the 4 GB Docker VM budget.
- **Docling's HybridChunker** — lost on `dev` (above); it would also need every Markdown file to go
  through Docling.
- **Parents in a separate store** (Postgres or vector-less points) — saves the duplicated `parent_text`,
  costs a second lookup per search; the corpus is small.
- **D59's sizes** (children ~450 tokens, parents ≤ 2000 tokens) — no retrieval gain, 2× the prompt text
  of the chosen setting, and five such parents exceed the agent's search budget.

## Consequences

- The AI service's environment grows to ~1.1 GB (torch CPU, torchvision, transformers, opencv); the
  image from 0.63 to 2.4 GB (Docling converts in it: CSF 2.0, 32 pages, 45 s in the Docker VM). The first PDF downloads Docling's layout model
  `docling-project/docling-layout-heron` (Apache-2.0) and TableFormer `docling-project/docling-models`
  (CDLA-Permissive-2.0 / Apache-2.0), ≈ 1 GB, into the Hugging Face cache (`~/.cache/huggingface`, in
  the image the `huggingface-cache` volume, in CI an Actions cache). On a slow line the first conversion
  can hit the timeout and fall back once.
- A PDF ingest starts a Python process that loads Docling (~5 s before the first page).
- Prompts carry whole sections: more input tokens per answer. Whether they make answers better is only
  measurable with the judge (M3b.1); `PARENT_SIZE=0` and a re-index revert it.
- Tests never run Docling: an autouse fixture sends PDFs to pypdf; the conversion's plumbing, the
  fallback, the DoclingDocument → sections mapping and the stored parse have their own tests.
- Scanned PDFs still have no text (no OCR).
