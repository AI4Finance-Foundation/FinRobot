import { describe, it, expect } from 'vitest'
import { buildBalanceCells } from './ChapterFinancialData'

// BUG-10 regression: shares_outstanding is never a reported diluted count —
// FMP carries no raw shares field (provider-layer market_cap/price derivation),
// and the yfinance path falls back to that same market-cap-implied count
// whenever the reported figure diverges from price × count (multi-class /
// ADR mismatch). The "DILUTED" sub-label claimed a 10-Q-sourced figure this
// pipeline never has.
describe('buildBalanceCells — shares outstanding caliber label', () => {
  it('labels shares outstanding IMPLIED, never DILUTED', () => {
    const cells = buildBalanceCells(
      { total_debt: 100, total_cash: 50 },
      { market_cap: 1000, shares_outstanding: 15_000_000_000 },
      'en',
      'USD',
      'USD',
    )
    const sharesCell = cells.find((c) => c.label === 'Shares Out')
    expect(sharesCell?.sub).toBe('IMPLIED')
    expect(sharesCell?.sub).not.toBe('DILUTED')
  })

  it('labels shares outstanding 隐含 (not 稀释后) in Chinese', () => {
    const cells = buildBalanceCells(
      { total_debt: 100, total_cash: 50 },
      { market_cap: 1000, shares_outstanding: 15_000_000_000 },
      'zh',
      'USD',
      'USD',
    )
    const sharesCell = cells.find((c) => c.label === '总股本')
    expect(sharesCell?.sub).toBe('隐含')
    expect(sharesCell?.sub).not.toBe('稀释后')
  })

  it('omits the shares-outstanding cell entirely when the field is absent', () => {
    const cells = buildBalanceCells({ total_debt: 100 }, { market_cap: 1000 }, 'en', 'USD', 'USD')
    expect(cells.find((c) => c.label === 'Shares Out')).toBeUndefined()
  })
})
