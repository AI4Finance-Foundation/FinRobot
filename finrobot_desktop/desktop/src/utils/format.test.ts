import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  formatAge,
  formatCurrencyCompact,
  formatDate,
  formatSourceDate,
  freshnessColor,
  freshnessTier,
  FRESHNESS_WARN_SECONDS,
  FRESHNESS_DANGER_SECONDS,
} from './format'

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

describe('formatCurrencyCompact', () => {
  it('compacts positive USD amounts', () => {
    expect(formatCurrencyCompact(5e9, 'USD', 'en')).toBe('$5.00B')
    expect(formatCurrencyCompact(1.23e12, 'USD', 'en')).toBe('$1.23T')
    expect(formatCurrencyCompact(4.5e6, 'USD', 'en')).toBe('$4.50M')
  })

  it('puts the sign BEFORE the symbol for negatives (finance convention)', () => {
    // "-$5.00B", never the hand-rolled "$-5.00B".
    expect(formatCurrencyCompact(-5e9, 'USD', 'en')).toBe('-$5.00B')
    expect(formatCurrencyCompact(-1.23e12, 'USD', 'en')).toBe('-$1.23T')
    expect(formatCurrencyCompact(-2.5e6, 'HKD', 'en')).toBe('-HK$2.50M')
  })

  it('keeps the sign with the number in the ISO-code fallback', () => {
    expect(formatCurrencyCompact(-1.23e9, 'XYZ', 'en')).toBe('XYZ -1.23B')
  })

  it('sub-thousand negatives defer to Intl (sign handled there)', () => {
    expect(formatCurrencyCompact(-500, 'USD', 'en')).toBe('-$500')
  })

  it('null / undefined / NaN → em dash', () => {
    expect(formatCurrencyCompact(null, 'USD', 'en')).toBe('—')
    expect(formatCurrencyCompact(undefined, 'USD', 'en')).toBe('—')
    expect(formatCurrencyCompact(Number.NaN, 'USD', 'en')).toBe('—')
  })
})

describe('formatDate — date-only strings are TZ-safe (western-hemisphere off-by-one)', () => {
  // The web tsconfig has no Node types; reach process via globalThis so the
  // TZ swap (a Node/vitest-only facility) doesn't break the tsc build.
  const proc = (globalThis as unknown as { process: { env: Record<string, string | undefined> } })
    .process
  const originalTZ = proc.env.TZ

  afterEach(() => {
    if (originalTZ === undefined) delete proc.env.TZ
    else proc.env.TZ = originalTZ
  })

  it('renders the calendar day verbatim in a UTC-negative zone', () => {
    // `new Date('2026-03-31')` is UTC midnight; local getters in New York
    // (UTC-4/-5) land on 03-30 without date-only local parsing.
    proc.env.TZ = 'America/New_York'
    expect(formatDate('2026-03-31', 'en', 'short')).toBe('2026-03-31')
    expect(formatDate('2026-03-31', 'en', 'long')).toBe('March 31, 2026')
  })

  it('renders the calendar day verbatim in a UTC-positive zone', () => {
    proc.env.TZ = 'Asia/Shanghai'
    expect(formatDate('2026-03-31', 'en', 'short')).toBe('2026-03-31')
  })

  it('full ISO timestamps keep instant semantics (not affected)', () => {
    proc.env.TZ = 'Asia/Shanghai'
    // UTC 16:00 on 03-30 = 03-31 00:00 in Shanghai — a real instant must
    // still render in the viewer's local zone.
    expect(formatDate('2026-03-30T16:00:00Z', 'en', 'short')).toBe('2026-03-31')
  })

  it('time style renders clock-only in the local zone (breaker cooldown badges)', () => {
    proc.env.TZ = 'Asia/Shanghai'
    // UTC 06:20 = 14:20 in Shanghai.
    expect(formatDate('2026-06-11T06:20:00Z', 'zh', 'time')).toBe('14:20')
    expect(formatDate('2026-06-11T06:20:00Z', 'en', 'time')).toBe('2:20 PM')
  })
})

describe('formatSourceDate — UTC calendar day, TZ-stable (source-reported dates)', () => {
  const proc = (globalThis as unknown as { process: { env: Record<string, string | undefined> } })
    .process
  const originalTZ = proc.env.TZ
  afterEach(() => {
    if (originalTZ === undefined) delete proc.env.TZ
    else proc.env.TZ = originalTZ
  })

  it('renders the source UTC day regardless of viewer timezone (the +1-day bug)', () => {
    // 16:20Z = next local day east of UTC; formatDate would roll it forward.
    // formatSourceDate must show the SOURCE day (06-11) in BOTH zones.
    proc.env.TZ = 'Asia/Shanghai'
    expect(formatSourceDate('2026-06-11T16:20:00Z', 'en')).toBe('2026-06-11')
    proc.env.TZ = 'America/New_York'
    expect(formatSourceDate('2026-06-11T16:20:00Z', 'en')).toBe('2026-06-11')
    // Contrast: plain formatDate DOES shift east of UTC (instant semantics).
    proc.env.TZ = 'Asia/Shanghai'
    expect(formatDate('2026-06-11T16:20:00Z', 'en', 'short')).toBe('2026-06-12')
  })

  it('passes a bare date-only string through unshifted', () => {
    proc.env.TZ = 'America/New_York'
    expect(formatSourceDate('2026-03-31', 'en')).toBe('2026-03-31')
  })

  it('returns the em-dash for null/undefined/invalid', () => {
    expect(formatSourceDate(null, 'en')).toBe('—')
    expect(formatSourceDate(undefined, 'en')).toBe('—')
    expect(formatSourceDate('not-a-date', 'en')).toBe('—')
  })
})
