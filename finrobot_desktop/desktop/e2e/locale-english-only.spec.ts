import { expect, test } from '@playwright/test'

// Visual self-check for the English-only switch (2026-06-05): the in-app language
// selector was removed and the whole app defaults to English. Seeds a STALE 'zh'
// locale in localStorage to prove main.tsx coerces it back to 'en' on launch — an
// English settings heading is the probe.

const SETTINGS = {
  model_name: 'openai:gpt-4o',
  providers: [],
  custom_providers: [],
  fmp_api_key_set: false,
  finnhub_api_key_set: false,
  alpha_vantage_api_key_set: false,
  adanos_api_key_set: false,
  sec_user_agent: '',
  sec_identity_active: false,
  sec_identity_dismissed_at: null,
  sec_holdings_auto_refresh: false,
  log_level: 'INFO',
  log_to_file: true,
  log_retention_days: 7,
  available_providers: ['yfinance', 'sec_edgar'],
  startup_error: null,
  secret_storage_mode: 'keychain',
}

test('stale zh locale is coerced to English on launch', async ({ page }) => {
  // Seed a stale 'zh' pref — main.tsx must force it back to 'en'.
  await page.addInitScript(() => {
    localStorage.setItem(
      'finrobot-ui-prefs',
      JSON.stringify({ state: { locale: 'zh' }, version: 0 }),
    )
  })
  await page.route('**/api/settings', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SETTINGS) }),
  )
  await page.goto('/settings')

  // English section heading proves the stale 'zh' was coerced to 'en'.
  const section = page.locator('[data-section="aiModel"]')
  await section.scrollIntoViewIfNeeded()
  await expect(section.locator('.settings-section-title')).toHaveText('AI Model')
  await section.screenshot({ path: 'e2e/_locale-english-only.png' })
})
