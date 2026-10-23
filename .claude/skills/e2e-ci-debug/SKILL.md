---
name: e2e-ci-debug
description: Finds why the Playwright e2e workflow failed in GitHub Actions from its `e2e-report` artifact — page snapshot, the browser's network requests from the trace, and stack.log — and shows the Compose environment as CI sees it (no `.env`). Use when "e2e is red", "Playwright times out in CI", "the login page never shows", or the e2e job fails while `pnpm dev` works locally.
---

# Debug a failed e2e run in CI

Run from the repo root; `$S` = session scratchpad.

1. Find the run and the failing line:
   ```bash
   gh run list --workflow e2e --limit 10
   gh run view <run-id> --log-failed | grep -E 'Error|waiting for|›' | head -20
   ```
2. Download the artifact (uploaded only on failure):
   ```bash
   gh run download <run-id> -n e2e-report -D $S/e2e-art
   cat $S/e2e-art/e2e/playwright-report/data/*.md          # error + page snapshot (what the browser showed)
   ```
3. Browser network from the trace — wrong URLs here usually mean a bad `config.json`:
   ```bash
   mkdir -p $S/e2e-art/trace && cd $S/e2e-art/trace && unzip -oq ../e2e/playwright-report/data/<first>.zip
   grep -ho '"url":"[^"]*"' *.network | sort | uniq -c
   ```
4. Container logs: `grep -E '^(api|ai-service|web|keycloak)-1' $S/e2e-art/stack.log | grep -vE 'readyz|RouterExplorer'`.
5. Compose env as CI sees it (job env vars only, plus the `.env` the workflow copies):
   ```bash
   env -i PATH="$PATH" HOME="$HOME" LLM_PROVIDER=fake \
     docker compose --file infra/compose/docker-compose.yml --env-file .env.example --profile full config web ai-service api
   ```
   `null` = unset in the container; a value starting with `#` = an inline comment after an empty value.

## Pitfalls

- A literal `${WEB_…}` in a request URL: the web container rendered `config.json` without its variables.
- Compose and Node parse `.env` differently: `KEY=   # note` is `""` for `pnpm dev`, `"# note"` for Compose.
- `playwright install` can take ~10 min (`ENOTFOUND playwright.download.prss.microsoft.com` falls back); that
  is the CDN, not the test.
- Angular drops whitespace between elements, so `hasText: /\bok\b/` never matches `<span>write</span><span>ok</span>`;
  assert on the element (`has: page.getByText('ok', { exact: true })`). Read the DOM in `*.trace` (`grep -o`).
- A test that fails after its write leaves the document behind; the retry then fails on the SHA-256 dedupe.
  Debug the first attempt, not `-retry1`.
- The smoke can't run against a `pnpm dev` with a real model: it needs `LLM_PROVIDER=fake` (ask before
  restarting the user's dev processes).
