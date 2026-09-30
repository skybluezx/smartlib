import { expect, test } from '@playwright/test';

test('reads the native intake and evidence contract without retired endpoints', async ({ page, request }) => {
  const failures: string[] = [];
  const retiredCalls: string[] = [];
  page.on('response', (response) => {
    if (response.url().includes('/api/') && response.status() >= 500) failures.push(response.url());
  });
  page.on('request', (req) => {
    if (/\/knowledge-hub\/publication-(imports|verifications)/.test(req.url())) retiredCalls.push(req.url());
  });
  await page.goto('/knowledge-hub');
  await expect(page.getByRole('heading', { name: '系统总览', exact: true })).toBeVisible();
  await page.goto('/knowledge-hub/imports');
  await expect(page.getByRole('heading', { name: '论文导入', exact: true })).toBeVisible();
  const queue = await request.get('/api/v1/publications/intake');
  expect(queue.status()).toBe(200);
  const body = (await queue.json()) as { total: number; items: Record<string, unknown>[] };
  expect(body.total).toBeGreaterThan(0);
  expect(body.items[0].record_id).toBeTruthy();
  expect(body.items[0].import_item_id).toBeUndefined();
  await page.goto('/knowledge-hub/verifications/publications');
  await expect(page.getByRole('heading', { name: '论文核验工作台' })).toBeVisible();
  const detailResponse = page.waitForResponse((r) => /\/api\/v1\/publications\/intake\/[0-9a-f-]+$/.test(r.url()));
  await page.getByRole('button', { name: '查看证据', exact: true }).first().click();
  expect((await detailResponse).status()).toBe(200);
  await expect(page.getByRole('dialog').first()).toBeVisible();
  expect(failures).toEqual([]);
  expect(retiredCalls).toEqual([]);
});
