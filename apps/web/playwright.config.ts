import { defineConfig, devices } from '@playwright/test';

const externalBaseUrl = process.env.SMARTLIB_E2E_BASE_URL;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',
  use: {
    baseURL: externalBaseUrl ?? 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    launchOptions: { chromiumSandbox: true },
  },
  webServer: externalBaseUrl ? undefined : {
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: 'chrome' } }],
});
