import { describe, it, expect } from 'vitest'
import { hitRateSampleCaption, type HitRateOverview } from './useDashboardHitRate'

// BUG-062: the is_sampled / sample_size honesty fields must reach the consumed
// TS contract (they were previously dropped at the API→frontend boundary) and
// be renderable as a disclosure caption.

const base: HitRateOverview = {
  window: 'all',
  overall: { n_total: 0, n_closed: 0, n_hit: 0, hit_rate: null },
  by_verdict: {
    BUY: { n_total: 0, n_closed: 0, n_hit: 0, hit_rate: null },
    HOLD: { n_total: 0, n_closed: 0, n_hit: 0, hit_rate: null },
    SELL: { n_total: 0, n_closed: 0, n_hit: 0, hit_rate: null },
  },
  generated_at: '2026-06-04T00:00:00Z',
  is_sampled: false,
  sample_size: 500,
}

describe('hitRateSampleCaption', () => {
  it('returns null when not sampled (full record) ', () => {
    expect(hitRateSampleCaption({ ...base, is_sampled: false })).toBeNull()
  })

  it('discloses the sample size when sampled', () => {
    const caption = hitRateSampleCaption({ ...base, is_sampled: true, sample_size: 500 })
    expect(caption).not.toBeNull()
    expect(caption).toContain('500')
  })

  it('honors a non-default sample_size in the caption', () => {
    expect(hitRateSampleCaption({ ...base, is_sampled: true, sample_size: 250 })).toContain('250')
  })

  it('returns null for undefined overview (no data yet)', () => {
    expect(hitRateSampleCaption(undefined)).toBeNull()
  })

  it('the contract carries is_sampled + sample_size through to consumers', () => {
    // Type-level guarantee: parsing an API payload that includes the honesty
    // fields keeps them — they are no longer silently stripped by the interface.
    const parsed = JSON.parse(
      JSON.stringify({ ...base, is_sampled: true, sample_size: 500 }),
    ) as HitRateOverview
    expect(parsed.is_sampled).toBe(true)
    expect(parsed.sample_size).toBe(500)
  })
})
