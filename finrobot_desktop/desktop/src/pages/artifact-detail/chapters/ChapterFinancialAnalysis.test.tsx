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
vi.mock('../../../components/charts/BankTrajectoryChart', () => ({ default: () => null }))
vi.mock('../../../components/charts/EpsTrendChart', () => ({ default: () => null }))
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

// Minimal history so the bank trajectory (and its calm note) render; the adapters
// touch every array, so all are present even though the charts are mocked out.
const HIST = {
  years: [2023, 2024],
  revenue: [1e11, 1.1e11],
  revenue_growth_yoy: [null, 0.1],
  cogs: [null, null],
  gross_profit: [null, null],
  gross_margin: [null, null],
  sga: [0, 0],
  sga_ratio: [null, null],
  ebitda: [4e10, 4.4e10],
  ebitda_margin: [0.4, 0.4],
  operating_income: [3e10, 3.2e10],
  operating_margin: [0.3, 0.29],
  net_income: [3e10, 3.2e10],
  eps: [10, 11],
  pe_ratio: [null, 12],
  operating_cash_flow: [0, 0],
  investing_cash_flow: [0, 0],
  financing_cash_flow: [0, 0],
  shareholders_equity: [],
  cagr_revenue: 0.1,
  ticker: 'BNK',
  price_data_available: true,
} as unknown as import('../../../types/finance').HistoricalMetrics

describe('ChapterFinancialAnalysis bank branch (financial_sector)', () => {
  it('omits the EBITDA row and renders the bank trajectory + calm caliber note', () => {
    render(
      <ChapterFinancialAnalysis
        dcf={null}
        rawData={RAW_DATA}
        historicalMetrics={HIST}
        reportingCurrency="USD"
        financialSector
      />,
    )
    // EBITDA is a category error for a bank — the waterfall row is gone.
    expect(screen.queryByText('EBITDA')).not.toBeInTheDocument()
    // Net income is still surfaced.
    expect(screen.getByText('净利润')).toBeInTheDocument()
    // Calm caliber note (zh locale in this file's i18n mock) explains the omission.
    expect(screen.getByText(/口径错误/)).toBeInTheDocument()
  })

  it('non-bank control keeps the EBITDA row (byte-identical path)', () => {
    render(
      <ChapterFinancialAnalysis
        dcf={null}
        rawData={RAW_DATA}
        historicalMetrics={HIST}
        reportingCurrency="USD"
        financialSector={false}
      />,
    )
    expect(screen.getByText('EBITDA')).toBeInTheDocument()
    expect(screen.queryByText(/口径错误/)).not.toBeInTheDocument()
  })
})
