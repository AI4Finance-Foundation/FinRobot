import { test, expect } from '@playwright/test'

// Visual + behaviour harness for the stale-while-revalidate Coverage Desk.
// Backend stubbed. Three market states the redesign must show distinctly:
//   * fresh      — network revalidate resolved, market_stale=false
//   * stale+busy — cache-only snapshot (market_stale=true) while the revalidate
//                  is still in flight → last-known numbers + "refreshing" pulse
//   * cold       — no snapshot yet (price null) → shimmer
// The app ships English-only (no language switcher; i18n.defaultLocale='en'), so
// this captures the en path every user sees; the zh catalog string exists and is
// consistent for when multi-language is re-enabled.

test.use({ viewport: { width: 1280, height: 900 } })

const GROUPS = [
  {
    id: 'cov_demo',
    name: 'Studied Tickers',
    description: null,
    is_system: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    member_count: 3,
  },
]

const src = (extra: Record<string, unknown> = {}) => ({
  provider: 'yfinance',
  as_of: '2026-06-04T00:00:00Z',
  fetched_at: '2026-06-04T08:00:00Z',
  ...extra,
})

function row(over: Record<string, unknown> = {}) {
  return {
    ticker: 'AAPL',
    company: 'Apple Inc.',
    price: 311.51,
    change_pct_1d: 0.84,
    price_as_of: '2026-06-04T00:00:00Z',
    market_cap: 4.56e12,
    revenue_ttm: 391e9,
    ev_ebitda: null,
    pe: 37.2,
    currency: 'USD',
    latest_verdict: 'BUY',
    target_price: 360,
    target_date: '2027-03-01T00:00:00Z',
    entry_price: 280,
    upside_to_target_live: 0.1556,
    signal: 'watching',
    artifact_count: 4,
    research_count: 4,
    latest_artifact_id: 'art_aapl',
    latest_type: 'equity_research',
    latest_at: '2026-04-01T00:00:00Z',
    run_status: null,
    run_error: null,
    market_stale: false,
    needs_refresh: [],
    warnings: [],
    sources: {
      price: src(),
      change_pct_1d: src({ formula_id: 'latest_session_change' }),
      market_cap: src({ formula_id: 'market_cap' }),
      revenue_ttm: src(),
      ev_ebitda: null,
      pe: src({ formula_id: 'pe_ttm' }),
      upside_to_target_live: {
        formula_id: 'upside_to_target_live',
        as_of: '2026-04-01T00:00:00Z',
        artifact_id: 'art_aapl',
      },
    },
    ...over,
  }
}

// Three cards: a stale snapshot (TSLA), a fresh one (AAPL), and a cold one (MU).
const STALE_ROWS = [
  row({ ticker: 'AAPL' }),
  row({
    ticker: 'TSLA',
    company: 'Tesla, Inc.',
    price: 391.82,
    pe: 383.1,
    market_cap: 1.48e12,
    market_stale: true,
    price_as_of: '2026-06-02T00:00:00Z',
    latest_verdict: 'HOLD',
  }),
  row({
    ticker: 'MU',
    company: 'Micron Technology',
    price: null,
    change_pct_1d: null,
    market_cap: null,
    revenue_ttm: null,
    pe: null,
    upside_to_target_live: null,
    market_stale: false,
    latest_verdict: null,
    sources: { price: null },
  }),
]

const FRESH_ROWS = STALE_ROWS.map((r) => ({ ...r, market_stale: false }))

async function setup(page: import('@playwright/test').Page, opts: { hangRevalidate: boolean }) {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  await page.route('**/api/coverage/groups/*/overview**', async (r) => {
    const isRefresh = r.request().url().includes('refresh=true')
    if (isRefresh && opts.hangRevalidate) {
      // Never resolve → the desk stays on the cache-only snapshot with the
      // revalidate in flight (stale + refreshing state).
      return
    }
    const rows = isRefresh ? FRESH_ROWS : STALE_ROWS
    await r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        group_id: 'cov_demo',
        group_name: 'Studied Tickers',
        rows,
        generated_at: '2026-06-04T08:00:00Z',
        partial: false,
        cache_only: !isRefresh,
      }),
    })
  })
}

test('coverage stale snapshot shows last-known + refreshing, cold shimmers', async ({ page }) => {
  await setup(page, { hangRevalidate: true })
  await page.goto('/coverage')
  await page.waitForSelector('[data-testid="coverage-card-AAPL"]')
  await page.waitForTimeout(400)

  // A row with a (stale) snapshot shows its last-known number — never a blank
  // shimmer — plus a refreshing affordance while the revalidate is in flight.
  const tsla = page.locator('[data-testid="coverage-card-TSLA"]')
  await expect(tsla).toContainText('391.82')
  await expect(tsla.locator('.coverage-card__provider')).toHaveAttribute('data-refreshing', 'true')
  // A genuinely cold row (no snapshot) shimmers instead.
  const mu = page.locator('[data-testid="coverage-card-MU"]')
  await expect(mu.locator('.skeleton').first()).toBeVisible()

  await page.screenshot({ path: 'e2e/_coverage-revalidate-busy.png' })
  await tsla.screenshot({ path: 'e2e/_coverage-revalidate-card.png' })
})

test('coverage fresh — revalidate resolved, no refreshing affordance', async ({ page }) => {
  await setup(page, { hangRevalidate: false })
  await page.goto('/coverage')
  await page.waitForSelector('[data-testid="coverage-card-AAPL"]')
  await page.waitForTimeout(600)

  const tsla = page.locator('[data-testid="coverage-card-TSLA"]')
  await expect(tsla).toContainText('391.82')
  await expect(tsla.locator('.coverage-card__provider')).not.toHaveAttribute(
    'data-refreshing',
    'true',
  )
  await page.screenshot({ path: 'e2e/_coverage-revalidate-fresh.png' })
})
