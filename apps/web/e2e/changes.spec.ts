import { expect, test } from '@playwright/test';

test('change workbench separates submitting from applying', async ({ page }) => {
  const submission = { submission_id: '11111111-1111-4111-8111-111111111111', context_name: '审核示例',
    source_label: '官方目录', status: 'needs_review', proposals: [{ proposal_id: '22222222-2222-4222-8222-222222222222',
      field_path: 'description', current_value: '原说明', proposed_value: '新说明', application_state: 'pending', decision_reason: null }] };
  let submitted = false;
  let applied = false;
  await page.route('**/api/v1/changes**', async (route) => {
    const req = route.request();
    if (req.method() === 'POST' && req.url().endsWith('/decision')) {
      expect(req.postDataJSON()).toMatchObject({ decision: 'accept', reason: '已核对官方证据' });
      applied = true;
      submission.status = 'accepted'; submission.proposals[0].application_state = 'applied';
    } else if (req.method() === 'POST') {
      const body = req.postDataJSON() as { proposals: { base_version: number }[] };
      expect(body.proposals[0]).toMatchObject({ target_kind: 'object', field_path: 'description', proposed_value: '新说明' });
      expect(body.proposals[0].base_version).toBeGreaterThan(0);
      submitted = true;
    }
    await route.fulfill({ json: req.method() === 'GET' ? (submitted ? [submission] : []) : submission });
  });
  await page.goto('/knowledge-hub/changes');
  await expect(page.getByRole('heading', { name: '数据变更', exact: true })).toBeVisible();
  await expect(page.locator('#change-target option')).not.toHaveCount(1);
  await page.locator('#change-target').selectOption({ index: 1 });
  await page.getByLabel('建议内容', { exact: true }).fill('新说明');
  await page.getByLabel('依据来源', { exact: true }).fill('官方目录');
  await page.getByLabel('修改原因与证据说明', { exact: true }).fill('核实来源后修正');
  await page.getByRole('button', { name: '提交审核', exact: true }).click();
  await expect(page.getByText('已提交，正式数据将在审核通过后更新。')).toBeVisible();
  expect(submitted).toBe(true); expect(applied).toBe(false);
  await page.getByLabel('审核说明', { exact: true }).fill('已核对官方证据');
  await page.getByRole('button', { name: '接受并应用', exact: true }).click();
  await expect(page.getByText('官方目录 · 已应用')).toBeVisible();
  expect(applied).toBe(true);
});

test('person identity fields submit through review with the current version', async ({ page }) => {
  let submitted = false;
  await page.route('**/api/v1/changes**', async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { proposals: Record<string, unknown>[] };
      expect(body.proposals[0]).toMatchObject({
        field_path: 'identifiers.orcid', proposed_value: '0000-0002-1825-0097', base_version: expect.any(Number),
      });
      submitted = true;
    }
    await route.fulfill({ json: route.request().method() === 'GET' ? [] : {} });
  });
  await page.goto('/knowledge-hub/changes');
  // Choose a real person from the live catalog, without applying test changes.
  const response = await page.request.get('/api/v1/catalog/objects?object_types=person&page_size=1');
  const catalog = await response.json() as { items: { object_id: string; canonical_name: string }[] };
  const name = catalog.items[0].canonical_name;
  await page.locator('#change-search').fill(name);
  await expect(page.locator(`#change-target option[value="${catalog.items[0].object_id}"]`)).toHaveCount(1);
  await page.locator('#change-target').selectOption(catalog.items[0].object_id);
  await page.locator('#change-field').selectOption('identifiers.orcid');
  await expect(page.getByText('来源姓名或名称：' + name)).toBeVisible();
  await page.getByLabel('建议内容', { exact: true }).fill('0000-0002-1825-0097');
  await page.getByLabel('依据来源', { exact: true }).fill('界面测试');
  await page.getByLabel('修改原因与证据说明', { exact: true }).fill('验证审核请求');
  await page.getByRole('button', { name: '提交审核', exact: true }).click();
  await expect(page.getByText('已提交，正式数据将在审核通过后更新。')).toBeVisible();
  expect(submitted).toBe(true);
});
