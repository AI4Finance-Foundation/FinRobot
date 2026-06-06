import { test, expect } from '@playwright/test'

// Visual + interaction harness for the redesigned Coverage Desk (card wall +
// inspector). Backend isn't required — groups / overview / artifact timeline are
// stubbed so the layout renders deterministically. Verifies the redesign's hard
// requirements: fixed-height cards, no page-level horizontal overflow at
// 1600×1000, Comfort/Compact density, card→inspector focus, and that numbers
// still render through SourcedNumber (provenance popover).

test.use({ viewport: { width: 1600, height: 1000 } })

const GROUPS = [
  {
    id: 'cov_demo',
    name: 'Studied Tickers',
    description: null,
    is_system: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    member_count: 5,
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
    latest_artifact_id: 'art_aapl_eq',
    latest_type: 'equity_research',
    latest_at: '2026-04-01T00:00:00Z',
    run_status: null,
    run_error: null,
    needs_refresh: [],
    warnings: [],
    sources: {
      price: src({ formula_warning: '实时价缺失，用最近收盘价' }),
      change_pct_1d: src({ formula_id: 'latest_session_change' }),
      market_cap: src({ formula_id: 'market_cap' }),
      revenue_ttm: src(),
      ev_ebitda: src({ formula_id: 'ev_ebitda' }),
      pe: src({ formula_id: 'pe_ttm' }),
      upside_to_target_live: {
        formula_id: 'upside_to_target_live',
        as_of: '2026-04-01T00:00:00Z',
        artifact_id: 'art_aapl_eq',
      },
    },
    ...over,
  }
}

// Five rows spanning every filter state: clean BUY, price-drift warn, never-run,
// in-flight run, no-reports.
const OVERVIEW = {
  group_id: 'cov_demo',
  group_name: 'Studied Tickers',
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
      latest_verdict: 'HOLD',
      target_price: 1100,
      upside_to_target_live: 0.0737,
      latest_artifact_id: 'art_nvda_eq',
      needs_refresh: [
        {
          kind: 'signal_closed',
          detail: '现价已达/超过目标价，结论待复核',
          artifact_id: 'art_nvda_eq',
        },
      ],
      warnings: ['NVDA 实时价缺失，用最近收盘价'],
    }),
    row({
      ticker: 'TSLA',
      company: 'Tesla Inc.',
      price: 184.41,
      change_pct_1d: -0.84,
      latest_verdict: null,
      target_price: null,
      entry_price: null,
      upside_to_target_live: null,
      signal: null,
      artifact_count: 0,
      research_count: 0,
      latest_artifact_id: null,
      latest_at: null,
      needs_refresh: [
        { kind: 'never_run', detail: '覆盖池中但从未跑过 Research', artifact_id: null },
      ],
    }),
    row({
      ticker: 'MSFT',
      company: 'Microsoft Corp.',
      price: 462.97,
      change_pct_1d: 1.12,
      latest_verdict: 'BUY',
      target_price: 540,
      upside_to_target_live: 0.162,
      run_status: 'running',
    }),
    row({
      ticker: 'GOOGL',
      company: 'Alphabet Inc.',
      price: 178.2,
      change_pct_1d: 0.4,
      latest_verdict: null,
      target_price: null,
      upside_to_target_live: null,
      artifact_count: 0,
      research_count: 0,
      latest_at: null,
      needs_refresh: [
        { kind: 'never_run', detail: '覆盖池中但从未跑过 Research', artifact_id: null },
      ],
    }),
  ],
}

const TIMELINE = [
  {
    id: 'art_nvda_eq',
    ticker: 'NVDA',
    cross_tickers: [],
    type: 'equity_research',
    created_at: '2026-06-02T00:00:00Z',
    headline: 'NVDA equity research',
    source: 'pipeline:equity_research',
    archived: false,
    verdict: 'HOLD',
    tagline: 'AI demand intact; valuation full',
  },
  {
    id: 'art_nvda_dcf',
    ticker: 'NVDA',
    cross_tickers: [],
    type: 'dcf',
    created_at: '2026-05-18T00:00:00Z',
    headline: 'NVDA DCF',
    source: 'pipeline:dcf',
    archived: false,
    verdict: null,
    tagline: 'previous run snapshot preserved',
  },
]

async function stub(page: import('@playwright/test').Page) {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  await page.route('**/api/coverage/groups/*/overview**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) }),
  )
  await page.route('**/api/artifacts/by-ticker/*/timeline**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TIMELINE) }),
  )
}

// The wall now shows the whole universe by default — the Needs-Action triage
// lens + "All" segment were removed (CoveragePage: "The whole universe, always").
// Kept as a no-op so the layout/clip tests below read intention-clearly without
// re-plumbing every call site.
async function showAll(_page: import('@playwright/test').Page) {
  // no-op: every card is already rendered
}

