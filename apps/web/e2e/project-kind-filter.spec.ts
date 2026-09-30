import { expect, test } from '@playwright/test';

test('links output type and project-kind filters against live data', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/outputs');

  await expect(page.getByRole('heading', { level: 1, name: '科研成果' })).toBeVisible();
  await expect(page.locator('#project-kind')).toHaveCount(0);

  await page.locator('#outputs-type').click();
  await page.getByRole('option', { name: '项目', exact: true }).click();

  const projectKind = page.getByRole('combobox', { name: '项目种类' });
  await expect(projectKind).toBeVisible();
  await expect(projectKind).toBeEnabled();
  await projectKind.click();
  await page.getByRole('option', {
    name: '111 Project（2）',
    exact: true,
  }).click();

  await expect(page).toHaveURL(/type=project/);
  await expect(page).toHaveURL(/projectKind=3ec3c5bd-21e5-5b79-a3a8-607723d8e3bf/);
  await expect(page.locator('.sg-results-summary strong')).toHaveText('2');
  await expect(page.locator('.sg-catalog-row')).toHaveCount(2);

  await page.locator('#outputs-type').click();
  await page.getByRole('option', { name: '论文', exact: true }).click();

  await expect(page.locator('#project-kind')).toHaveCount(0);
  await expect(page).not.toHaveURL(/projectKind=/);
});
