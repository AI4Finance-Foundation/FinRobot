import { describe, it, expect } from 'vitest'
import { deriveTriage, MOVER_THRESHOLD, TRIAGE_MAX } from './coverageTriage'
import type { CoverageRow } from '../../api/coverage'

// Minimal row factory (mirrors coverageSort.test.ts) — every field present so
// the CoverageRow type is satisfied; tests override only what they exercise.
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

describe('deriveTriage', () => {
  it('returns nothing for an empty watchlist', () => {
    expect(deriveTriage([])).toEqual([])
  })

  it('skips rows whose anomaly fields are null', () => {
    // change_pct_1d null and upside null → never qualifies, regardless of price.
    const rows = [row({ ticker: 'A', price: 100 }), row({ ticker: 'B', price: 50 })]
    expect(deriveTriage(rows)).toEqual([])
  })

  it('flags pure movers (|1d| >= threshold) in both directions', () => {
    // +4.0 and -5.0 both qualify (|4|, |5| >= 3.0); +2.9 and -1.0 do not.
    const rows = [
      row({ ticker: 'UP', change_pct_1d: 4.0 }),
      row({ ticker: 'FLAT', change_pct_1d: 2.9 }),
      row({ ticker: 'DOWN', change_pct_1d: -5.0 }),
      row({ ticker: 'CALM', change_pct_1d: -1.0 }),
    ]
    const out = deriveTriage(rows)
    // Both movers, ordered by |change| desc: DOWN(5) before UP(4).
    expect(out.map((i) => i.row.ticker)).toEqual(['DOWN', 'UP'])
    expect(out.every((i) => i.kind === 'mover')).toBe(true)
    expect(out.map((i) => i.magnitude)).toEqual([5.0, 4.0])
  })

  it('treats the threshold as inclusive (3.0 in, 2.999 out)', () => {
    const rows = [
      row({ ticker: 'EXACT', change_pct_1d: MOVER_THRESHOLD }), // 3.0 → in
      row({ ticker: 'JUST_UNDER', change_pct_1d: 2.999 }), // → out
      row({ ticker: 'NEG_EXACT', change_pct_1d: -MOVER_THRESHOLD }), // -3.0 → in
    ]
    const out = deriveTriage(rows)
    expect(out.map((i) => i.row.ticker).sort()).toEqual(['EXACT', 'NEG_EXACT'])
  })

  it('flags past_target only when live upside is strictly negative', () => {
    // upside < 0 qualifies; exactly 0 (at target) and > 0 (below target) do not.
    const rows = [
      row({ ticker: 'OVER', upside_to_target_live: -0.08 }),
      row({ ticker: 'AT', upside_to_target_live: 0 }),
      row({ ticker: 'UNDER', upside_to_target_live: 0.15 }),
    ]
    const out = deriveTriage(rows)
    expect(out.map((i) => i.row.ticker)).toEqual(['OVER'])
    expect(out[0].kind).toBe('past_target')
    expect(out[0].magnitude).toBeCloseTo(0.08)
  })

  it('orders all past_target ahead of all movers, magnitude-desc within each kind', () => {
    const rows = [
      row({ ticker: 'MOV_SM', change_pct_1d: 3.5 }), // mover, |3.5|
      row({ ticker: 'PT_BIG', upside_to_target_live: -0.2 }), // past_target, |0.2|
      row({ ticker: 'MOV_BIG', change_pct_1d: -9.0 }), // mover, |9.0|
      row({ ticker: 'PT_SM', upside_to_target_live: -0.05 }), // past_target, |0.05|
    ]
    const out = deriveTriage(rows)
    // past_target block (by |upside| desc): PT_BIG, PT_SM
    // then mover block (by |change| desc): MOV_BIG, MOV_SM
    expect(out.map((i) => i.row.ticker)).toEqual(['PT_BIG', 'PT_SM', 'MOV_BIG', 'MOV_SM'])
    expect(out.map((i) => i.kind)).toEqual(['past_target', 'past_target', 'mover', 'mover'])
  })

  it('classifies a row hitting BOTH classes as past_target, never duplicated', () => {
    // Down 12% AND already past target — the more urgent past_target wins, and it
    // appears exactly once (not also as a mover).
    const rows = [row({ ticker: 'CRASH', change_pct_1d: -12.0, upside_to_target_live: -0.3 })]
    const out = deriveTriage(rows)
    expect(out).toHaveLength(1)
    expect(out[0].kind).toBe('past_target')
    expect(out[0].magnitude).toBeCloseTo(0.3) // |upside|, not |change|
  })

  it('returns the FULL qualifying set (no TRIAGE_MAX truncation here)', () => {
    // Six movers — derive returns all six; truncation is the strip's job.
    const rows = Array.from({ length: 6 }, (_, i) => row({ ticker: `M${i}`, change_pct_1d: 4 + i }))
    const out = deriveTriage(rows)
    expect(out).toHaveLength(6)
    expect(out.length).toBeGreaterThan(TRIAGE_MAX)
    // Sorted by |change| desc: M5(9) … M0(4).
    expect(out.map((i) => i.row.ticker)).toEqual(['M5', 'M4', 'M3', 'M2', 'M1', 'M0'])
  })
})
