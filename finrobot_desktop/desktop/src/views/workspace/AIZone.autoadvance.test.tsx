import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'

// UX-002: when a research run the user is WATCHING transitions running→completed,
// AIZone drills straight into the report instead of stranding them on an "open"
// button. These tests drive the run store across that transition and assert the
// navigation (and its guards: fresh transition only, research only, once).

const navigate = vi.fn()
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))

let runState: Record<string, unknown> | undefined
const dismiss = vi.fn()
const startRun = vi.fn()
vi.mock('../../stores/runStreamStore', () => ({
  useRunStreamStore: (selector: (s: unknown) => unknown) =>
    selector({ startRun, dismiss, __runs: { AAPL: runState } }),
  selectRunByTicker:
    (ticker: string) =>
    (s: { __runs?: Record<string, unknown> }): unknown =>
      s.__runs?.[ticker],
}))

vi.mock('../../hooks/useV5Artifacts', () => ({
  useLatestArtifact: () => ({
    latest: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  useV5ArtifactTimeline: () => ({
    data: [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
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
// AIZone now reads the live quote (TargetGauge "now" tick). Stub it so these
// cold/running auto-advance scenarios don't need a QueryClientProvider.
vi.mock('../../hooks/useTickerData', () => ({
  useTickerPrice: () => ({ data: undefined }),
}))
vi.mock('../../stores/toastStore', () => ({ useToastStore: () => vi.fn() }))
vi.mock('../../i18n', () => ({
  useI18n: () => ({ locale: 'en', t: (k: string) => k }),
  tSync: (k: string) => k,
}))
vi.mock('../PipelineProgressPanel', () => ({ PipelineProgressPanel: () => null }))

import { AIZone } from './AIZone'

function running() {
  return {
    status: 'running',
    artifactId: 'art1',
    artifactType: 'equity_research',
    cancelling: false,
    dismissed: false,
  }
}
function completed(over: Record<string, unknown> = {}) {
  return {
    status: 'completed',
    artifactId: 'art1',
    artifactType: 'equity_research',
    cancelling: false,
    dismissed: false,
    ...over,
  }
}

describe('AIZone auto-advance (UX-002)', () => {
  beforeEach(() => {
    navigate.mockClear()
    dismiss.mockClear()
    runState = undefined
  })

  it('drills into the report when a watched run completes', () => {
    runState = running()
    const { rerender } = render(<AIZone ticker="AAPL" />)
    expect(navigate).not.toHaveBeenCalled() // still running

    runState = completed()
    rerender(<AIZone ticker="AAPL" />)
    expect(navigate).toHaveBeenCalledWith('/stocks/AAPL/runs/art1')
    expect(dismiss).toHaveBeenCalledWith('AAPL')
  })

  it('does NOT yank a user who lands on a workspace with an already-completed run', () => {
    runState = completed() // completed on first render — no prior 'running' observed here
    render(<AIZone ticker="AAPL" />)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('does not auto-open a non-research result (DCF/LBO keep their panel CTA)', () => {
    runState = running()
    const { rerender } = render(<AIZone ticker="AAPL" />)
    runState = completed({ artifactType: 'dcf' })
    rerender(<AIZone ticker="AAPL" />)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('advances a given artifact at most once', () => {
    runState = running()
    const { rerender } = render(<AIZone ticker="AAPL" />)
    runState = completed()
    rerender(<AIZone ticker="AAPL" />)
    expect(navigate).toHaveBeenCalledTimes(1)
    // A benign re-render with the same completed run must not navigate again.
    rerender(<AIZone ticker="AAPL" />)
    expect(navigate).toHaveBeenCalledTimes(1)
  })
})
