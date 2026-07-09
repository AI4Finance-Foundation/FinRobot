// Chapter 02 — Company Overview. The chapter used to render ONLY the
// company_overview narrative (a text wall under a header promising structure).
// It now renders a sourced identity+scale snapshot strip above the narrative,
// built from raw_data.market (sector/industry/country/market_cap/beta),
// raw_data.income.gross_margin, and historical_metrics.cagr_revenue. These
// guards lock: snapshot cells appear from rawData, ratios (cagr/gross_margin)
// render as %, market_cap uses the quote currency, numeric cells carry
// provenance, and every degradation path (missing field / no rawData / no
// narrative) stays graceful — no blank, NaN, or undefined.
//
// BACKLOG A4 (2026-07-09) added segmentOverview: a real segment revenue mix
// table, rendered below the narrative, for tickers the SOTP option-value gate
// did NOT fire for. Guarded separately below (source labeling, revenue/share/
// profit-metric cells, and the null/empty no-render path).
//
// test-setup.ts pins the i18n store to locale='en', so the real useI18n yields
// English labels here (no i18n mock needed — mirrors ChapterCover.test).

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterCompanyOverview } from './ChapterCompanyOverview'
import type { SegmentOverviewShape, ThesisShape } from './types'
import type { HistoricalMetrics } from '../../../types/finance'

// A real AAPL artifact slice (verified via curl 2026-06-16):
//   market.sector="Technology", industry="Consumer Electronics", country="US"
//   market.market_cap≈4.345e12 (≈$4.35T, QUOTE currency USD), beta=1.086
//   income.gross_margin=0.4786 (RATIO → 47.9%)
//   historical_metrics.cagr_revenue=0.0328 (RATIO → 3.3%)
const RAW_DATA = {
  market: {
    sector: 'Technology',
    industry: 'Consumer Electronics',
    country: 'US',
    market_cap: 4_345_107_399_039.99,
    beta: 1.086,
  },
  income: {
    gross_margin: 0.47862405358827936,
  },
  provenance: { provider: 'fmp' },
}

// cagr_revenue is the only field the snapshot reads off HistoricalMetrics.
const HISTORICAL = { cagr_revenue: 0.03275991627577457 } as unknown as HistoricalMetrics

function thesis(partial: Partial<ThesisShape>): ThesisShape {
  return partial as ThesisShape
}

