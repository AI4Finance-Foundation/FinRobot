import { test, expect } from '@playwright/test'

// Visual harness for Coverage Table provenance (per-field SourcedNumber).
// Backend isn't required — the groups list + overview are stubbed so every
// numeric cell renders through SourcedNumber with a source popover, and the
// degraded cells show their inline caveat glyph.

const GROUPS = [
  {
    id: 'cov_demo',
    name: 'Mag7',
    description: null,
    is_system: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    member_count: 2,
  },
]

function row(over: Record<string, unknown> = {}) {
  return {
    ticker: 'AAPL',
    company: 'Apple Inc.',
    price: 200.12,
    change_pct_1d: 1.25,
    price_as_of: '2026-06-01T00:00:00Z',
    market_cap: 3.01e12,
    revenue_ttm: 391e9,
    ev_ebitda: 18.4,
    pe: 28.5,
    currency: 'USD',
    latest_verdict: 'BUY',
    target_price: 240,
    target_date: '2027-03-01T00:00:00Z',
    entry_price: 180,
    upside_to_target_live: 0.1993,
    signal: 'watching',
    run_count: 2,
    latest_artifact_id: 'art_aapl_eq',
    latest_type: 'equity_research',
    latest_at: '2026-04-01T00:00:00Z',
    run_status: null,
    run_error: null,
    needs_refresh: [],
    warnings: [],
    sources: {
      price: {
        provider: 'yfinance',
        as_of: '2026-06-01T00:00:00Z',
        fetched_at: '2026-06-02T08:00:00Z',
        formula_warning: '实时价缺失，用最近收盘价',
      },
      change_pct_1d: {
        provider: 'yfinance',
        as_of: '2026-06-01T00:00:00Z',
        fetched_at: '2026-06-02T08:00:00Z',
        formula_id: 'latest_session_change',
      },
      market_cap: {
        provider: 'yfinance',
        as_of: '2025-09-28T00:00:00Z',
        fetched_at: '2026-06-02T08:00:00Z',
        formula_id: 'market_cap',
      },
      revenue_ttm: {
        provider: 'yfinance',
        as_of: '2025-09-28T00:00:00Z',
        fetched_at: '2026-06-02T08:00:00Z',
      },
      ev_ebitda: {
        provider: 'yfinance',
        as_of: '2025-09-28T00:00:00Z',
        fetched_at: '2026-06-02T08:00:00Z',
        formula_id: 'ev_ebitda',
      },
      pe: {
        provider: 'yfinance',
        as_of: '2025-09-28T00:00:00Z',
        fetched_at: '2026-06-02T08:00:00Z',
        formula_id: 'pe_ttm',
      },
      upside_to_target_live: {
        formula_id: 'upside_to_target_live',
        as_of: '2026-04-01T00:00:00Z',
        artifact_id: 'art_aapl_eq',
      },
    },
    ...over,
  }
}

const OVERVIEW = {
  group_id: 'cov_demo',
  group_name: 'Mag7',
  generated_at: '2026-06-02T08:00:00Z',
  partial: true,
  rows: [
    row(),
    row({
      ticker: 'NVDA',
      company: 'NVIDIA Corp.',
      price: 1024.5,
      change_pct_1d: -2.1,
      market_cap: 2.5e12,
      revenue_ttm: 110e9,
      ev_ebitda: 42.7,
      pe: 65.2,
      latest_verdict: 'HOLD',
      target_price: 1100,
      upside_to_target_live: 0.0737,
      latest_artifact_id: 'art_nvda_eq',
      // TTM-lagged P/E → caveat surfaces on the P/E cell.
      sources: {
        price: {
          provider: 'yfinance',
          as_of: '2026-06-01T00:00:00Z',
          fetched_at: '2026-06-02T08:00:00Z',
        },
        change_pct_1d: { provider: 'yfinance', formula_id: 'latest_session_change' },
        market_cap: { provider: 'yfinance', formula_id: 'market_cap' },
        revenue_ttm: { provider: 'yfinance' },
        ev_ebitda: { provider: 'yfinance', formula_id: 'ev_ebitda' },
        pe: {
          provider: 'yfinance',
          as_of: '2025-04-28T00:00:00Z',
          fetched_at: '2026-06-02T08:00:00Z',
          formula_id: 'pe_ttm',
          formula_warning: 'TTM 口径滞后(P/E 分母)',
        },
        upside_to_target_live: {
          formula_id: 'upside_to_target_live',
          as_of: '2026-04-01T00:00:00Z',
          artifact_id: 'art_nvda_eq',
        },
      },
    }),
  ],
}