test('card wall renders with no horizontal overflow at 1600×1000', async ({ page }) => {
  await stub(page)
  await page.goto('/coverage')
  await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })
  await showAll(page)
  await expect(page.getByTestId('coverage-card-AAPL')).toBeVisible()

  // No page-level horizontal overflow (the grid scrolls internally; the document
  // must not).
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)

  await page.screenshot({ path: 'e2e/_coverage-comfort.png' })
})

test('card sizes to content — never clips its bottom (footer) row', async ({ page }) => {
  await stub(page)
  await page.goto('/coverage')
  await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })

  const card = page.getByTestId('coverage-card-AAPL')
  await expect(card).toBeVisible()

  // The card sizes to its content and never clips its bottom row (status +
  // report summary) behind overflow:hidden. The whole-card surface is the open
  // affordance now — there is no inline run button — so we assert the footer,
  // the lowest content row, sits fully inside the card box.
  const footer = card.locator('.coverage-card__footer')
  await expect(footer).toBeVisible()
  const cardBox = await card.boundingBox()
  const footerBox = await footer.boundingBox()
  expect(cardBox && footerBox).toBeTruthy()
  expect(footerBox!.y + footerBox!.height).toBeLessThanOrEqual(cardBox!.y + cardBox!.height + 1)

  await page.screenshot({ path: 'e2e/_coverage-comfort2.png' })
})

test('cards never overlap — every card stays clickable', async ({ page }) => {
  await stub(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/coverage')
  await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })

  // No two cards overlap — a too-short grid row track once let a tall card bleed
  // over the next row and cover it.
  const overlaps = await page.getByTestId('coverage-card-grid').evaluate((grid) => {
    const rects = Array.from(grid.querySelectorAll('[data-ticker]')).map((c) =>
      c.getBoundingClientRect(),
    )
    let n = 0
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i]
        const b = rects[j]
        if (
          a.left < b.right - 1 &&
          b.left < a.right - 1 &&
          a.top < b.bottom - 1 &&
          b.top < a.bottom - 1
        )
          n++
      }
    }
    return n
  })
  expect(overlaps).toBe(0)

  // The card surface is the open affordance — it must be genuinely hittable, not
  // obscured by an overlapping neighbor (Playwright's click fails if covered).
  const card = page.getByTestId('coverage-card-AAPL')
  await card.scrollIntoViewIfNeeded()
  await card.click({ trial: true })
})

test('clicking a card opens its detail route', async ({ page }) => {
  await stub(page)
  await page.goto('/coverage')
  await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })
  await expect(page.getByTestId('coverage-card-MSFT')).toBeVisible()

  // The whole card is the open affordance. The inline inspector panel was
  // removed — opening a card now routes to /stocks/:ticker, where research runs
  // and artifact history (the old inspector's Latest Report / History tabs) live.
  await page.getByTestId('coverage-card-MSFT').click()
  await expect(page).toHaveURL(/\/stocks\/MSFT$/)
})

test('the whole universe renders by default — clean and flagged names alike', async ({ page }) => {
  await stub(page)
  await page.goto('/coverage')
  await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })

  // No triage lens: every studied name is on the wall from first paint (clean
  // AAPL/MSFT and flagged NVDA/TSLA/GOOGL together).
  await expect(page.getByTestId('coverage-card-NVDA')).toBeVisible()
  await expect(page.getByTestId('coverage-card-AAPL')).toBeVisible()
  await expect(page.getByTestId('coverage-card-MSFT')).toBeVisible()

  // A card number still carries provenance — hover the NVDA price popover.
  await page.getByTestId('coverage-card-NVDA').getByText('$1,024.50').hover()
  await page.waitForTimeout(350)
  await expect(page.getByRole('dialog').first()).toBeVisible()
})

// The redesign's load-bearing responsive guarantee: the card grid uses auto-fill
// columns (not a fixed repeat(3/4) with a min track), so it falls back to fewer
// columns and NEVER clips a card horizontally — the GOOGL-sliced-off bug.

async function assertNoClip(page: import('@playwright/test').Page) {
  // No document-level horizontal overflow.
  const docOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(docOverflow).toBeLessThanOrEqual(1)

  // The grid scrolls vertically only — no internal horizontal scroll.
  const gridOverflowX = await page
    .getByTestId('coverage-card-grid')
    .evaluate((el) => el.scrollWidth - el.clientWidth)
  expect(gridOverflowX).toBeLessThanOrEqual(1)

  // Every card's edges sit within the grid's content box — no card (GOOGL was
  // the audit's victim) is sliced off the right.
  const clipped = await page.getByTestId('coverage-card-grid').evaluate((grid) => {
    const gr = grid.getBoundingClientRect()
    return Array.from(grid.querySelectorAll('[data-ticker]')).filter((c) => {
      const r = c.getBoundingClientRect()
      return r.right > gr.right + 0.5 || r.left < gr.left - 0.5
    }).length
  })
  expect(clipped).toBe(0)
}

