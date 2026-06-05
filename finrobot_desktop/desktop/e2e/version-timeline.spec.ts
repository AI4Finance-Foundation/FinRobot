import { test, type Page } from '@playwright/test'

// Visual self-check for the redesigned right-rail Version Timeline (spine + status
// dots, vN labels, NOW/ARCH pills, verdict + outcome badges). Stubs the artifact
// detail + a 6-version timeline whose semantics mirror the design reference
// (v6 NOW/BUY/WATCHING … v3 ARCH/BUY/FAILED … v1 ARCH/REVIEW/no-target) and
// screenshots just the rail in zh + en. Backend not required.

const V6 = 'art-v6-now'

const TIMELINE = [
  // newest → oldest; the rail numbers them v6..v1 from this order.
  { ver: 6, id: V6, created: '2026-06-04', target: 184.37, verdict: 'BUY', signal: 'watching', archived: false }, // prettier-ignore
  { ver: 5, id: 'art-v5', created: '2026-05-12', target: 168.2, verdict: 'BUY', signal: 'hit', archived: false }, // prettier-ignore
  { ver: 4, id: 'art-v4', created: '2026-04-02', target: 132.05, verdict: 'HOLD', signal: 'hit', archived: false }, // prettier-ignore
  { ver: 3, id: 'art-v3', created: '2026-02-21', target: 141.88, verdict: 'BUY', signal: 'failed', archived: true }, // prettier-ignore
  { ver: 2, id: 'art-v2', created: '2026-01-09', target: 118.49, verdict: 'HOLD', signal: 'hit', archived: true }, // prettier-ignore
  { ver: 1, id: 'art-v1', created: '2025-11-30', target: null, verdict: 'REVIEW', signal: 'watching', archived: true }, // prettier-ignore
].map((r) => ({
  id: r.id,
  ticker: 'NVDA',
  cross_tickers: [],
  type: 'equity_research',
  created_at: `${r.created}T14:00:00Z`,
  headline: `NVDA equity research v${r.ver}`,
  source: 'pipeline',
  archived: r.archived,
  entry_price: 150,
  target_price: r.target,
  target_date: null,
  signal: r.signal,
  verdict: r.verdict,
  tagline: null,
}))

const DETAIL = {
  id: V6,
  ticker: 'NVDA',
  type: 'equity_research',
  created_at: '2026-06-04T14:00:00Z',
  outputs: { structured: {} },
  inputs: {},
  assumptions: {},
  meta: {},
}

async function gotoReport(page: Page, locale: 'zh' | 'en') {
  await page.addInitScript((loc) => {
    localStorage.setItem(
      'finrobot-ui-prefs',
      JSON.stringify({ state: { locale: loc }, version: 0 }),
    )
  }, locale)
  // Anchor to the top-level /api/ path — a bare **/api/** glob also catches the
  // app's own Vite source module /src/api/client.ts and breaks bootstrap.
  await page.route('http://localhost:5173/api/**', (route) => {
    const url = route.request().url()
    if (url.includes('/timeline')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TIMELINE) }) // prettier-ignore
    }
    // VersionDiffBanner's semantic-diff fetch. Its URL ends in the current id,
    // so this MUST precede the detail branch. 404 → the banner renders its error
    // state (off-screen from the rail) instead of mapping an empty payload.
    if (/\/diff\//.test(url)) {
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    }
    if (/\/api\/artifacts\/art-v6-now(\?|$)/.test(url)) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL) }) // prettier-ignore
    }
    // Chart/data endpoints → JSON null so the chapter chart hooks short-circuit
    // (they guard `data ? … : []`); with `{}` they'd map an undefined field and
    // crash the shared error boundary, taking the rail down with them.
    if (/\/api\/(data|valuation)\//.test(url)) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
    }
    // Everything else (settings, markViewed, …) is irrelevant to the rail.
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
  await page.goto(`/stocks/NVDA/runs/${V6}`)
  await page.locator('[data-testid="report-right-rail"]').waitFor({ timeout: 12000 })
  await page.locator(`[data-testid="timeline-${V6}"]`).waitFor()
  await page.waitForTimeout(200)
}

test('version timeline — zh', async ({ page }) => {
  await gotoReport(page, 'zh')
  await page
    .locator('[data-testid="report-right-rail"]')
    .screenshot({ path: 'e2e/_version-timeline-zh.png' })
})

test('version timeline — en', async ({ page }) => {
  await gotoReport(page, 'en')
  await page
    .locator('[data-testid="report-right-rail"]')
    .screenshot({ path: 'e2e/_version-timeline-en.png' })
})
