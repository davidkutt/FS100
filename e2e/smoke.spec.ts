import { expect, test } from '@playwright/test';

// Demo steps 2–4 (plan.md §1) as an editor. Unique content dodges the SHA-256 dedupe on reruns.
test('login → upload → ask → cited answer', async ({ page }) => {
  const filename = `e2e-rollback-${Date.now()}.md`;
  const content = `# Rollback\n\nTo roll back a release, redeploy the previous image tag (${filename}).\n`;

  await page.goto('/');
  await page.locator('#username').fill('bob');
  await page.locator('#password').fill('bob');
  await page.locator('#kc-login').click();

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
  await page.getByRole('button', { name: new RegExp(`\\[\\d+\\] ${filename}`) }).click();
  await expect(page.getByRole('dialog')).toContainText('previous image tag');

  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Documents' }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: `Delete ${filename}` }).click();
  await expect(row).toHaveCount(0);
});