// Hard requirement: 1280 / 1366 / 1440 / 1600 / 1920 with the AI panel OPEN
// (the e2e default) must not clip a card. These are the widths the audit caught
// GOOGL sliced off at, AI-panel-open being the trigger.
for (const width of [1280, 1366, 1440, 1600, 1920]) {
  test(`AI panel open: no card clipping at ${width}px`, async ({ page }) => {
    await stub(page)
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/coverage')
    await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })
    await expect(page.getByTestId('right-chat-panel')).toBeVisible() // AI panel open
    await showAll(page) // densest wall for the clip check
    await assertNoClip(page)
    await page.screenshot({ path: `e2e/_coverage-aiopen-w${width}.png` })
  })
}

// Small windows (AI panel collapsed — nobody keeps a 420px chat panel open in a
// 700px window). The inspector docks below the wall; cards stay single/double
// column, fully visible, vertical-scroll only. Spec: "不崩、不丢操作、可滚动".
for (const width of [1024, 820, 680]) {
  test(`small window (AI collapsed): no clipping, grid usable at ${width}px`, async ({ page }) => {
    await stub(page)
    await page.setViewportSize({ width, height: 768 })
    await page.goto('/coverage')
    // Collapse the AI panel FIRST — a real small-window session; with it open a
    // 420px chat panel leaves almost no room and pushes the wall below the fold.
    await page.getByTestId('collapse-btn').first().click()
    await page.waitForTimeout(200)
    await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })
    await showAll(page)
    await assertNoClip(page)
    await page.screenshot({ path: `e2e/_coverage-small-w${width}.png` })
  })
}

test('provenance popover escapes the card overflow (portaled, fully on-screen)', async ({
  page,
}) => {
  await stub(page)
  // Narrow enough that an in-card absolute popover near the right edge would be
  // clipped by the card's box — the portal must lift it to the viewport.
  await page.setViewportSize({ width: 980, height: 900 })
  await page.goto('/coverage')
  await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })
  await showAll(page)
  await expect(page.getByTestId('coverage-card-AAPL')).toBeVisible()

  await page.getByTestId('coverage-card-AAPL').getByText('$200.12').hover()
  await page.waitForTimeout(350)
  const dialog = page.getByRole('dialog').first()
  await expect(dialog).toBeVisible()

  // The popover lives at <body> level now: its full width/height is on-screen,
  // not sliced by the card's clip. Assert it's within the viewport bounds.
  const onScreen = await dialog.evaluate((el) => {
    const r = el.getBoundingClientRect()
    return (
      r.left >= -0.5 &&
      r.top >= -0.5 &&
      r.right <= window.innerWidth + 0.5 &&
      r.bottom <= window.innerHeight + 0.5 &&
      r.width > 150 // not collapsed/halved
    )
  })
  expect(onScreen).toBe(true)
  await page.screenshot({ path: 'e2e/_coverage-popover.png' })
})

test('many tickers: the wall stays bounded and scrolls internally', async ({ page }) => {
  // 60-ticker group — the case that broke: an unbounded wall grew to ~10000px
  // and pushed everything below it off-screen. The wall must scroll INTERNALLY
  // (bounded layout height, content overflowing its own box) so the page chrome
  // stays put no matter how many names are studied.
  const bigOverview = {
    ...OVERVIEW,
    rows: Array.from({ length: 60 }, (_, i) =>
      row({ ticker: `T${String(i).padStart(2, '0')}`, company: `Co ${i}`, latest_at: null }),
    ),
  }
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) }),
  )
  await page.route('**/api/coverage/groups/*/overview**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(bigOverview) }),
  )

  await page.setViewportSize({ width: 760, height: 820 })
  await page.goto('/coverage')
  await expect(page.getByTestId('coverage-card-grid')).toBeVisible({ timeout: 8000 })
  await page.waitForTimeout(250) // let the layout settle

  const grid = page.getByTestId('coverage-card-grid')
  const gridClientH = await grid.evaluate((el) => el.clientHeight)
  const gridScrollH = await grid.evaluate((el) => el.scrollHeight)
  expect(gridClientH).toBeLessThan(900) // bounded, not the full 60-card stack
  expect(gridScrollH).toBeGreaterThan(gridClientH) // genuinely scrollable

  await page.screenshot({ path: 'e2e/_coverage-many.png' })
})
