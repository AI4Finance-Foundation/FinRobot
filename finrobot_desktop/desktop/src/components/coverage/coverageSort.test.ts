import { describe, it, expect } from 'vitest'
import { sortCoverageRows } from './coverageSort'
import type { CoverageRow } from '../../api/coverage'

function row(over: Partial<CoverageRow>): CoverageRow {
  return {
    ticker: 'AAA',
    company: null,
    price: null,
    change_pct_1d: null,
    price_as_of: null,
    session_state: null,
    market_cap: null,
    revenue_ttm: null,
    ev_ebitda: null,
    pe: null,
    currency: null,
    latest_verdict: null,
    target_price: null,
    target_date: null,
    entry_price: null,
    upside_to_target_live: null,
    signal: null,
    artifact_count: 0,
    research_count: 0,
    latest_artifact_id: null,
    latest_type: null,
    latest_at: null,
    run_status: null,
    run_error: null,
    market_implied: null,
    market_stale: false,
    needs_refresh: [],
    warnings: [],
    sources: {
      price: null,
      change_pct_1d: null,
      market_cap: null,
      revenue_ttm: null,
      ev_ebitda: null,
      pe: null,
      upside_to_target_live: null,
      market_implied: null,
    },
    ...over,
  }
}

describe('sortCoverageRows', () => {
  it('returns the original array reference-order when sort is null', () => {
    const rows = [row({ ticker: 'B' }), row({ ticker: 'A' })]
    expect(sortCoverageRows(rows, null)).toEqual(rows)
  })

  it('sorts numbers descending and ascending', () => {
    const rows = [
      row({ ticker: 'A', pe: 10 }),
      row({ ticker: 'B', pe: 30 }),
      row({ ticker: 'C', pe: 20 }),
    ]
    expect(sortCoverageRows(rows, { key: 'pe', dir: 'desc' }).map((r) => r.ticker)).toEqual([
      'B',
      'C',
      'A',
    ])
    expect(sortCoverageRows(rows, { key: 'pe', dir: 'asc' }).map((r) => r.ticker)).toEqual([
      'A',
      'C',
      'B',
    ])
  })

  it('pins null values to the bottom in BOTH directions', () => {
    const rows = [
      row({ ticker: 'A', pe: 10 }),
      row({ ticker: 'N', pe: null }),
      row({ ticker: 'B', pe: 30 }),
    ]
    // desc: real numbers first (30,10), null last
    expect(sortCoverageRows(rows, { key: 'pe', dir: 'desc' }).map((r) => r.ticker)).toEqual([
      'B',
      'A',
      'N',
    ])
    // asc: real numbers first (10,30), null STILL last (never floated to top)
    expect(sortCoverageRows(rows, { key: 'pe', dir: 'asc' }).map((r) => r.ticker)).toEqual([
      'A',
      'B',
      'N',
    ])
  })

  it('sorts tickers as locale strings', () => {
    const rows = [row({ ticker: 'NVDA' }), row({ ticker: 'AAPL' }), row({ ticker: 'MSFT' })]
    expect(sortCoverageRows(rows, { key: 'ticker', dir: 'asc' }).map((r) => r.ticker)).toEqual([
      'AAPL',
      'MSFT',
      'NVDA',
    ])
  })

  it('does not mutate the input array', () => {
    const rows = [row({ ticker: 'B', pe: 1 }), row({ ticker: 'A', pe: 2 })]
    const before = rows.map((r) => r.ticker)
    sortCoverageRows(rows, { key: 'pe', dir: 'desc' })
    expect(rows.map((r) => r.ticker)).toEqual(before)
  })
})

describe('derived sort keys', () => {
  it('needs_action orders by priority score (run_failed > never_run > clean)', () => {
    const rows = [
      row({ ticker: 'CLEAN', artifact_count: 2, research_count: 2 }),
      row({
        ticker: 'FAILED',
        run_status: 'failed',
        needs_refresh: [{ kind: 'run_failed', detail: 'boom', artifact_id: null }],
      }),
      row({
        ticker: 'NEW',
        needs_refresh: [{ kind: 'never_run', detail: 'never', artifact_id: null }],
      }),
    ]
    expect(
      sortCoverageRows(rows, { key: 'needs_action', dir: 'desc' }).map((r) => r.ticker),
    ).toEqual(['FAILED', 'NEW', 'CLEAN'])
  })

  it('latest_report orders by report date, undated rows sink', () => {
    const rows = [
      row({ ticker: 'OLD', latest_at: '2026-01-01T00:00:00Z' }),
      row({ ticker: 'NONE', latest_at: null }),
      row({ ticker: 'NEW', latest_at: '2026-06-01T00:00:00Z' }),
    ]
    expect(
      sortCoverageRows(rows, { key: 'latest_report', dir: 'desc' }).map((r) => r.ticker),
    ).toEqual(['NEW', 'OLD', 'NONE'])
  })
})
