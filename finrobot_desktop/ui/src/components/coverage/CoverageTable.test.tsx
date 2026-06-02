/**
 * CoverageTable — provenance integration.
 *
 * Verifies the numeric cells render through SourcedNumber: values show, sourced
 * cells expose a popover trigger, a degraded cell shows its inline caveat glyph,
 * and the upside cell's deep-link resolves from the row's ticker (the /coverage
 * route carries no :ticker param, so SourcedNumber relies on the prop).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { CoverageTable } from './CoverageTable'
import type { CoverageSort, CoverageSortKey } from './coverageSort'
import type { CoverageRow } from '../../api/coverage'

function makeRow(over: Partial<CoverageRow> = {}): CoverageRow {
  return {
    ticker: 'AAPL',
    company: 'Apple Inc.',
    price: 200,
    change_pct_1d: 1.25,
    price_as_of: '2026-03-01T00:00:00Z',
    market_cap: 3e12,
    revenue_ttm: 100e9,
    ev_ebitda: 18.4,
    pe: 28.5,
    currency: 'USD',
    latest_verdict: 'BUY',
    target_price: 240,
    target_date: '2027-03-01T00:00:00Z',
    entry_price: 180,
    upside_to_target_live: 0.2,
    signal: 'watching',
    run_count: 2,
    latest_artifact_id: 'art_aapl_eq',
    latest_type: 'equity_research',
    latest_at: '2026-04-01T00:00:00Z',
    run_status: null,
    run_error: null,
    needs_refresh: [],
    warnings: [],
    sources: {
      price: {
        provider: 'yfinance',
        as_of: '2026-03-01T00:00:00Z',
        fetched_at: '2026-06-02T00:00:00Z',
        formula_warning: '实时价缺失，用最近收盘价',
      },
      change_pct_1d: { provider: 'yfinance', formula_id: 'latest_session_change' },
      market_cap: { provider: 'yfinance', formula_id: 'market_cap' },
      revenue_ttm: { provider: 'yfinance' },
      ev_ebitda: { provider: 'yfinance', formula_id: 'ev_ebitda' },
      pe: { provider: 'yfinance', formula_id: 'pe_ttm' },
      upside_to_target_live: {
        formula_id: 'upside_to_target_live',
        as_of: '2026-04-01T00:00:00Z',
        artifact_id: 'art_aapl_eq',
      },
    },
    ...over,
  }
}

function renderTable(
  rows: CoverageRow[],
  opts: {
    sort?: CoverageSort | null
    onSort?: (key: CoverageSortKey) => void
    marketPending?: boolean
  } = {},
): void {
  render(
    <MemoryRouter initialEntries={['/coverage']}>
      <CoverageTable
        rows={rows}
        selected={[]}
        marketPending={opts.marketPending}
        sort={opts.sort ?? null}
        onSort={opts.onSort ?? (() => {})}
        onToggle={() => {}}
        onToggleAll={() => {}}
        onOpenTicker={() => {}}
        onRunOne={() => {}}
      />
    </MemoryRouter>,
  )
}

describe('CoverageTable provenance', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the formatted price and exposes a source popover trigger', () => {
    renderTable([makeRow()])
    // Value still renders through SourcedNumber's format closure.
    expect(screen.getByText('$200.00')).toBeInTheDocument()
    // Sourced cells are interactive popover triggers (dotted-underline button).
    expect(screen.getAllByRole('button').length).toBeGreaterThan(0)
  })

  it('shows the degraded caveat glyph inline on the price cell', () => {
    renderTable([makeRow()])
    // close_only caveat surfaces without hover (dense-table requirement).
    expect(screen.getByRole('img', { name: '实时价缺失，用最近收盘价' })).toBeInTheDocument()
  })

  it('opens the price popover showing its provider', () => {
    renderTable([makeRow()])
    const priceTrigger = screen.getByText('$200.00').closest('[role="button"]') as HTMLElement
    fireEvent.mouseEnter(priceTrigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('yfinance')).toBeInTheDocument()
  })

  it('resolves the upside cell deep-link from the row ticker (no :ticker route)', () => {
    renderTable([makeRow()])
    const upsideTrigger = screen.getByText('20.0%').closest('[role="button"]') as HTMLElement
    fireEvent.mouseEnter(upsideTrigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })
    const link = screen.getByText(/Open full report/) as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/stocks/AAPL/runs/art_aapl_eq')
  })
})

describe('CoverageTable fast-skeleton (marketPending)', () => {
  it('renders market cells as loading shimmer, not values, while pending', () => {
    renderTable([makeRow()], { marketPending: true })
    // Price value is NOT shown; a loading placeholder is.
    expect(screen.queryByText('$200.00')).toBeNull()
    expect(screen.getAllByRole('img', { name: 'loading' }).length).toBeGreaterThan(0)
    // Research cells stay real — verdict is available in the fast phase.
    expect(screen.getByText('BUY')).toBeInTheDocument()
  })

  it('renders real market values once not pending', () => {
    renderTable([makeRow()], { marketPending: false })
    expect(screen.getByText('$200.00')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'loading' })).toBeNull()
  })
})

describe('CoverageTable sorting', () => {
  it('column headers are sort buttons that emit the column key', () => {
    const onSort = vi.fn()
    renderTable([makeRow()], { onSort })
    fireEvent.click(screen.getByRole('button', { name: /Sort by P\/E/ }))
    expect(onSort).toHaveBeenCalledWith('pe')
  })

  it('every numeric/ticker column is sortable; categorical ones are not', () => {
    renderTable([makeRow()])
    for (const col of ['Price', '1D', 'EV/EBITDA', 'P/E']) {
      expect(
        screen.getByRole('button', { name: new RegExp(`Sort by ${col.replace('/', '\\/')}`) }),
      ).toBeInTheDocument()
    }
    // Verdict / Signal / Status are categorical — no sort button.
    expect(screen.queryByRole('button', { name: /Sort by Verdict/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Sort by Signal/ })).toBeNull()
  })
})
