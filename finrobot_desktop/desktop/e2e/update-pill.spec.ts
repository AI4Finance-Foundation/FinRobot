import { expect, test } from '@playwright/test'

// Visual self-check for the title-bar auto-update pill (UpdatePill). The pill is
// driven by useUpdaterStore, whose "available" state only occurs inside Tauri —
// so we force the store directly (same module singleton the app imports) and
// screenshot the titlebar in each phase.

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

async function setPhase(page: import('@playwright/test').Page, state: Record<string, unknown>) {
  await page.evaluate((s) => {
    ;(window as unknown as { __updaterStore: { setState: (v: unknown) => void } }).__updaterStore.setState(
      s,
    )
  }, state)
}

test('update pill — available then downloading', async ({ page }) => {
  await page.route('**/api/settings', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SETTINGS) }),
  )
  await page.goto('/settings')

  const titlebar = page.locator('[data-testid="titlebar"]')
  await expect(titlebar).toBeVisible()

  // Available — the clickable "Update to vX" pill.
  await setPhase(page, { phase: 'available', version: '1.3.0', notes: 'Bug fixes' })
  await expect(titlebar.locator('.tb-update-pill.is-available')).toBeVisible()
  await titlebar.screenshot({ path: 'e2e/_update-pill-available.png' })

  // Downloading — live progress, non-interactive.
  await setPhase(page, { phase: 'downloading', progress: 0.42 })
  await expect(titlebar.locator('.tb-update-pill.is-busy')).toBeVisible()
  await titlebar.screenshot({ path: 'e2e/_update-pill-downloading.png' })

  // Error — failed install offers retry.
  await setPhase(page, { phase: 'error', error: 'signature mismatch' })
  await expect(titlebar.locator('.tb-update-pill.is-error')).toBeVisible()
  await titlebar.screenshot({ path: 'e2e/_update-pill-error.png' })
})

test('mandatory update gate — full-screen block', async ({ page }) => {
  await page.route('**/api/settings', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SETTINGS) }),
  )
  await page.goto('/settings')
  await setPhase(page, { phase: 'available', version: '2.0.0', mandatory: true })
  await expect(page.locator('[role="alertdialog"]')).toBeVisible()
  await page.screenshot({ path: 'e2e/_update-gate-mandatory.png' })
})
