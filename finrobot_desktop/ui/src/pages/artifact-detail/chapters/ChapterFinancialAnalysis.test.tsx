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

// useHistoricalData hits the network; stub it so the chapter renders its KV
// cells (which don't depend on historical) without a QueryClient.
vi.mock('../../../hooks/useHistoricalData', () => ({
  useHistoricalData: () => ({ data: undefined }),
}))

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
    render(<ChapterFinancialAnalysis ticker="AAPL" dcf={null} rawData={RAW_DATA} />)
    // EBITDA card only renders when baseEbitda !== null — i.e. when income.ebitda
    // is read correctly. Pre-fix (top-level read) this card was always absent.
    expect(screen.getByText('EBITDA')).toBeInTheDocument()
    expect(screen.getByText('净利润')).toBeInTheDocument()
    // fiscal year derived from top-level fiscal_period_end, not a (nonexistent)
    // fiscal_year field.
    expect(screen.getByText('FY2024')).toBeInTheDocument()
  })

  it('does NOT surface cards when income bucket is absent', () => {
    render(<ChapterFinancialAnalysis ticker="AAPL" dcf={null} rawData={{}} />)
    expect(screen.queryByText('EBITDA')).not.toBeInTheDocument()
  })
})