test('coverage table renders per-field provenance + popover', async ({ page }) => {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  await page.route('**/api/coverage/groups/*/overview**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) }),
  )

  await page.goto('/coverage')
  await expect(page.getByRole('button', { name: 'AAPL' })).toBeVisible({ timeout: 8000 })

  // Whole table — dotted-underline sourced cells + inline caveat glyphs.
  await page.screenshot({ path: 'e2e/_coverage-provenance.png' })

  // Open the AAPL price popover (provider + as_of vs fetched_at).
  await page.getByText('$200.12').hover()
  await page.waitForTimeout(350)
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.screenshot({ path: 'e2e/_coverage-popover.png' })
})

// Fast skeleton: research/run fields real, market fields null + fast:true.
function skeletonRow(over: Record<string, unknown> = {}) {
  return {
    ...row(over),
    price: null,
    change_pct_1d: null,
    market_cap: null,
    revenue_ttm: null,
    ev_ebitda: null,
    pe: null,
    upside_to_target_live: null,
    signal: null,
    sources: {
      price: null,
      change_pct_1d: null,
      market_cap: null,
      revenue_ttm: null,
      ev_ebitda: null,
      pe: null,
      upside_to_target_live: null,
    },
    ...over,
  }
}

const FAST_OVERVIEW = {
  group_id: 'cov_demo',
  group_name: 'Mag7',
  generated_at: '2026-06-02T08:00:00Z',
  partial: false,
  fast: true,
  rows: [skeletonRow(), skeletonRow({ ticker: 'NVDA', company: 'NVIDIA Corp.', latest_verdict: 'HOLD' })],
}

test('fast skeleton paints research instantly with market cells shimmering', async ({ page }) => {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  // fast=true returns instantly; the full fetch is delayed so the skeleton stays
  // on screen long enough to capture.
  await page.route('**/api/coverage/groups/*/overview**', async (route) => {
    if (route.request().url().includes('fast=true')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(FAST_OVERVIEW),
      })
    } else {
      await new Promise((resolve) => setTimeout(resolve, 2500))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(OVERVIEW),
      })
    }
  })

  await page.goto('/coverage')
  // Research side (verdict) is real immediately; market cells are shimmering.
  await expect(page.getByText('BUY')).toBeVisible({ timeout: 8000 })
  await expect(page.getByRole('img', { name: 'loading' }).first()).toBeVisible()
  await page.screenshot({ path: 'e2e/_coverage-skeleton.png' })

  // Once the full fetch lands, real prices replace the shimmer.
  await expect(page.getByText('$200.12')).toBeVisible({ timeout: 8000 })
  await expect(page.getByRole('img', { name: 'loading' })).toHaveCount(0)
})

test('column menu hides a column and it persists in the table', async ({ page }) => {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  await page.route('**/api/coverage/groups/*/overview**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) }),
  )

  await page.goto('/coverage')
  await expect(page.getByRole('button', { name: 'AAPL' })).toBeVisible({ timeout: 8000 })
  // P/E column present initially.
  await expect(page.getByRole('button', { name: /P\/E/ })).toBeVisible()

  // Open the column menu, uncheck P/E (scope to the menu — the sort header's
  // aria-label also contains "P/E").
  await page.getByRole('button', { name: /列|Columns/ }).click()
  await page.getByRole('menu').getByLabel('P/E', { exact: true }).uncheck()

  // P/E column header is gone from the table.
  await expect(page.getByRole('button', { name: /Sort by P\/E|按 P\/E/ })).toHaveCount(0)
  await page.screenshot({ path: 'e2e/_coverage-columns.png' })
})

test('clicking a column header sorts the table (NVDA price > AAPL → top)', async ({ page }) => {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  await page.route('**/api/coverage/groups/*/overview**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) }),
  )

  await page.goto('/coverage')
  await expect(page.getByRole('button', { name: 'AAPL' })).toBeVisible({ timeout: 8000 })

  // Click the Price header → default desc → NVDA (1024.5) sorts above AAPL (200.12).
  await page.getByRole('button', { name: /价格|Price/ }).click()
  await page.waitForTimeout(150)

  const firstTicker = page.locator('tbody tr').first().getByRole('button')
  await expect(firstTicker.first()).toHaveText('NVDA')
  await page.screenshot({ path: 'e2e/_coverage-sorted.png' })
})
