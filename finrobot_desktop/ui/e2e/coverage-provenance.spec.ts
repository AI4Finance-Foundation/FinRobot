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
