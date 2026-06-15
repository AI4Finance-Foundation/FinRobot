import { describe, it, expect } from 'vitest'
import { epsBarColor } from './EpsTrendChart'

// EPS bars are colored by YoY direction so the growth trajectory is scannable
// without hovering (涨绿跌红). The exact % stays in the tooltip.
describe('epsBarColor — YoY-direction coloring', () => {
  it('greens EPS growth (and flat counts as non-negative)', () => {
    expect(epsBarColor(12)).toBe('var(--success)')
    expect(epsBarColor(0)).toBe('var(--success)')
  })

  it('reds EPS contraction', () => {
    expect(epsBarColor(-8)).toBe('var(--danger)')
  })

  it('keeps the baseline year (no prior → null / non-finite YoY) neutral', () => {
    expect(epsBarColor(null)).toBe('var(--primary)')
    expect(epsBarColor(Number.NaN)).toBe('var(--primary)')
  })
})
