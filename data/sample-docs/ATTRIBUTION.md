# Sample corpus — sources and licences

The Phase 1 demo and eval corpus (plan.md D22, D25). Every file is public or self-written; nothing here
may contain private or customer data, because chat sends retrieved chunks to third-party LLM providers.

Domain tags per file live in [`domains.json`](domains.json) — use them when uploading the corpus, and
keep them in sync: the retrieval eval (`pnpm eval:retrieval`) ingests exactly the files listed there.

| File | Source | Licence |
|---|---|---|
| `fs100-readme.md`, `fs100-plan.md` | Snapshot of this repo's `README.md` and `plan.md` (2026-10-15) | MIT (this repo) |
| `adr-0001-…`, `adr-0002-…`, `adr-0003-…` | Snapshot of `docs/adr/` (2026-10-15) | MIT (this repo) |
| `../../docs/setup/setup-installation.md`, `../../docs/setup/setup-startup.md` | Snapshot of `docs/setup/` (2026-10-15) | MIT (this repo) |
| `runbook-*.md`, `slo-handbook.pdf` | Written for this project; procedures are generic, hostnames are examples | MIT (this repo) |

The repo documents are **snapshots** on purpose: golden-set labels (`evals/datasets/`) point at their
headings, so the corpus must not drift with every docs change. Refresh a snapshot only together with a
new dataset version.

## Adding a document

1. Public or self-written only. For upstream docs (Kubernetes, Keycloak, Qdrant, GitHub Actions …) check
   the licence first (e.g. CC BY 4.0 needs attribution, which goes into the table above).
2. Add the file and its domains to `domains.json`.
3. Adding documents changes the eval baseline (more distractors) — note it in the next eval run.
