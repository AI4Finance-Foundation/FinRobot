import { describe, it, expect, vi } from 'vitest'
import { formatAge, freshnessColor, freshnessTier, FRESHNESS_WARN_SECONDS, FRESHNESS_DANGER_SECONDS } from './format'

// Mock tSync so unit test doesn't depend on full Lingui compile output.
vi.mock('../i18n', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../i18n')
  return {
    ...actual,
    tSync: (key: string, params?: Record<string, unknown>) => {
      const n = params?.n ?? ''
      const zh: Record<string, string> = {
        'marketdata.age.justNow': '刚刚',
        'marketdata.age.sAgo': `${n}s 前`,
        'marketdata.age.minAgo': `${n}min 前`,
        'marketdata.age.hAgo': `${n}h 前`,
      }
      return zh[key] ?? key
    },
  }
})

describe('formatAge', () => {
  const now = new Date('2026-05-27T12:00:00Z')

  it('null returns dash', () => {
    expect(formatAge(null, now)).toBe('—')
  })

  it('invalid ISO returns dash', () => {
    expect(formatAge('not-a-date', now)).toBe('—')
  })

  it('< 5s returns 刚刚', () => {
    const iso = new Date(now.getTime() - 2000).toISOString()
    expect(formatAge(iso, now)).toBe('刚刚')
  })

  it('< 60s returns s 前', () => {
    const iso = new Date(now.getTime() - 30_000).toISOString()
    expect(formatAge(iso, now)).toBe('30s 前')
  })

  it('< 3600s returns min 前', () => {
    const iso = new Date(now.getTime() - 5 * 60_000).toISOString()
    expect(formatAge(iso, now)).toBe('5min 前')
  })

  it('>= 3600s returns h 前', () => {
    const iso = new Date(now.getTime() - 2 * 3600_000).toISOString()
    expect(formatAge(iso, now)).toBe('2h 前')
  })

  it('future timestamps return 刚刚 (no negative seconds)', () => {
    const iso = new Date(now.getTime() + 5000).toISOString()
    expect(formatAge(iso, now)).toBe('刚刚')
  })
})

describe('freshnessColor', () => {
  it('fresh (<= WARN) returns accent-cyan (live signal)', () => {
    expect(freshnessColor(0)).toBe('var(--accent-cyan)')
    expect(freshnessColor(FRESHNESS_WARN_SECONDS)).toBe('var(--accent-cyan)')
  })

  it('delayed (> WARN, <= DANGER) returns warning', () => {
    expect(freshnessColor(FRESHNESS_WARN_SECONDS + 1)).toBe('var(--warning)')
    expect(freshnessColor(FRESHNESS_DANGER_SECONDS)).toBe('var(--warning)')
  })

  it('stale (> DANGER) returns danger', () => {
    expect(freshnessColor(FRESHNESS_DANGER_SECONDS + 1)).toBe('var(--danger)')
    expect(freshnessColor(3600 * 24)).toBe('var(--danger)')
  })
})

describe('freshnessTier', () => {
  it('returns fresh / delayed / stale at boundaries', () => {
    expect(freshnessTier(0)).toBe('fresh')
    expect(freshnessTier(FRESHNESS_WARN_SECONDS)).toBe('fresh')
    expect(freshnessTier(FRESHNESS_WARN_SECONDS + 1)).toBe('delayed')
    expect(freshnessTier(FRESHNESS_DANGER_SECONDS)).toBe('delayed')
    expect(freshnessTier(FRESHNESS_DANGER_SECONDS + 1)).toBe('stale')
  })
})
