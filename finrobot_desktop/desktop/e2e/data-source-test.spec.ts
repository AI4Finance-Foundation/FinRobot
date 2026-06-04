import { test } from '@playwright/test'

// Visual self-check for the data-source "Test connection" buttons (added
// 2026-06-04 alongside POST /api/settings/test-data-provider). Each keyed data
// source (FMP, Finnhub) gets a Test button beside its key field, mirroring the
// LLM provider one. Stubs /api/settings + /api/settings/test-data-provider and
// screenshots zh + en, exercising both an OK result (FMP) and an auth failure
// (Finnhub).

const SETTINGS = {
  model_name: 'openai:gpt-4o',
  providers: [
    {
      id: 'openai',
      label: 'OpenAI',
      kind: 'openai-compatible',
      base_url: 'https://api.openai.com/v1',
      models: ['gpt-4o', 'gpt-4o-mini'],
      key_set: true,
      is_builtin: true,
    },
  ],
  custom_providers: [],
  fmp_api_key_set: true,
  finnhub_api_key_set: false,
  alpha_vantage_api_key_set: false,
  adanos_api_key_set: false,
  sec_user_agent: 'Acme Research analyst@example.com',
  sec_identity_active: true,
  sec_identity_dismissed_at: null,
  sec_holdings_auto_refresh: false,
  log_level: 'INFO',
  log_to_file: true,
  log_retention_days: 7,
  available_providers: ['fmp', 'yfinance', 'sec_edgar', 'news_aggregator'],
  startup_error: null,
  secret_storage_mode: 'keychain',
}

async function gotoSettings(page: import('@playwright/test').Page, locale: 'zh' | 'en') {
  await page.addInitScript((loc) => {
    localStorage.setItem(
      'finrobot-ui-prefs',
      JSON.stringify({ state: { locale: loc }, version: 0 }),
    )
  }, locale)
  await page.route('**/api/settings', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SETTINGS) }),
  )
  // One distinct result per source so every state shows in a single shot:
  // FMP ok · Finnhub auth · Adanos ok · Alpha Vantage connect.
  const RESULTS: Record<string, { ok: boolean; code: string; detail: string }> = {
    fmp: { ok: true, code: 'ok', detail: '' },
    finnhub: { ok: false, code: 'auth', detail: 'HTTP 401' },
    adanos: { ok: true, code: 'ok', detail: '' },
    alpha_vantage: { ok: false, code: 'connect', detail: 'ConnectError' },
  }
  await page.route('**/api/settings/test-data-provider', async (r) => {
    const body = JSON.parse(r.request().postData() || '{}')
    await r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(RESULTS[body.provider] ?? { ok: false, code: 'unknown', detail: '' }),
    })
  })
  await page.goto('/settings')
  await page
    .getByText(/AI 模型|AI Model/)
    .first()
    .waitFor({ timeout: 12000 })
  // Scroll the Data Sources section into view.
  await page.locator('[data-section="dataSources"]').scrollIntoViewIfNeeded()
}

async function runAllTests(page: import('@playwright/test').Page) {
  const buttons = page.locator('[data-section="dataSources"] .settings-test-row button')
  const n = await buttons.count() // FMP · Finnhub · Adanos · Alpha Vantage
  for (let i = 0; i < n; i++) await buttons.nth(i).click()
  // Wait until every test row has resolved to a result.
  await page
    .locator('[data-section="dataSources"] .settings-test-result')
    .nth(n - 1)
    .waitFor()
  await page.waitForTimeout(200)
}

test('data-source test buttons — zh', async ({ page }) => {
  await gotoSettings(page, 'zh')
  await page.locator('[data-section="dataSources"]').screenshot({
    path: 'e2e/_data-source-test-zh-idle.png',
  })
  await runAllTests(page)
  await page.locator('[data-section="dataSources"]').screenshot({
    path: 'e2e/_data-source-test-zh-result.png',
  })
})

test('data-source test buttons — en', async ({ page }) => {
  await gotoSettings(page, 'en')
  await page.locator('[data-section="dataSources"]').screenshot({
    path: 'e2e/_data-source-test-en-idle.png',
  })
  await runAllTests(page)
  await page.locator('[data-section="dataSources"]').screenshot({
    path: 'e2e/_data-source-test-en-result.png',
  })
})
