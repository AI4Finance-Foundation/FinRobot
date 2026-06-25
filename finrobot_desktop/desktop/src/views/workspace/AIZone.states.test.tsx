import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Deterministic coverage of the AI-zone state machine — the part the
// adversarial review flagged as untested: the loading / cold / error split and
// the `backendBooting` gate on the error state. We mock the hooks directly so
// timeline-query state (loading / errored / resolved-empty) and health level
// (starting / offline / connected) are set exactly, free of the real
// useHealth's module-level `backendSeenOnce` latch + 120s boot-grace timing.

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ ticker: 'NVDA' }),
}))
vi.mock('../../stores/runStreamStore', () => ({
  useRunStreamStore: (selector: (s: unknown) => unknown) =>
    selector({ startRun: vi.fn(), dismiss: vi.fn(), __runs: {} }),
  selectRunByTicker:
    (ticker: string) =>
    (s: { __runs?: Record<string, unknown> }): unknown =>
      s.__runs?.[ticker],
}))

// ── controllable timeline query ──────────────────────────────────────────────
let tlData: unknown[] | undefined
let tlLoading: boolean
let tlError: boolean
vi.mock('../../hooks/useV5Artifacts', () => ({
  useLatestArtifact: () => ({
    latest: (tlData ?? []).find((a) => (a as { type?: string }).type === 'equity_research') ?? null,
    isLoading: tlLoading,
    isError: tlError,
    error: tlError ? new Error('boom') : null,
    refetch: vi.fn(),
  }),
  useV5ArtifactTimeline: () => ({
    data: tlData,
    isLoading: tlLoading,
    isError: tlError,
    refetch: vi.fn(),
  }),
  useArtifactDetail: () => ({ data: undefined, isLoading: false }),
}))

// ── controllable health ──────────────────────────────────────────────────────
type HealthLevel = 'starting' | 'connected' | 'degraded' | 'offline'
let healthLevel: HealthLevel
let healthPlaceholder: boolean
vi.mock('../../hooks/useHealth', () => ({
  useHealth: () => ({
    data: {
      level: healthLevel,
      backendReachable: healthLevel === 'connected' || healthLevel === 'degraded',
      startupError: null,
      availableProviders: ['fmp'],
      modelConfigured: true,
    },
    isPlaceholderData: healthPlaceholder,
  }),
}))

vi.mock('../../hooks/useTickerData', () => ({ useTickerPrice: () => ({ data: undefined }) }))
vi.mock('../../stores/toastStore', () => ({ useToastStore: () => vi.fn() }))
vi.mock('../../i18n', () => ({
  useI18n: () => ({ locale: 'en', t: (k: string) => k }),
  tSync: (k: string) => k,
}))
vi.mock('../PipelineProgressPanel', () => ({ PipelineProgressPanel: () => null }))

import { AIZone } from './AIZone'

beforeEach(() => {
  tlData = undefined
  tlLoading = false
  tlError = false
  healthLevel = 'connected'
  healthPlaceholder = false
})

describe('AIZone state machine (loading / cold / error × backendBooting)', () => {
  it('history query in flight → neutral LoadingState, never the "No report · Run" terminal', () => {
    tlLoading = true
    tlData = undefined
    render(<AIZone ticker="NVDA" />)
    expect(screen.getByTestId('ai-zone-loading')).toBeInTheDocument()
    // The lie + the footgun: neither may appear before the query resolves.
    expect(screen.queryByTestId('run-analysis-trigger')).not.toBeInTheDocument()
    expect(screen.queryByTestId('ai-zone-cold')).not.toBeInTheDocument()
    expect(screen.queryByTestId('ai-zone-error')).not.toBeInTheDocument()
  })

  it('query RESOLVED to zero reports (backend connected) → ColdState with the run trigger', () => {
    tlData = []
    tlLoading = false
    render(<AIZone ticker="NVDA" />)
    expect(screen.getByTestId('ai-zone-cold')).toBeInTheDocument()
    expect(screen.getByTestId('run-analysis-trigger')).toBeInTheDocument()
    // The loading skeleton is gone once we KNOW there are zero reports.
    expect(screen.queryByTestId('ai-zone-loading')).not.toBeInTheDocument()
  })

  it('query error while backend CONNECTED → red error state + retry', () => {
    tlError = true
    healthLevel = 'connected'
    render(<AIZone ticker="NVDA" />)
    expect(screen.getByTestId('ai-zone-error')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone-retry')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-zone-loading')).not.toBeInTheDocument()
  })

  // The regression the adversarial review caught: a backend that is CONFIRMED
  // offline (crashed mid-session / never came up past the boot grace) with an
  // errored query must surface the error + Retry — NOT a perpetual neutral
  // skeleton with no way out (which is what `&& backendReachable` produced).
  it('query error while backend CONFIRMED OFFLINE → red error + retry, NOT a stuck skeleton', () => {
    tlError = true
    healthLevel = 'offline'
    render(<AIZone ticker="NVDA" />)
    expect(screen.getByTestId('ai-zone-error')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone-retry')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-zone-loading')).not.toBeInTheDocument()
  })

  it('query error while sidecar STILL STARTING → neutral loading, no red flash (transient boot)', () => {
    tlError = true
    healthLevel = 'starting'
    render(<AIZone ticker="NVDA" />)
    expect(screen.getByTestId('ai-zone-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-zone-error')).not.toBeInTheDocument()
  })

  it('query error while the FIRST health probe is still in flight → neutral loading', () => {
    tlError = true
    healthPlaceholder = true // health === null in AIZone
    render(<AIZone ticker="NVDA" />)
    expect(screen.getByTestId('ai-zone-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-zone-error')).not.toBeInTheDocument()
  })
})
