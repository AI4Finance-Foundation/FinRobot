import { test } from '@playwright/test'

// Visual self-check for the registry-driven model selection (ADR-0013, redesign
// 2026-06-04). Built-ins are Anthropic + OpenAI; everything else is a custom
// provider. Provider picker is a cosmic dropdown (no native <select>); model id
// is free text; no per-role overrides. Stubs /api/settings and screenshots
// zh + en, exercising the dropdown and the add-custom form.

const SETTINGS = {
  model_name: 'openai:gpt-4o',
  providers: [
    {
      id: 'anthropic',
      label: 'Anthropic',
      kind: 'anthropic',
      base_url: null,
      models: ['claude-sonnet-4-6', 'claude-opus-4-8'],
      key_set: false,
      is_builtin: true,
    },
    {
      id: 'openai',
      label: 'OpenAI',
      kind: 'openai-compatible',
      base_url: 'https://api.openai.com/v1',
      models: ['gpt-4o', 'gpt-4o-mini'],
      key_set: true,
      is_builtin: true,
    },
    {
      id: 'openrouter',
      label: 'OpenRouter',
      kind: 'openai-compatible',
      base_url: 'https://openrouter.ai/api/v1',
      models: ['anthropic/claude-sonnet-4'],
      key_set: false,
      is_builtin: false,
    },
  ],
  custom_providers: [
    {
      id: 'openrouter',
      label: 'OpenRouter',
      kind: 'openai-compatible',
      base_url: 'https://openrouter.ai/api/v1',
      models: ['anthropic/claude-sonnet-4'],
    },
  ],
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
  await page.goto('/settings')
  await page
    .getByText(/AI 模型|AI Model/)
    .first()
    .waitFor({ timeout: 12000 })
}

test('model registry settings — zh', async ({ page }) => {
  await gotoSettings(page, 'zh')
  await page.screenshot({ path: 'e2e/_model-registry-zh.png', fullPage: true })

  // Open the provider dropdown (custom-styled, not native).
  await page.locator('.settings-dd-trigger').click()
  await page.locator('.settings-dd-menu').waitFor()
  await page.waitForTimeout(250) // let the open animation settle before the shot
  await page.screenshot({ path: 'e2e/_model-registry-zh-dropdown.png', fullPage: true })
})

test('model registry settings — en + add custom', async ({ page }) => {
  await gotoSettings(page, 'en')
  await page.screenshot({ path: 'e2e/_model-registry-en.png', fullPage: true })

  // Open dropdown → click the "add custom provider" entry → form appears.
  await page.locator('.settings-dd-trigger').click()
  await page.locator('.settings-dd-add').click()
  await page.locator('.settings-custom-box').waitFor()
  await page.waitForTimeout(150)
  await page.screenshot({ path: 'e2e/_model-registry-en-addcustom.png', fullPage: true })
})
