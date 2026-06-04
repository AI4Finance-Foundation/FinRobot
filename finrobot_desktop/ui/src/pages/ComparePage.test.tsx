import { describe, it, expect } from 'vitest'
import { dayAge, vintageSpreadDays, VINTAGE_WARN_DAYS } from './ComparePage'
import type { CompanyValuation } from '../api/coverage'

// BUG-057: the Compare table assembles each ticker's latest *stored* DCF, which
// can be today's run for one ticker and a weeks-old artifact for another. These
// tests pin the vintage-disclosure helpers driving the "DCF Date" column +
// disparate-vintage warning.

const DAY = 86_400_000

function cv(ticker: string, dcf_as_of: string | null, error: string | null = null): CompanyValuation {
  return {
    ticker,
    company_name: '',
    current_price: 180,
    implied_price: 200,
    upside_pct: 11.1,
    wacc: 0.082,
    terminal_growth: 0.025,
    ev_ebitda: 18,
    pe_ratio: 28,
    dcf_as_of,
    dcf_artifact_id: dcf_as_of ? `art_${ticker}` : null,
    warnings: [],
    error,
  }
}

describe('dayAge', () => {
  it('returns whole-day age from an ISO stamp', () => {
    const now = Date.parse('2026-05-01T00:00:00Z')
    expect(dayAge('2026-04-24T00:00:00Z', now)).toBe(7)
  })

  it('returns null for live (no as_of) rows', () => {
    expect(dayAge(null, Date.now())).toBeNull()
  })

  it('returns null for an unparseable stamp', () => {
    expect(dayAge('not-a-date', Date.now())).toBeNull()
  })
})

describe('vintageSpreadDays', () => {
  it('measures the gap between oldest and newest dated DCF', () => {
    const spread = vintageSpreadDays([
      cv('AAPL', '2026-05-01T00:00:00Z'),
      cv('MSFT', '2026-04-10T00:00:00Z'),
    ])
    expect(spread).toBe(21)
    expect(spread! > VINTAGE_WARN_DAYS).toBe(true)
  })

  it('is null when fewer than two rows carry a vintage', () => {
    expect(vintageSpreadDays([cv('AAPL', '2026-05-01T00:00:00Z'), cv('MSFT', null)])).toBeNull()
  })

  it('ignores errored rows when measuring spread', () => {
    const spread = vintageSpreadDays([
      cv('AAPL', '2026-05-01T00:00:00Z'),
      cv('MSFT', '2026-04-30T00:00:00Z'),
      cv('GOOG', '2026-01-01T00:00:00Z', 'no DCF'),
    ])
    expect(spread).toBe(1) // GOOG excluded (error) → only AAPL/MSFT counted
  })

  it('returns 0 when all vintages are the same instant', () => {
    expect(
      vintageSpreadDays([cv('A', '2026-05-01T00:00:00Z'), cv('B', '2026-05-01T00:00:00Z')]),
    ).toBe(0)
  })
})
