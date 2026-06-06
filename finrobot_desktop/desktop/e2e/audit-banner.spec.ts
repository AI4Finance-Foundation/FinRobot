import { test, type Page } from '@playwright/test'

// Visual self-check for the numeric-audit banner (ChapterAuditBanner). Stubs an
// artifact detail whose outputs.structured.numeric_audit flags a bank EV
// (blocked_field, withholds valuation) + a loss-maker P/E (review). Backend not
// required. The banner renders at the top of the report body when
// artifact_status !== "publishable".

const ID = 'art-audit-demo'

const DETAIL = {
  id: ID,
  ticker: 'JPM',
  type: 'equity_research',
  created_at: '2026-06-06T14:00:00Z',
  outputs: {
    structured: {
      numeric_audit: {
        artifact_status: 'review_only',
        withhold_valuation: true,
        findings: [
          {
            field_key: 'ev_ebitda',
            check: 'financial_sector_ev_meaningless',
            severity: 'blocked_field',
            evidence:
              "JPM industry='Banks - Diversified': deposits/float/funding are operating, not capital structure, and there is no clean above-the-line EBITDA — ev_ebitda=8.0 is a category error. Value on P/B, P/TBV, ROTCE, DDM.",
          },
          {
            field_key: 'pe_ratio',
            check: 'non_positive_earnings_pe_nm',
            severity: 'review',
            evidence:
              'JPM net_income=-5,800,000,000 ≤ 0: P/E is not meaningful by economics (loss-maker / cyclical trough). Lean on EV/Revenue, P/B, or DCF.',
          },
        ],
      },
    },
  },
  inputs: {},
  assumptions: {},
  meta: {},
}

async function gotoReport(page: Page, locale: 'zh' | 'en') {
  await page.addInitScript((loc) => {
    localStorage.setItem('finrobot-ui-prefs', JSON.stringify({ state: { locale: loc }, version: 0 }))
  }, locale)
  await page.route('http://localhost:5173/api/**', (route) => {
    const url = route.request().url()
    if (/\/timeline/.test(url)) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    if (/\/diff\//.test(url)) {
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    }
    if (new RegExp(`/api/artifacts/${ID}(\\?|$)`).test(url)) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL) }) // prettier-ignore
    }
    if (/\/api\/(data|valuation)\//.test(url)) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
  await page.goto(`/stocks/JPM/runs/${ID}`)
  await page.locator('[data-testid="report-audit-banner"]').waitFor({ timeout: 12000 })
  await page.waitForTimeout(200)
}

test('numeric-audit banner — en', async ({ page }) => {
  await gotoReport(page, 'en')
  await page
    .locator('[data-testid="report-audit-banner"]')
    .screenshot({ path: 'e2e/_audit-banner-en.png' })
})

test('numeric-audit banner — zh', async ({ page }) => {
  await gotoReport(page, 'zh')
  await page
    .locator('[data-testid="report-audit-banner"]')
    .screenshot({ path: 'e2e/_audit-banner-zh.png' })
})
