import { expect, type Page, test } from '@playwright/test';

async function login(page: Page, user: string): Promise<void> {
  await page.goto('/');
  await page.locator('#username').fill(user);
  await page.locator('#password').fill(user);
  await page.locator('#kc-login').click();
}

// Demo steps 2–4 (plan.md §1) as an editor. Unique content dodges the SHA-256 dedupe on reruns.
test('login → upload → ask → cited answer', async ({ page }) => {
  const filename = `e2e-rollback-${Date.now()}.md`;
  const content = `# Rollback\n\nTo roll back a release, redeploy the previous image tag (${filename}).\n`;

  await login(page, 'bob');

  await page.getByRole('link', { name: 'Documents' }).click();
  await page.getByRole('group', { name: 'Domains' }).getByText('devops').click();
  await page
    .getByLabel(/PDF, Markdown or text files/)
    .setInputFiles({ name: filename, mimeType: 'text/markdown', buffer: Buffer.from(content) });
  const row = page.getByRole('row', { name: new RegExp(filename) });
  await expect(row.getByText('ready')).toBeVisible({ timeout: 60_000 });

  await page.getByRole('link', { name: 'Chat' }).click();
  await page.getByLabel('Question').fill('How do I roll back a release?');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.locator('summary', { hasText: 'kb.search_knowledge_base' })).toContainText(
    'ok',
  );
  await page.getByRole('button', { name: new RegExp(`\\[\\d+\\] ${filename}`) }).click();
  await expect(page.getByRole('dialog')).toContainText('previous image tag');

  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Documents' }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: `Delete ${filename}` }).click();
  await expect(row).toHaveCount(0);
});

// Demo step 4 (plan-phase-2.md §1): the fake LLM proposes `kb.ingest_url` for "Add <url>". The
// approved run fetches the file from GitHub; the test deletes it again, since dedupe would fail a rerun.
test('agent write → reject, then approve → runs once', async ({ page }) => {
  const url = 'https://raw.githubusercontent.com/davidkutt/FS100/main/docs/adr/template.md';

  await login(page, 'bob');
  await page.getByRole('link', { name: 'Chat' }).click();

  await page.getByLabel('Question').fill(`Add ${url}`);
  await page.getByRole('button', { name: 'Send' }).click();
  await page.getByRole('button', { name: 'Reject' }).click();
  await expect(page.getByText('Rejected.', { exact: true })).toBeVisible();
  const tool = page.locator('summary', { hasText: 'kb.ingest_url' });
  await expect(tool.filter({ hasText: 'rejected' })).toBeVisible();

  await page.getByLabel('Question').fill(`Add ${url}`);
  await page.getByRole('button', { name: 'Send' }).click();
  await page.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText('Approved and done.', { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  // The status badge, not the text: Angular drops the spaces, so the summary reads "writeokdocument…".
  await expect(tool.filter({ has: page.getByText('ok', { exact: true }) })).toHaveCount(1);

  await page.getByRole('link', { name: 'Documents' }).click();
  const row = page.getByRole('row', { name: /template\.md/ });
  await expect(row.getByText('ready')).toBeVisible({ timeout: 60_000 });
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Delete template.md' }).click();
  await expect(row).toHaveCount(0);
});
