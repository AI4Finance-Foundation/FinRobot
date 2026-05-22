// Cosmic Stage A.2 + Stage B end-to-end walkthrough.
//
// Validates the activated "活的功能" path:
//   landing                    →  studied tickers table
//   click row                  →  /stocks/:ticker workspace
//   workspace MyResearchFeed   →  click a card
//   detail page                →  ArtifactDetailPage renders structured output
//
// All /api/* calls are stubbed via page.route so the test never needs a
// running backend; if you want to point at the real server, delete the
// route handlers and set PLAYWRIGHT_USE_BACKEND=1 then run vite dev with
// /api proxy.

import { test, expect } from '@playwright/test'

const SAMPLE_ARTIFACT_ID = 'art_2026-05-22_NVDA_equity_research'

test.beforeEach(async ({ page }) => {
  // ── Landing endpoints ─────────────────────────────────────────────────
  await page.route('**/api/dashboard/hit-rate*', async (route) =>
    route.fulfill({
      json: {
        window: 'all',
        sample_window_days: null,
        overall: { n_total: 4, n_closed: 2, n_hit: 1, hit_rate: 0.5 },
        by_verdict: {
          BUY: { n_total: 2, n_closed: 1, n_hit: 1, hit_rate: 1.0 },
          HOLD: { n_total: 1, n_closed: 0, n_hit: 0, hit_rate: null },
          SELL: { n_total: 1, n_closed: 1, n_hit: 0, hit_rate: 0.0 },
        },
        generated_at: '2026-05-22T00:00:00Z',
      },
    }),
  )

  await page.route('**/api/dashboard/recent-research*', async (route) =>
    route.fulfill({
      json: {
        items: [
          {
            artifact_id: SAMPLE_ARTIFACT_ID,
            ticker: 'NVDA',
            cross_tickers: [],
            type: 'equity_research',
            headline: 'BUY · target $920 — AI 算力超级周期受益者',
            verdict: 'BUY',
            entry_price: 866.0,
            target_price: 920.0,
            current_price: 905.0,
            delta_to_target_pct: 0.72,
            signal: 'watching',
            created_at: '2026-05-22T00:00:00Z',
            age_label: 'just now',
          },
        ],
        total_in_store: 1,
        generated_at: '2026-05-22T00:00:00Z',
      },
    }),
  )

  await page.route('**/api/artifacts/studied-tickers*', async (route) =>
    route.fulfill({
      json: {
        items: [
          {
            ticker: 'NVDA',
            run_count: 3,
            latest_created_at: '2026-05-22T00:00:00Z',
            latest_type: 'equity_research',
            latest_artifact_id: SAMPLE_ARTIFACT_ID,
            latest_target_price: 920.0,
            latest_entry_price: 866.0,
            latest_signal: 'watching',
            types: ['equity_research', 'dcf', 'lbo'],
          },
        ],
        generated_at: '2026-05-22T00:00:00Z',
      },
    }),
  )

  // ── Workspace endpoints ───────────────────────────────────────────────
  await page.route('**/api/artifacts/by-ticker/**/timeline*', async (route) =>
    route.fulfill({
      json: [
        {
          id: SAMPLE_ARTIFACT_ID,
          ticker: 'NVDA',
          cross_tickers: [],
          type: 'equity_research',
          created_at: '2026-05-22T00:00:00Z',
          headline: 'BUY · target $920 — AI 算力超级周期受益者',
          source: 'pipeline:equity_research',
          archived: false,
          entry_price: 866,
          target_price: 920,
          target_date: '2027-05-22T00:00:00Z',
          signal: 'watching',
        },
      ],
    }),
  )

  await page.route(`**/api/artifacts/${SAMPLE_ARTIFACT_ID}`, async (route) =>
    route.fulfill({
      json: {
        id: SAMPLE_ARTIFACT_ID,
        ticker: 'NVDA',
        type: 'equity_research',
        created_at: '2026-05-22T00:00:00Z',
        inputs: {
          data_source: 'yfinance',
          data_fetched_at: '2026-05-22T00:00:00Z',
          raw_data: {
            market: { current_price: 905, market_cap: 2.2e12 },
            income: { revenue: 60e9 },
          },
        },
        assumptions: {
          parameters: {
            wacc: 0.082,
            terminal_growth_rate: 0.025,
          },
        },
        compute_version: {
          version: '0.1.0',
          git_commit: 'abc1234',
          formula_id: 'equity_research_dcf_standard_with_da_v2',
          formula_warnings: [],
        },
        outputs: {
          structured: {
            thesis: {
              recommendation: 'BUY',
              price_target: 920,
              tagline:
                'NVDA · AI 算力超级周期受益者，估值仍有 6% 上行空间',
              key_takeaways: [
                '数据中心营收增速 50%+ YoY',
                '毛利率扩张至 78%',
                'Hopper → Blackwell 过渡顺利',
              ],
              valuation_overview:
                'DCF $920 / Comps $880 / DDM N/A · 加权目标 $920',
            },
          },
          summary_text: 'BUY thesis · target $920',
          warnings: [],
        },
        meta: {
          created_at: '2026-05-22T00:00:00Z',
          source: 'pipeline:equity_research',
        },
      },
    }),
  )

  await page.route('**/api/valuation/aggregate/*', async (route) =>
    route.fulfill({
      json: {
        ticker: 'NVDA',
        current_price: 905,
        as_of: '2026-05-22T00:00:00Z',
        methods: [
          {
            method: 'dcf',
            method_type: 'valuation',
            low: 850,
            mid: 920,
            high: 990,
            confidence: 0.85,
            source: 'monte_carlo',
            warnings: [],
          },
        ],
        warnings: [],
      },
    }),
  )

  await page.route('**/api/valuation/historical-bands/*', async (route) =>
    route.fulfill({
      json: {
        ticker: 'NVDA',
        metric: 'ev_ebitda',
        current: 40,
        median: 32,
        p25: 28,
        p75: 36,
        p90: 38,
        timeline: [{ date: '2026-01-01', value: 40 }],
        sample_count: 1,
        classification: 'expensive',
        warnings: [],
      },
    }),
  )

  await page.route('**/api/sentiment/*', async (route) =>
    route.fulfill({
      json: {
        ticker: 'NVDA',
        days: 7,
        available: true,
        coverage: '2/3',
        bullish_pct: 70,
        bearish_pct: 30,
        average_buzz: 150,
        source_alignment: 'aligned',
        sources: [],
        warnings: [],
      },
    }),
  )

  await page.route('**/api/data/*/price*', async (route) =>
    route.fulfill({
      json: {
        ticker: 'NVDA',
        current_price: 905,
        change: 8.5,
        change_pct: 0.95,
        market_cap: 2.2e12,
        company_name: 'NVIDIA Corp',
        exchange: 'NasdaqGS',
        next_earnings_date: '2026-08-15',
        history: Array.from({ length: 60 }, (_, i) => ({
          date: `2026-${String(Math.floor(i / 28) + 3).padStart(2, '0')}-${String((i % 28) + 1).padStart(2, '0')}`,
          close: 850 + i,
          open: 850 + i,
          high: 860 + i,
          low: 845 + i,
          volume: 1e7,
        })),
      },
    }),
  )

  await page.route('**/api/data/*/news', async (route) =>
    route.fulfill({ json: { items: [], overall_sentiment: 0 } }),
  )
  await page.route('**/api/data/*/catalysts', async (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/data/*/financials', async (route) =>
    route.fulfill({ json: { market: { market_cap: 2.2e12, pe_ratio: 50 } } }),
  )
  await page.route('**/api/data/*/quarterly', async (route) =>
    route.fulfill({ json: { quarters: [] } }),
  )
  await page.route('**/api/compute/**', async (route) =>
    route.fulfill({ json: {} }),
  )
  await page.route('**/api/data/sources/status', async (route) =>
    route.fulfill({ json: { sources: [] } }),
  )
  await page.route('**/api/search*', async (route) =>
    route.fulfill({ json: { query: '', results: [] } }),
  )
})

test('cosmic research flow · landing → studied → workspace → detail', async ({
  page,
}) => {
  // ── 1. Land on /stocks ─────────────────────────────────────────────
  await page.goto('/stocks')
  await page.waitForSelector('[data-testid="stocks-landing"]')

  // Hit-rate banner shows the stubbed 50% overall hit-rate.
  await expect(page.getByTestId('hit-rate-banner')).toBeVisible()
  await expect(page.getByTestId('hit-rate-banner')).toContainText('50.0%')

  // Studied tickers table shows NVDA row with 3 runs.
  await expect(page.getByTestId('studied-tickers-table')).toBeVisible()
  await expect(page.getByTestId('studied-tickers-table')).toContainText('NVDA')
  await page.screenshot({
    path: '../docs/cosmic-screenshots/01-landing.png',
    fullPage: true,
  })

  // ── 2. Click ticker → workspace ────────────────────────────────────
  // The table renders 6 buttons per row (one per column); first one is
  // labelled aria "View NVDA".
  await page.getByRole('button', { name: /View NVDA/i }).first().click()
  await page.waitForURL(/\/stocks\/NVDA$/)
  await page.waitForSelector('[data-testid="ticker-hero"]')

  // Cosmic hero: BUY badge + tagline + key takeaways.
  await expect(page.getByTestId('hero-verdict-badge')).toBeVisible()
  await expect(page.getByTestId('hero-verdict-badge')).toContainText('BUY')
  await page.screenshot({
    path: '../docs/cosmic-screenshots/02-workspace-hero.png',
    fullPage: true,
  })

  // ── 3. Scroll to MyResearchFeed and click the artifact card ─────────
  await page.locator('#sec-research').scrollIntoViewIfNeeded()
  await page.waitForSelector(`[data-testid="artifact-card-${SAMPLE_ARTIFACT_ID}"]`)
  await page.screenshot({
    path: '../docs/cosmic-screenshots/03-my-research.png',
    fullPage: true,
  })
  await page.getByTestId(`artifact-card-${SAMPLE_ARTIFACT_ID}`).click()

  // ── 4. ArtifactDetailPage renders ──────────────────────────────────
  await page.waitForURL(/\/stocks\/NVDA\/runs\//)
  await expect(page.getByText('NVDA · AI 完整研报')).toBeVisible()
  // structured output panel surfaces the BUY thesis dict (tagline value
  // shows up as part of the recursive KvGrid render).
  await expect(page.getByText('AI 算力超级周期受益者')).toBeVisible()
  await page.screenshot({
    path: '../docs/cosmic-screenshots/04-artifact-detail.png',
    fullPage: true,
  })
})
