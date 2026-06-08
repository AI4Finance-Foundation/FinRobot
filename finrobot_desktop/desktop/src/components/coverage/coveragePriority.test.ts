import { describe, it, expect } from 'vitest'
import { coveragePriority } from './coveragePriority'
import type { CoverageRow, NeedsRefreshReason } from '../../api/coverage'

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

const reason = (kind: string): NeedsRefreshReason => ({ kind, detail: kind, artifact_id: null })

describe('coveragePriority', () => {
  it('a clean, run ticker needs no action and scores 0', () => {
    const p = coveragePriority(row({ artifact_count: 3, research_count: 3 }))
    expect(p.needsAction).toBe(false)
    expect(p.score).toBe(0)
    expect(p.reasons).toEqual([])
  })

  it('ranks run_failed above never_run above soft reasons', () => {
    const failed = coveragePriority(row({ needs_refresh: [reason('run_failed')] }))
    const never = coveragePriority(row({ needs_refresh: [reason('never_run')] }))
    const drift = coveragePriority(row({ needs_refresh: [reason('price_drift')] }))
    expect(failed.score).toBeGreaterThan(never.score)
    expect(never.score).toBeGreaterThan(drift.score)
    expect(failed.needsAction).toBe(true)
  })

  it('takes the max weight across multiple reasons', () => {
    const p = coveragePriority(
      row({ needs_refresh: [reason('price_drift'), reason('run_failed')] }),
    )
    expect(p.score).toBe(100)
  })

  it('a warning alone flags needsAction at the warning weight', () => {
    const p = coveragePriority(row({ warnings: ['行情获取失败'] }))
    expect(p.needsAction).toBe(true)
    expect(p.score).toBe(20)
    expect(p.reasons).toContain('行情获取失败')
  })

  it('reasons list structured refresh details first, then warnings, deduped', () => {
    const p = coveragePriority(
      row({ needs_refresh: [reason('never_run')], warnings: ['never_run', 'extra'] }),
    )
    // 'never_run' detail already present → not duplicated by the matching warning
    expect(p.reasons).toEqual(['never_run', 'extra'])
  })
})
