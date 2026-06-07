import { test, expect } from '@playwright/test'

// Visual check for the Coverage card's reverse-DCF "market-implied" line.
// Backend stubbed (page.route) so each market_implied state renders
// deterministically: fundamental (implied growth), option_value (priced on
// optionality), near_ceiling (WACC-sensitive), and a no-DCF control (no line).

test.use({ viewport: { width: 1280, height: 900 } })

const GROUPS = [
  {
    id: 'cov_demo',
    name: 'Studied Tickers',
    description: null,
    is_system: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    member_count: 4,
  },
]

function src(extra: Record<string, unknown> = {}) {
  return {
    provider: 'yfinance',
    as_of: '2026-06-01T00:00:00Z',
    fetched_at: '2026-06-02T08:00:00Z',
    ...extra,
  }
}

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
    artifact_count: 5,
    research_count: 5,
    latest_artifact_id: 'art_eq',
    latest_type: 'equity_research',
    latest_at: '2026-04-01T00:00:00Z',
    run_status: null,
    run_error: null,
    market_implied: null,
    needs_refresh: [],
    warnings: [],
    sources: {
      price: src(),
      change_pct_1d: src({ formula_id: 'latest_session_change' }),
      market_cap: src({ formula_id: 'market_cap' }),
      revenue_ttm: src(),
      ev_ebitda: src({ formula_id: 'ev_ebitda' }),
      pe: src({ formula_id: 'pe_ttm' }),
      upside_to_target_live: {
        formula_id: 'upside_to_target_live',
        as_of: '2026-04-01T00:00:00Z',
        artifact_id: 'art_eq',
      },
      market_implied: {
        formula_id: 'market_implied_nature',
        as_of: '2026-04-01T00:00:00Z',
        artifact_id: 'art_eq',
      },
    },
    ...over,
  }
}

const OVERVIEW = {
  group_id: 'cov_demo',
  group_name: 'Studied Tickers',
  generated_at: '2026-06-02T08:00:00Z',
  partial: false,
  rows: [
    // fundamental — implied growth is explainable, shown as per-name context.
    row({
      ticker: 'NVDA',
      company: 'NVIDIA Corp.',
      price: 1024.5,
      market_implied: {
        kind: 'fundamental',
        implied_growth: 0.281,
        implied_wacc: 0.092,
        horizon_years: 5,
        growth_ceiling: null,
        ceiling_price: null,
      },
    }),
    // option_value — no growth reaches the price, even at a lower WACC.
    row({
      ticker: 'TSLA',
      company: 'Tesla Inc.',
      price: 418.0,
      market_implied: {
        kind: 'option_value',
        implied_growth: null,
        implied_wacc: null,
        horizon_years: 5,
        growth_ceiling: 0.5,
        ceiling_price: 65.0,
      },
    }),
    // near_ceiling — unreachable at own WACC but a lower plausible WACC rescues it.
    row({
      ticker: 'AMD',
      company: 'Advanced Micro Devices',
      price: 168.0,
      market_implied: {
        kind: 'near_ceiling',
        implied_growth: null,
        implied_wacc: 0.103,
        horizon_years: 5,
        growth_ceiling: 0.5,
        ceiling_price: 160.0,
      },
    }),
    // control — no DCF artifact → no market-implied line at all.
    row({ ticker: 'KO', company: 'Coca-Cola Co.', price: 62.0, market_implied: null }),
  ],
}

async function stub(page: import('@playwright/test').Page) {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  await page.route('**/api/coverage/groups/*/overview**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) }),
  )
  await page.route('**/api/artifacts/by-ticker/*/timeline**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
}

test('coverage cards render the three market-implied states', async ({ page }) => {
  await stub(page)
  await page.goto('/coverage')
  await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 12000 })

  const nvda = page.getByTestId('coverage-card-NVDA')
  const tsla = page.getByTestId('coverage-card-TSLA')
  const amd = page.getByTestId('coverage-card-AMD')
  const ko = page.getByTestId('coverage-card-KO')
  await expect(nvda).toBeVisible()

  // fundamental → implied growth context; option_value / near_ceiling → flags.
  await expect(nvda.getByText(/28\.1%\/yr priced in/)).toBeVisible()
  await expect(tsla.getByText(/Option-value/)).toBeVisible()
  await expect(amd.getByText(/Near-ceiling/)).toBeVisible()

  // The no-DCF control shows no market-implied line.
  await expect(ko.getByText('Mkt implied')).toHaveCount(0)

  await page.screenshot({ path: 'e2e/_coverage-implied.png' })
  // Per-card close-ups so the line's copy + tone are legible.
  await nvda.screenshot({ path: 'e2e/_coverage-implied-nvda.png' })
  await tsla.screenshot({ path: 'e2e/_coverage-implied-tsla.png' })
  await amd.screenshot({ path: 'e2e/_coverage-implied-amd.png' })
  await ko.screenshot({ path: 'e2e/_coverage-implied-ko.png' })
})