describe('ChapterCompanyOverview — sourced snapshot strip', () => {
  it('renders identity + scale cells from rawData, with ratios as % and quote-currency market cap', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'AAPL designs and sells consumer electronics.' })}
        rawData={RAW_DATA}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt="2026-06-11T18:24:24.154643Z"
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    // Identity strings render plain.
    expect(screen.getByText('Sector')).toBeInTheDocument()
    expect(screen.getByText('Technology')).toBeInTheDocument()
    expect(screen.getByText('Industry')).toBeInTheDocument()
    expect(screen.getByText('Consumer Electronics')).toBeInTheDocument()
    expect(screen.getByText('Country')).toBeInTheDocument()
    expect(screen.getByText('US')).toBeInTheDocument()

    // Market cap → quote currency ($), compacted to ≈$4.35T (not a bare number,
    // not a wrong symbol).
    expect(screen.getByText('Market Cap')).toBeInTheDocument()
    expect(screen.getByText('$4.35T')).toBeInTheDocument()

    // Ratios → % (0.4786 → 47.9%, 0.0328 → 3.3%) — single-percent, not doubled.
    expect(screen.getByText('Gross Margin')).toBeInTheDocument()
    expect(screen.getByText('47.9%')).toBeInTheDocument()
    expect(screen.getByText('Revenue CAGR')).toBeInTheDocument()
    expect(screen.getByText('3.3%')).toBeInTheDocument()

    // Beta is a plain ratio (no %, no currency).
    expect(screen.getByText('Beta')).toBeInTheDocument()
    expect(screen.getByText('1.09')).toBeInTheDocument()

    // The narrative still renders below the strip.
    expect(screen.getByText('AAPL designs and sells consumer electronics.')).toBeInTheDocument()
  })

  it('renders operating margin as a % metric (profitability companion to gross margin) when present', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'x' })}
        rawData={{ ...RAW_DATA, income: { gross_margin: 0.4786, operating_margin: 0.315 } }}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt="2026-06-11T18:24:24.154643Z"
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    // operating_margin is a real backend field (IncomeStatement.operating_margin),
    // rendered as a % beside gross margin — the profitability pair.
    expect(screen.getByText('Operating Margin')).toBeInTheDocument()
    expect(screen.getByText('31.5%')).toBeInTheDocument()
    expect(screen.getByText('Gross Margin')).toBeInTheDocument()
  })

  it('renders a negative operating margin (loss-maker, backend allows ge=-5) without crashing', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'x' })}
        rawData={{ ...RAW_DATA, income: { gross_margin: 0.2, operating_margin: -0.35 } }}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt={null}
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    expect(screen.getByText('Operating Margin')).toBeInTheDocument()
    // Negative is shown verbatim (the radial arc clamps to an empty sweep) — no NaN/crash.
    expect(screen.getByText('-35.0%')).toBeInTheDocument()
    expect(screen.queryByText(/NaN|undefined/)).not.toBeInTheDocument()
  })

  it('wraps numeric cells in SourcedNumber (provenance popover reachable) while identity strings stay plain', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'narrative' })}
        rawData={RAW_DATA}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt="2026-06-11T18:24:24.154643Z"
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    // SourcedNumber gives provider-sourced numbers a role="button" trigger with a
    // "click for data source" aria-label; the market-cap cell is wrapped.
    const sourced = screen.getByText('$4.35T').closest('[role="button"]')
    expect(sourced).not.toBeNull()
    // Identity strings are NOT wrapped (no provenance trigger).
    expect(screen.getByText('Technology').closest('[role="button"]')).toBeNull()
  })

  it('omits a cell whose field is absent — never a blank/NaN cell', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'narrative' })}
        // Only sector + market_cap present; industry/country/beta/income absent.
        rawData={{ market: { sector: 'Technology', market_cap: 1_000_000_000 } }}
        historicalMetrics={null}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt={null}
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    expect(screen.getByText('Sector')).toBeInTheDocument()
    expect(screen.getByText('Market Cap')).toBeInTheDocument()
    // Absent fields → no cell at all.
    expect(screen.queryByText('Industry')).not.toBeInTheDocument()
    expect(screen.queryByText('Country')).not.toBeInTheDocument()
    expect(screen.queryByText('Gross Margin')).not.toBeInTheDocument()
    expect(screen.queryByText('Operating Margin')).not.toBeInTheDocument()
    expect(screen.queryByText('Revenue CAGR')).not.toBeInTheDocument()
    expect(screen.queryByText('Beta')).not.toBeInTheDocument()
    // No degenerate rendering anywhere.
    expect(screen.queryByText(/NaN|undefined|—%/)).not.toBeInTheDocument()
  })

  it('degrades to narrative only when rawData is null (no snapshot, no crash)', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'just the prose, no data snapshot' })}
        rawData={null}
        historicalMetrics={null}
        quoteCurrency="USD"
        dataSource={null}
        fetchedAt={null}
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    expect(screen.getByText('just the prose, no data snapshot')).toBeInTheDocument()
    // No snapshot labels surface.
    expect(screen.queryByText('Sector')).not.toBeInTheDocument()
    expect(screen.queryByText('Market Cap')).not.toBeInTheDocument()
  })

  it('shows the snapshot even when the narrative is absent (snapshot is additive)', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: null })}
        rawData={RAW_DATA}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt="2026-06-11T18:24:24.154643Z"
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    // Snapshot still renders.
    expect(screen.getByText('Sector')).toBeInTheDocument()
    expect(screen.getByText('$4.35T')).toBeInTheDocument()
    // Empty-state fallback is unchanged (the prose really is missing).
    expect(screen.getByText(/This report has no company-overview narrative/)).toBeInTheDocument()
  })

  it('renders the empty-state when there is no narrative AND no rawData', () => {
    render(
      <ChapterCompanyOverview
        thesis={null}
        rawData={null}
        historicalMetrics={null}
        quoteCurrency="USD"
        dataSource={null}
        fetchedAt={null}
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    expect(screen.getByText(/This report has no company-overview narrative/)).toBeInTheDocument()
  })
})

