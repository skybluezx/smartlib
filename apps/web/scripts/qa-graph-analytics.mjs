/* global document, window */
import AxeBuilder from '@axe-core/playwright';
import { chromium } from 'playwright';

const baseUrl = process.env.SMARTLIB_WEB_URL ?? 'http://127.0.0.1:18080';
const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const outputRoot = new URL('../../../outputs/', import.meta.url).pathname;
const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
  chromiumSandbox: true,
});

const reports = [];
for (const width of [1440, 1280]) {
  const context = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  const response = await page.goto(`${baseUrl}/graph-analytics`, {
    waitUntil: 'networkidle',
    timeout: 60_000,
  });
  await page.getByRole('heading', { name: '图谱分析', level: 1 }).waitFor();
  const tabs = await page.getByRole('tab').allTextContents();
  const pendingProgramRelations = await page.locator('.sg-funding-status article').filter({ hasText: '待核基金计划' }).locator('strong').textContent();
  const candidateTopName = await page.locator('.sg-candidate-distribution article strong').first().textContent();
  await page.getByRole('tab', { name: '仅已确认' }).click();
  const verifiedCaption = await page.getByText('已确认基金资助计划占比').textContent();
  if (width === 1440) {
    await page.getByRole('tab', { name: '演进视图' }).click();
    await page.screenshot({ path: `${outputRoot}/graph-analytics-funding-1440.png`, fullPage: true });
  }
  await page.getByRole('tab', { name: '人员合作' }).click();
  const peopleEdges = await page.locator('.sg-collaboration-edge:visible').count();
  await page.locator('.sg-collaboration-edge:visible').last().press('Enter');
  const peopleEvidenceLinks = await page.locator('.sg-edge-evidence a:visible').count();
  if (width === 1440) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `${outputRoot}/graph-analytics-people-1440.png`, fullPage: true });
  }
  await page.getByRole('tab', { name: '机构合作' }).click();
  const highlightedInstitutionEdges = await page.locator('.sg-collaboration-edge.highlighted:visible').count();
  await page.locator('.sg-collaboration-edge.highlighted:visible').last().press('Enter');
  const focusLabel = await page.locator('.sg-collaboration-detail > span:visible').textContent();
  if (width === 1440) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `${outputRoot}/graph-analytics-institutions-1440.png`, fullPage: true });
  }
  await page.getByRole('tab', { name: '学科方向' }).click();
  const disciplineRows = await page.locator('.sg-direction-table > div').count();
  const accessibility = await new AxeBuilder({ page }).include('.sg-analytics-page').analyze();
  const viewportOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  await page.screenshot({ path: `${outputRoot}/graph-analytics-${width}.png`, fullPage: true });
  reports.push({
    width,
    status: response?.status(),
    tabs,
    pendingProgramRelations,
    candidateTopName,
    verifiedCaption,
    peopleEdges,
    peopleEvidenceLinks,
    highlightedInstitutionEdges,
    focusLabel,
    disciplineRows,
    viewportOverflow,
    consoleErrors,
    accessibilityViolations: accessibility.violations.map((item) => ({
      id: item.id,
      targets: item.nodes.map((node) => node.target.join(' ')),
    })),
  });
  await context.close();
}

await browser.close();
console.log(JSON.stringify(reports, null, 2));
