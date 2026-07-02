import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterFinancialAnalysis } from './ChapterFinancialAnalysis'

// raw_data is FinancialData.model_dump() — money line items nest under income.*.
// This guards the 2026-05-29 fix: the chapter used to read rawData.ebitda etc.
// from the TOP level, so the EBITDA / net-income cards silently never rendered.

vi.mock('../../../i18n', () => ({
  useI18n: () => ({
    locale: 'zh',
    t: (key: string) => {
      const map: Record<string, string> = {
        'chapter.financial.kv.revenueBase': '营收',
        'chapter.financial.kv.netIncome': '净利润',
      }
      return map[key] ?? key
    },
  }),
}))

// historical trend is now passed as a FROZEN prop (historicalMetrics), not a
// live hook — the KV cards don't depend on it, so pass null here.

// Charts are irrelevant to the KV-card regression; render them as no-ops.
vi.mock('../../../components/charts/RevenueEbitdaChart', () => ({ default: () => null }))
vi.mock('../../../components/charts/MarginTrendChart', () => ({ default: () => null }))
vi.mock('../../../components/charts/CashFlowChart', () => ({ default: () => null }))

const RAW_DATA = {
  fiscal_period_end: '2024-09-30',
  income: {
    revenue: 391_035_000_000,
    ebitda: 131_900_000_000,
    net_income: 93_736_000_000,
  },
}

describe('ChapterFinancialAnalysis KV cards', () => {
  it('reads money line items from income.* (not the top level)', () => {
    render(
      <ChapterFinancialAnalysis
        dcf={null}
        rawData={RAW_DATA}
        historicalMetrics={null}
        reportingCurrency="USD"
      />,
    )
    // EBITDA card only renders when baseEbitda !== null — i.e. when income.ebitda
    // is read correctly. Pre-fix (top-level read) this card was always absent.
    expect(screen.getByText('EBITDA')).toBeInTheDocument()
    expect(screen.getByText('净利润')).toBeInTheDocument()
    // Revenue (Base) is a TTM figure (Σ latest 4 quarters), NOT a completed
    // fiscal year — the badge must say TTM (+ the TTM window's end month), not
    // "FY2024" (BUG-10 regression: that claimed a completed fiscal year the
    // pipeline never asserts, since fiscal_period_end is the TTM period end).
    expect(screen.getByText('TTM · 2024-09')).toBeInTheDocument()
    expect(screen.queryByText('FY2024')).not.toBeInTheDocument()
  })

  it('does NOT surface cards when income bucket is absent', () => {
    render(
      <ChapterFinancialAnalysis
        dcf={null}
        rawData={{}}
        historicalMetrics={null}
        reportingCurrency="USD"
      />,
    )
    expect(screen.queryByText('EBITDA')).not.toBeInTheDocument()
  })
})