// BACKLOG A4 (2026-07-09): segment revenue mix table.
const XBRL_SEGMENT_OVERVIEW: SegmentOverviewShape = {
  ticker: 'MSFT',
  as_of: '2026-07-09T00:00:00Z',
  source: 'sec_xbrl_business_segment',
  period_label: 'FY ending 2025-06-30',
  segments: [
    {
      name: 'Productivity and Business Processes',
      revenue: 120.81e9,
      revenue_share: 0.4288,
      operating_income: 69.773e9,
    },
    {
      name: 'Intelligent Cloud',
      revenue: 106.265e9,
      revenue_share: 0.3772,
      operating_income: 44.589e9,
    },
  ],
  warnings: [],
}

// TSLA-shaped: gross-profit anchor instead of operating income.
const GROSS_PROFIT_SEGMENT_OVERVIEW: SegmentOverviewShape = {
  ticker: 'TSLA',
  as_of: '2026-07-09T00:00:00Z',
  source: 'sec_xbrl_business_segment',
  period_label: 'FY ending 2025-12-31',
  segments: [
    { name: 'Automotive', revenue: 69.526e9, revenue_share: 0.845, gross_profit: 13.292e9 },
    {
      name: 'Energy generation and storage',
      revenue: 12.771e9,
      revenue_share: 0.155,
      gross_profit: 3.802e9,
    },
  ],
  warnings: [],
}

describe('ChapterCompanyOverview — segment overview table (BACKLOG A4)', () => {
  it('renders segment rows with revenue, share, and the OI-anchored profit column', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'x' })}
        rawData={RAW_DATA}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt="2026-06-11T18:24:24.154643Z"
        segmentOverview={XBRL_SEGMENT_OVERVIEW}
        reportingCurrency="USD"
      />,
    )
    // Source + period render as one line (sibling text nodes in the same div).
    expect(
      screen.getByText('SEC XBRL reportable segments (ASC 280) · FY ending 2025-06-30'),
    ).toBeInTheDocument()
    expect(screen.getByText('Productivity and Business Processes')).toBeInTheDocument()
    expect(screen.getByText('Intelligent Cloud')).toBeInTheDocument()
    // MSFT-style breakdown → the operating-income column header, NOT gross profit.
    expect(screen.getByText('Segment Operating Income')).toBeInTheDocument()
    expect(screen.queryByText('Segment Gross Profit')).not.toBeInTheDocument()
    // Compact currency + percent cells render (exact formatting is format.ts's
    // concern; this just proves the numbers reach the table, not '—').
    expect(screen.getByText('42.9%')).toBeInTheDocument()
    expect(screen.getByText('37.7%')).toBeInTheDocument()
  })

  it('renders the gross-profit column for a TSLA-style gross-profit-anchored breakdown', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'x' })}
        rawData={RAW_DATA}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt="2026-06-11T18:24:24.154643Z"
        segmentOverview={GROSS_PROFIT_SEGMENT_OVERVIEW}
        reportingCurrency="USD"
      />,
    )
    expect(screen.getByText('Automotive')).toBeInTheDocument()
    // Gross-profit anchor → the gross-profit column header, NOT operating income.
    expect(screen.getByText('Segment Gross Profit')).toBeInTheDocument()
    expect(screen.queryByText('Segment Operating Income')).not.toBeInTheDocument()
  })

  it('renders no table when segmentOverview is null', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'x' })}
        rawData={RAW_DATA}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt="2026-06-11T18:24:24.154643Z"
        segmentOverview={null}
        reportingCurrency="USD"
      />,
    )
    expect(screen.queryByText('Revenue Share')).not.toBeInTheDocument()
  })

  it('renders no table when segmentOverview has zero segments (defensive, matches backend contract)', () => {
    render(
      <ChapterCompanyOverview
        thesis={thesis({ company_overview: 'x' })}
        rawData={RAW_DATA}
        historicalMetrics={HISTORICAL}
        quoteCurrency="USD"
        dataSource="fmp"
        fetchedAt="2026-06-11T18:24:24.154643Z"
        segmentOverview={{ ...XBRL_SEGMENT_OVERVIEW, segments: [] }}
        reportingCurrency="USD"
      />,
    )
    expect(screen.queryByText('Revenue Share')).not.toBeInTheDocument()
  })
})
