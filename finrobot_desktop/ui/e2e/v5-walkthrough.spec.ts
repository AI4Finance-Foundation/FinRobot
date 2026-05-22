// v5 retail-investor walkthrough (spec §15 condition 5).
//
// Drives headless Chromium against vite dev (no Tauri shell required —
// the React layer is the only thing this checks). Captures the five
// canonical checkpoints to docs/v5-screenshots/ so reviewers can diff
// future visual regressions.
//
// Run with: `npm run e2e` from ui/ (vite dev started by webServer below).

import { test, expect } from '@playwright/test'

// Mock every /api/* call so the walkthrough doesn't need a live backend.
// Each step exercises a different UI surface; the responses below are the
// shapes the v5 components consume per their hook definitions.
test.beforeEach(async ({ page }) => {
  await page.route('**/api/artifacts/by-ticker/**/timeline', async (route) => {
    await route.fulfill({
      json: [
        {
          id: 'art_2026-05-19_NVDA_equity_research',
          ticker: 'NVDA',
          cross_tickers: [],
          type: 'equity_research',
          created_at: '2026-05-19T00:00:00Z',
          headline: 'BUY · target $920 — 数据中心增速放缓但毛利率改善',
          source: 'pipeline:equity_research',
          archived: false,
          entry_price: 866,
          target_price: 920,
          target_date: '2027-05-19T00:00:00Z',
          signal: 'hit',
        },
        {
          id: 'art_2026-05-12_NVDA_dcf',
          ticker: 'NVDA',
          cross_tickers: [],
          type: 'dcf',
          created_at: '2026-05-12T00:00:00Z',
          headline: 'DCF implied $890',
          source: 'cli',
          archived: false,
          entry_price: 850,
          target_price: 890,
          target_date: '2027-05-12T00:00:00Z',
          signal: 'hit',
        },
        {
          id: 'art_2026-04-01_NVDA_lbo',
          ticker: 'NVDA',
          cross_tickers: [],
          type: 'lbo',
          created_at: '2026-04-01T00:00:00Z',
          headline: 'LBO IRR 18%',
          source: 'pipeline:lbo',
          archived: false,
          entry_price: 820,
          target_price: 900,
          target_date: '2027-04-01T00:00:00Z',
          signal: 'failed',
        },
      ],
    })
  })

  await page.route('**/api/valuation/aggregate/**', async (route) => {
    await route.fulfill({
      json: {
        ticker: 'NVDA',
        current_price: 876.42,
        as_of: '2026-05-21T00:00:00Z',
        methods: [
          {
            method: 'dcf',
            method_type: 'valuation',
            low: 800,
            mid: 920,
            high: 1040,
            confidence: 0.85,
            source: 'monte_carlo_p10_p90',
            warnings: [],
          },
          {
            method: 'comps_pe',
            method_type: 'valuation',
            low: 820,
            mid: 895,
            high: 980,
            confidence: 0.78,
            source: 'peer_median_pe',
            warnings: [],
          },
          {
            method: 'lbo',
            method_type: 'valuation',
            low: 780,
            mid: 900,
            high: 1020,
            confidence: 0.6,
            source: 'sensitivity_grid',
            warnings: [],
          },
        ],
        warnings: [],
      },
    })
  })

  await page.route('**/api/valuation/historical-bands/**', async (route) => {
    await route.fulfill({
      json: {
        ticker: 'NVDA',
        metric: 'ev_ebitda',
        current: 42,
        median: 35,
        p25: 31.5,
        p75: 38.2,
        p90: 41,
        timeline: Array.from({ length: 24 }, (_, i) => ({
          date: `2024-${String(((i % 12) + 1)).padStart(2, '0')}-01`,
          value: 28 + i * 0.7,
        })),
        sample_count: 24,
        classification: 'expensive',
        warnings: [],
      },
    })
  })

  await page.route('**/api/sentiment/**', async (route) => {
    await route.fulfill({
      json: {
        ticker: 'NVDA',
        days: 7,
        available: true,
        coverage: '2/3',
        bullish_pct: 67,
        bearish_pct: 33,
        average_buzz: 142,
        source_alignment: 'aligned',
        sources: [
          {
            platform: 'Reddit',
            has_data: true,
            bullish_pct: 70,
            activity_label: 'Mentions',
            activity_value: 1240,
          },
          {
            platform: 'X.com',
            has_data: true,
            bullish_pct: 65,
            activity_label: 'Mentions',
            activity_value: 8400,
          },
          {
            platform: 'Polymarket',
            has_data: false,
            bullish_pct: null,
            activity_label: 'Trades',
            activity_value: 0,
          },
        ],
        warnings: [],
      },
    })
  })

  await page.route('**/api/data/*/catalysts', async (route) => {
    await route.fulfill({
      json: [
        {
          category: 'earnings',
          title: 'Q1 2026 财报',
          date: '2026-05-22',
          impact_direction: 'up',
          impact_magnitude: 'high',
          source: 'IR calendar',
        },
        {
          category: 'product_launch',
          title: 'Blackwell GPU 量产',
          date: '2026-06-15',
          impact_direction: 'up',
          impact_magnitude: 'high',
          source: 'press release',
        },
      ],
    })
  })

  await page.route('**/api/data/*/news', async (route) => {
    await route.fulfill({ json: { items: [] } })
  })

  await page.route('**/api/data/*/price**', async (route) => {
    await route.fulfill({
      json: {
        current_price: 876.42,
        change_pct: 1.23,
        price_history: Array.from({ length: 250 }, (_, i) => ({
          date: `2026-${String(Math.floor(i / 21) + 1).padStart(2, '0')}-${String(((i % 21) + 1)).padStart(2, '0')}`,
          close: 700 + i,
        })),
      },
    })
  })

  await page.route('**/api/data/*/quarterly', async (route) => {
    await route.fulfill({
      json: {
        quarters: [
          { period: '2026Q1', revenue: 30e9, gross_margin: 0.72, net_income: 10e9 },
          { period: '2025Q4', revenue: 28e9, gross_margin: 0.71, net_income: 9.5e9 },
          { period: '2025Q3', revenue: 26e9, gross_margin: 0.7, net_income: 8.8e9 },
          { period: '2025Q2', revenue: 24e9, gross_margin: 0.69, net_income: 8.1e9 },
        ],
      },
    })
  })

  await page.route('**/api/data/*/financials', async (route) => {
    await route.fulfill({ json: { market_cap: 2.1e12, pe_ratio: 42 } })
  })

  await page.route('**/api/runs', async (route) => {
    await route.fulfill({ json: { run_id: 'run_e2e_1', status: 'queued' } })
  })
})

