import { test, type Page } from '@playwright/test'

// Visual self-check for the workspace back strip (WorkspaceBackBar) that
// replaced the FINROBOT › STOCKS › TSLA breadcrumb: a single ← that is pinned
// (position: sticky) so it survives scrolling, and a full-page not-found view
// whose back strip + CTA both route into search. Stubs /api/data so the hero
// renders; backend not required.

const PRICE = {
  ticker: 'AAPL',
  current_price: 201.45,
  change: 2.13,
  change_pct: 1.07,
  market_cap: 3_100_000_000_000,
  company_name: 'Apple Inc.',
  exchange: 'NasdaqGS',
  fetched_at: '2026-06-05T14:00:00Z',
  as_of: '2026-06-05',
  session_state: 'live',
  history: [],
}

async function setLocale(page: Page, locale: 'zh' | 'en') {
  await page.addInitScript((loc) => {
    localStorage.setItem('finrobot-ui-prefs', JSON.stringify({ state: { locale: loc }, version: 0 }))
  }, locale)
}

async function stubApi(page: Page, opts: { priceStatus: number }) {
  await page.route('http://localhost:5173/api/**', (route) => {
    const url = route.request().url()
    if (/\/api\/data\/[^/]+\/price/.test(url)) {
      if (opts.priceStatus !== 200) {
        return route.fulfill({ status: opts.priceStatus, contentType: 'application/json', body: '{"detail":"invalid"}' }) // prettier-ignore
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PRICE) }) // prettier-ignore
    }
    // Timelines / lists → empty arrays so the AI column lands in cold state.
    if (/\/(timeline|studied-tickers|recent-research|catalysts)/.test(url)) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
}

test('back bar — workspace top (zh)', async ({ page }) => {
  await setLocale(page, 'zh')
  await stubApi(page, { priceStatus: 200 })
  await page.goto('/stocks/AAPL')
  await page.locator('[data-testid="workspace-back"]').waitFor({ timeout: 12000 })
  await page.locator('[data-testid="ticker-hero"]').waitFor()
  await page.waitForTimeout(200)
  await page.screenshot({ path: 'e2e/_back-bar-workspace-zh.png' })
})

test('back bar — workspace top (en)', async ({ page }) => {
  await setLocale(page, 'en')
  await stubApi(page, { priceStatus: 200 })
  await page.goto('/stocks/AAPL')
  await page.locator('[data-testid="workspace-back"]').waitFor({ timeout: 12000 })
  await page.waitForTimeout(200)
  await page.screenshot({ path: 'e2e/_back-bar-workspace-en.png' })
})

test('back bar — stays pinned after scroll', async ({ page }) => {
  await setLocale(page, 'zh')
  await stubApi(page, { priceStatus: 200 })
  await page.goto('/stocks/AAPL')
  await page.locator('[data-testid="workspace-back"]').waitFor({ timeout: 12000 })
  await page.locator('#main-scroll').evaluate((el) => (el.scrollTop = 400))
  await page.waitForTimeout(200)
  await page.screenshot({ path: 'e2e/_back-bar-scrolled.png' })
})

test('back bar — not-found view (zh)', async ({ page }) => {
  await setLocale(page, 'zh')
  await stubApi(page, { priceStatus: 422 })
  await page.goto('/stocks/NOTAREALTICKER')
  await page.locator('[data-testid="ticker-not-found"]').waitFor({ timeout: 12000 })
  await page.waitForTimeout(200)
  await page.screenshot({ path: 'e2e/_back-bar-notfound-zh.png' })
})
