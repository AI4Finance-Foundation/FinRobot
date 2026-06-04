import { test } from '@playwright/test'

// Visual self-check for the registry-driven model selection (ADR-0013).
// Stubs /api/settings with a representative registry: built-ins + one custom
// provider, deepseek key set, anthropic/openai not. Screenshots zh + en and
// exercises the custom-provider + per-role panels.

const SETTINGS = {
  model_name: 'deepseek:deepseek-chat',
  model_data: null,
  model_analysis: null,
  model_modeling: 'anthropic:claude-opus-4-8',
  model_synthesis: null,
  model_report: null,
  providers: [
    {
      id: 'deepseek',
      label: 'DeepSeek',
      kind: 'deepseek',
      base_url: null,
      models: ['deepseek-chat', 'deepseek-reasoner'],
      key_set: true,
      is_builtin: true,
    },
    {
      id: 'anthropic',
      label: 'Anthropic',
      kind: 'anthropic',
      base_url: null,
      models: ['claude-sonnet-4-6', 'claude-opus-4-8', 'claude-haiku-4-5-20251001'],
      key_set: false,
      is_builtin: true,
    },
    {
      id: 'openai',
      label: 'OpenAI',
      kind: 'openai-compatible',
      base_url: 'https://api.openai.com/v1',
      models: ['gpt-4o', 'gpt-4o-mini'],
      key_set: false,
      is_builtin: true,
    },
    {
      id: 'moonshot',
      label: 'Moonshot (Kimi)',
      kind: 'openai-compatible',
      base_url: 'https://api.moonshot.cn/v1',
      models: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'],
      key_set: false,
      is_builtin: true,
    },
    {
      id: 'qwen',
      label: 'Qwen (DashScope)',
      kind: 'openai-compatible',
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      models: ['qwen-plus', 'qwen-max', 'qwen-turbo'],
      key_set: false,
      is_builtin: true,
    },
    {
      id: 'openrouter',
      label: 'OpenRouter',
      kind: 'openai-compatible',
      base_url: 'https://openrouter.ai/api/v1',
      models: [],
      key_set: false,
      is_builtin: true,
    },
    {
      id: 'mygw',
      label: 'My Gateway',
      kind: 'openai-compatible',
      base_url: 'https://gw.local/v1',
      models: ['llama-3.1-70b'],
      key_set: true,
      is_builtin: false,
    },
  ],
  custom_providers: [
    {
      id: 'mygw',
      label: 'My Gateway',
      kind: 'openai-compatible',
      base_url: 'https://gw.local/v1',
      models: ['llama-3.1-70b'],
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
  await page.getByText(/AI 模型|AI Model/).first().waitFor({ timeout: 12000 })
}

test('model registry settings — zh', async ({ page }) => {
  await gotoSettings(page, 'zh')
  await page.screenshot({ path: 'e2e/_model-registry-zh.png', fullPage: true })

  // Expand both advanced panels and screenshot.
  for (const d of await page.locator('details.settings-advanced').all()) {
    await d.locator('summary').click()
  }
  await page.waitForTimeout(300)
  await page.screenshot({ path: 'e2e/_model-registry-zh-expanded.png', fullPage: true })
})

test('model registry settings — en + provider switch', async ({ page }) => {
  await gotoSettings(page, 'en')
  await page.screenshot({ path: 'e2e/_model-registry-en.png', fullPage: true })

  // Switch the provider to OpenAI → key field flips to "Required", base_url hint shows.
  const providerSelect = page.locator('select').first()
  await providerSelect.selectOption('openai')
  await page.waitForTimeout(300)
  await page.screenshot({ path: 'e2e/_model-registry-en-openai.png', fullPage: true })
})
