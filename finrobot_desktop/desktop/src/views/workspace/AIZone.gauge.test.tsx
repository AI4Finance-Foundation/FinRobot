import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'

// The workspace verdict card (HotState) renders a TargetGauge under the verdict
// badge + target — the moat's #1 glance number now shows WHERE the target sits
// vs the current price. These tests assert: gauge present when a target AND a
// price exist; absent when the target is withheld (null); and that the live
// quote (not the artifact's entry_price) drives the "now" tick when available.

// SourcedNumber (inside TargetGauge) reads useParams for its deep-link ticker
// fallback; stub it alongside useNavigate.
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ ticker: 'AAPL' }),
}))

vi.mock('../../stores/runStreamStore', () => ({
  useRunStreamStore: (selector: (s: unknown) => unknown) =>
    selector({ startRun: vi.fn(), dismiss: vi.fn(), __runs: {} }),
  selectRunByTicker:
    (ticker: string) =>
    (s: { __runs?: Record<string, unknown> }): unknown =>
      s.__runs?.[ticker],
}))

let latest: Record<string, unknown> | undefined
vi.mock('../../hooks/useV5Artifacts', () => ({
  useLatestArtifact: () => ({
    latest,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  useV5ArtifactTimeline: () => ({ data: [], isLoading: false, isError: false, refetch: vi.fn() }),
}))
vi.mock('../../hooks/useHealth', () => ({
  useHealth: () => ({
    data: {
      backendReachable: true,
      startupError: null,
      availableProviders: ['fmp'],
      modelConfigured: true,
    },
    isPlaceholderData: false,
  }),
}))

let priceData: { current_price: number | null } | undefined
vi.mock('../../hooks/useTickerData', () => ({
  useTickerPrice: () => ({ data: priceData }),
}))
vi.mock('../../stores/toastStore', () => ({ useToastStore: () => vi.fn() }))
vi.mock('../../i18n', () => ({
  useI18n: () => ({ locale: 'en', t: (k: string) => k }),
  tSync: (k: string) => k,
}))
vi.mock('../PipelineProgressPanel', () => ({ PipelineProgressPanel: () => null }))

import { AIZone } from './AIZone'

function artifact(over: Record<string, unknown> = {}) {
  return {
    id: 'art1',
    ticker: 'AAPL',
    type: 'equity_research',
    created_at: new Date().toISOString(),
    verdict: 'BUY',
    target_price: 250,
    entry_price: 200,
    ...over,
  }
}

describe('AIZone verdict-card TargetGauge', () => {
  it('renders the gauge when a target AND a price are present', () => {
    latest = artifact()
    priceData = { current_price: 210 }
    const { container } = render(<AIZone ticker="AAPL" />)
    const gauge = container.querySelector('[data-testid="ai-zone-target-gauge"]')
    expect(gauge).not.toBeNull()
    // Above price → green; marker right of centre.
    const value = gauge!.querySelector('.target-gauge__value') as HTMLElement
    expect(value.style.color).toBe('var(--success)')
    const mark = gauge!.querySelector('.target-gauge__mark') as HTMLElement
    expect(parseFloat(mark.style.left)).toBeGreaterThan(50)
    expect(gauge!.textContent).toContain('250')
  })

  it('does NOT render the gauge when the target is withheld (target_price null)', () => {
    latest = artifact({ target_price: null })
    priceData = { current_price: 210 }
    const { container } = render(<AIZone ticker="AAPL" />)
    expect(container.querySelector('[data-testid="ai-zone-target-gauge"]')).toBeNull()
    // The withheld treatment still stands.
    expect(container.querySelector('[data-testid="ai-zone-target-withheld"]')).not.toBeNull()
  })

  it('falls back to entry_price (with an honest note) when no live quote is available', () => {
    latest = artifact({ entry_price: 180 })
    priceData = { current_price: null }
    const { container } = render(<AIZone ticker="AAPL" />)
    const gauge = container.querySelector('[data-testid="ai-zone-target-gauge"]')
    expect(gauge).not.toBeNull()
    // 250 vs entry 180 → above → green, and the degraded-anchor note is shown.
    expect(gauge!.textContent).toContain('vs price at creation')
  })

  it('omits the gauge entirely when neither a live quote NOR an entry_price exist', () => {
    latest = artifact({ entry_price: null })
    priceData = { current_price: null }
    const { container } = render(<AIZone ticker="AAPL" />)
    expect(container.querySelector('[data-testid="ai-zone-target-gauge"]')).toBeNull()
  })
})
