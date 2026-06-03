import { describe, it, expect } from 'vitest'
import { COVERAGE_FILTERS, filterRows, matchesFilter } from './coverageFilter'
import type { CoverageRow } from '../../api/coverage'

function row(over: Partial<CoverageRow>): CoverageRow {
  return {
    ticker: 'AAA',
    company: null,
    price: null,
    change_pct_1d: null,
    price_as_of: null,
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
    },
    ...over,
  }
}

describe('coverageFilter', () => {
  const clean = row({ ticker: 'CLEAN', artifact_count: 2, research_count: 2 })
  const running = row({ ticker: 'RUN', run_status: 'running', research_count: 1 })
  const created = row({ ticker: 'NEW', run_status: 'created' })
  const action = row({
    ticker: 'ACT',
    research_count: 1,
    needs_refresh: [{ kind: 'run_failed', detail: 'x', artifact_id: null }],
  })
  const notRun = row({ ticker: 'COLD', artifact_count: 0, research_count: 0 })

  it('all passes everything', () => {
    const rows = [clean, running, action, notRun]
    expect(filterRows(rows, 'all')).toEqual(rows)
  })

  it('needs_action matches only actionable rows', () => {
    expect(matchesFilter(action, 'needs_action')).toBe(true)
    expect(matchesFilter(clean, 'needs_action')).toBe(false)
  })

  it('running matches created OR running, not terminal states', () => {
    expect(matchesFilter(running, 'running')).toBe(true)
    expect(matchesFilter(created, 'running')).toBe(true)
    expect(matchesFilter(clean, 'running')).toBe(false)
  })

  it('exposes only the three triage lenses (has_reports / not_run were cut)', () => {
    expect(COVERAGE_FILTERS).toEqual(['all', 'needs_action', 'running'])
  })
})
