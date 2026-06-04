// Playwright config for v5 retail walkthrough (spec §15 condition 5).
//
// Headless Chromium against vite dev. Backend isn't required — page.route
// stubs every /api/* call in v5-walkthrough.spec.ts.

import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 1280, height: 900 },
    headless: true,
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
