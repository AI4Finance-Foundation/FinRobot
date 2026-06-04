import { test, expect } from '@playwright/test'

// Visual + behaviour harness for the group-scoped track-record strip (UX-013).
// Backend stubbed. Verifies: the strip renders the portfolio hit-rate with scope
// + lookback, suppresses the percentage below the closed-call threshold, and
// surfaces the sampled disclosure.

test.use({ viewport: { width: 1400, height: 900 } })

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

function row(ticker: string, company: string) {
  return {
    ticker,
    company,
    price: 200,
    change_pct_1d: 1,
    price_as_of: '2026-06-01T00:00:00Z',
    market_cap: 1e12,
    revenue_ttm: 1e11,
    ev_ebitda: 18,
    pe: 25,
    currency: 'USD',
    latest_verdict: 'BUY',
    target_price: 240,
    target_date: '2027-03-01T00:00:00Z',
    entry_price: 180,
    upside_to_target_live: 0.2,
    signal: 'watching',
    artifact_count: 2,
    research_count: 2,
    latest_artifact_id: 'art_x',
    latest_type: 'equity_research',
    latest_at: '2026-04-01T00:00:00Z',
    run_status: null,
    run_error: null,
    needs_refresh: [],
    warnings: [],
    sources: {},
  }
}

const OVERVIEW = {
  group_id: 'cov_demo',
  group_name: 'Studied Tickers',
  generated_at: '2026-06-02T08:00:00Z',
  partial: false,
  rows: [row('AAPL', 'Apple Inc.'), row('NVDA', 'NVIDIA Corp.'), row('MSFT', 'Microsoft Corp.')],
}

function hitRate(over: Record<string, unknown> = {}) {
  return {
    window: 'all',
    overall: { n_total: 20, n_closed: 14, n_hit: 9, hit_rate: 0.642857 },
    by_verdict: {
      BUY: { n_total: 12, n_closed: 8, n_hit: 6, hit_rate: 0.75 },
      HOLD: { n_total: 5, n_closed: 4, n_hit: 2, hit_rate: 0.5 },
      SELL: { n_total: 3, n_closed: 2, n_hit: 1, hit_rate: 0.5 },
    },
    generated_at: '2026-06-02T08:00:00Z',
    is_sampled: false,
    sample_size: 200,
    ...over,
  }
}

async function stub(page: import('@playwright/test').Page, hr: Record<string, unknown>) {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  await page.route('**/api/coverage/groups/*/overview**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) }),
  )
  await page.route('**/api/artifacts/by-ticker/*/timeline**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/dashboard/hit-rate**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(hr) }),
  )
}

test('trust strip shows the group-scoped hit rate with scope + lookback', async ({ page }) => {
  await stub(page, hitRate())
  await page.goto('/coverage')
  const strip = page.getByTestId('coverage-trust-strip')
  await expect(strip).toBeVisible({ timeout: 8000 })
  await expect(strip).toContainText('Studied Tickers')
  await expect(strip).toContainText('64%') // 9/14 rounded
  await expect(strip).toContainText(/9\/14/)
  await page.screenshot({ path: 'e2e/_trust-strip.png' })
})

test('below the closed-call threshold the percentage is suppressed (no false precision)', async ({
  page,
}) => {
  await stub(
    page,
    hitRate({
      overall: { n_total: 4, n_closed: 2, n_hit: 2, hit_rate: 1.0 },
      by_verdict: {
        BUY: { n_total: 4, n_closed: 2, n_hit: 2, hit_rate: 1.0 },
        HOLD: { n_total: 0, n_closed: 0, n_hit: 0, hit_rate: null },
        SELL: { n_total: 0, n_closed: 0, n_hit: 0, hit_rate: null },
      },
    }),
  )
  await page.goto('/coverage')
  const strip = page.getByTestId('coverage-trust-strip')
  await expect(strip).toBeVisible({ timeout: 8000 })
  // A "100%" from 2 closed calls must NOT appear.
  await expect(strip).not.toContainText('100%')
  await expect(strip).toContainText('2') // discloses the closed-call count instead
  await page.screenshot({ path: 'e2e/_trust-strip-insufficient.png' })
})

test('sampled record discloses "based on latest N"', async ({ page }) => {
  await stub(page, hitRate({ is_sampled: true, sample_size: 200 }))
  await page.goto('/coverage')
  const strip = page.getByTestId('coverage-trust-strip')
  await expect(strip).toBeVisible({ timeout: 8000 })
  await expect(strip).toContainText(/200/)
})