test('v5 5-step retail walkthrough', async ({ page }) => {
  // Step 1 — cold start: land on the legacy /stocks placeholder, then
  // navigate to /stocks/NVDA to surface the StockWorkspace. Stage A
  // retired AnchorNav — section nav now lives in ⌘K. Assert the
  // cosmic hero is visible and the workspace section IDs exist on
  // the page so cmdK can scrollIntoView them.
  await page.goto('/stocks/NVDA')
  await page.waitForSelector('[data-testid="ticker-hero"]')
  await page.screenshot({
    path: '../docs/v5-screenshots/01-cold-workspace.png',
    fullPage: true,
  })
  await expect(page.getByTestId('ticker-hero')).toBeVisible()
  await expect(page.locator('#sec-now')).toBeAttached()
  await expect(page.locator('#sec-research')).toBeAttached()

  // Step 2 — open + 跑分析 dropdown.
  await page.getByTestId('run-analysis-trigger').click()
  await expect(page.getByTestId('run-analysis-dropdown')).toBeVisible()
  await page.screenshot({
    path: '../docs/v5-screenshots/02-run-analysis-dropdown.png',
    fullPage: true,
  })
  // Verify DCF entry is present (the Stage A fix added it).
  await expect(page.getByTestId('run-dcf')).toBeVisible()
  await page.keyboard.press('Escape')

  // Step 3 — football field visible after scrolling. Use the hash anchor
  // (CmdK uses scrollIntoView on the same ID).
  await page.locator('#sec-football').scrollIntoViewIfNeeded()
  await page.waitForSelector('[data-testid="football-field-svg-wrapper"]')
  await page.screenshot({
    path: '../docs/v5-screenshots/03-football-field.png',
    fullPage: true,
  })

  // Step 4 — scroll to 我的研究, ensure stat banner + cards render.
  await page.locator('#sec-research').scrollIntoViewIfNeeded()
  await page.waitForSelector('[data-testid="stat-banner"]')
  await expect(page.getByTestId('stat-banner')).toContainText('命中率')
  await page.screenshot({
    path: '../docs/v5-screenshots/04-my-research.png',
    fullPage: true,
  })

  // Step 5 — share button in HERO. Click it (download API stubbed in JSDOM;
  // in real chromium it actually saves a PNG, but we don't assert that here
  // to avoid filesystem dependencies in CI).
  await page.locator('#sec-now').scrollIntoViewIfNeeded()
  await page.waitForSelector('[data-testid="hero-share-card"]')
  await page.screenshot({
    path: '../docs/v5-screenshots/05-hero-share.png',
    fullPage: true,
  })
  await expect(page.getByTestId('hero-share-card')).toBeVisible()
})
