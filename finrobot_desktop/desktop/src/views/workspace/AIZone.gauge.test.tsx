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
  useArtifactDetail: () => ({ data: undefined, isLoading: false }),
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

let priceData: { current_price: number | null; quote_currency?: string | null } | undefined
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
    // Live 210 drives the NOW marker; target 250 sits above it.
    expect(gauge!.textContent).toContain('NOW 210')
    expect(gauge!.textContent).toContain('TGT 250')
    // Above price → implied-return readout is green ▲.
    const upside = container.querySelector('[data-testid="ai-zone-target-upside"]') as HTMLElement
    expect(upside.textContent).toContain('▲')
    expect(upside.style.color).toBe('var(--card-buy-fg)')
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

  // ── cross-currency: the live quote is the canonical PRICE (NEVER FX-normalized),
  // so a foreign LOCAL listing's quote (2330.TW → TWD) must NOT be compared against
  // the artifact's USD target. The client can't run FX → drop the live quote and
  // degrade to the USD entry_price anchor (abstain, never mix). This is the in-
  // browser twin of the backend coverage/dashboard/valuation cross-currency fix.
  it('drops a foreign-currency live quote and degrades to the USD entry anchor', () => {
    latest = artifact({ entry_price: 180 }) // USD entry, USD target 250
    // TWD live quote 7000: if used raw, 250/7000−1 ≈ −0.96 → RED, marker far left.
    priceData = { current_price: 7000, quote_currency: 'TWD' }
    const { container } = render(<AIZone ticker="2330.TW" />)
    const gauge = container.querySelector('[data-testid="ai-zone-target-gauge"]')
    expect(gauge).not.toBeNull()
    // The gauge's "now" is the USD entry 180, NOT the raw TWD 7000 — proving the
    // foreign quote was dropped, not mixed into the USD gap.
    expect(gauge!.textContent).toContain('NOW 180')
    expect(gauge!.textContent).not.toContain('7000')
    // entry 180 vs target 250 → ABOVE → green ▲ (the raw-TWD path would be red ▼).
    const upside = container.querySelector('[data-testid="ai-zone-target-upside"]') as HTMLElement
    expect(upside.textContent).toContain('▲')
    expect(upside.style.color).toBe('var(--card-buy-fg)')
    // …and the note names the cross-currency reason, not "unavailable".
    expect(gauge!.textContent).toContain('foreign currency')
  })

  it('uses an explicit-USD live quote normally (US universe no regression)', () => {
    latest = artifact()
    priceData = { current_price: 210, quote_currency: 'USD' }
    const { container } = render(<AIZone ticker="AAPL" />)
    const gauge = container.querySelector('[data-testid="ai-zone-target-gauge"]')
    expect(gauge).not.toBeNull()
    // Live 210 drives the tick (not entry) → no degraded-anchor note.
    expect(gauge!.textContent).not.toContain('vs price at creation')
  })

  // Each marker (tick + label) is absolutely positioned at its value's % on the
  // track, so the label can NEVER mismatch its marker. These guard the value→
  // position mapping: on a downside call (now > target) the Target tick sits LEFT
  // of the Now tick (lower value = lower %), and vice-versa on an upside call.
  function markerPct(container: HTMLElement, which: 'now' | 'target'): number {
    const el = container.querySelector(`[data-testid="ai-zone-gauge-${which}"]`) as HTMLElement
    return parseFloat(el.getAttribute('data-pct') ?? 'NaN')
  }

  it('positions the Target tick LEFT of the Now tick on a downside call', () => {
    latest = artifact({ target_price: 100 }) // target 100 < live 150 → downside
    priceData = { current_price: 150 }
    const { container } = render(<AIZone ticker="AAPL" />)
    expect(container.querySelector('[data-testid="ai-zone-target-gauge"]')).not.toBeNull()
    // Lower value (target 100) → smaller % → left of the now (150) tick.
    expect(markerPct(container, 'target')).toBeLessThan(markerPct(container, 'now'))
    // Downside → red ▼ implied-return readout (no regression in the directional hue).
    const upside = container.querySelector('[data-testid="ai-zone-target-upside"]') as HTMLElement
    expect(upside.textContent).toContain('▼')
    expect(upside.style.color).toBe('var(--card-sell-fg)')
  })

  it('positions the Now tick LEFT of the Target tick on an upside call', () => {
    latest = artifact({ target_price: 250 }) // target 250 > live 210 → upside
    priceData = { current_price: 210 }
    const { container } = render(<AIZone ticker="AAPL" />)
    // Lower value (now 210) → smaller % → left of the target (250) tick.
    expect(markerPct(container, 'now')).toBeLessThan(markerPct(container, 'target'))
  })
})
