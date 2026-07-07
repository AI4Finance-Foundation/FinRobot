import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Regression lock (2026-07-07): a running 13-chapter research run must NOT
// unmount the bottom tools row. ValuationInstruments was designed to stay
// visible and lock its own launch buttons during any run (lockOthers), but
// AIZone once gated the whole row behind `!researchRunning`, so starting a
// report made the four instrument cards vanish. The gate is gone; this file
// pins the survival of the row through a live research run.

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ ticker: 'NVDA' }),
}))

// Controllable run slot — unlike the states harness, the run map is mutable so
// a test can hold a mid-flight research run.
let mockRuns: Record<string, unknown>
vi.mock('../../stores/runStreamStore', () => ({
  useRunStreamStore: (selector: (s: unknown) => unknown) =>
    selector({ startRun: vi.fn(), dismiss: vi.fn(), __runs: mockRuns }),
  selectRunByTicker:
    (ticker: string) =>
    (s: { __runs?: Record<string, unknown> }): unknown =>
      s.__runs?.[ticker],
}))

let tlData: unknown[] | undefined
vi.mock('../../hooks/useV5Artifacts', () => ({
  useLatestArtifact: () => ({
    latest: (tlData ?? []).find((a) => (a as { type?: string }).type === 'equity_research') ?? null,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  useV5ArtifactTimeline: () => ({
    data: tlData,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useArtifactDetail: () => ({ data: undefined, isLoading: false }),
}))

vi.mock('../../hooks/useHealth', () => ({
  useHealth: () => ({
    data: {
      level: 'connected',
      backendReachable: true,
      startupError: null,
      availableProviders: ['fmp'],
      modelConfigured: true,
    },
    isPlaceholderData: false,
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

const runningResearch = {
  runId: 'run_test_research',
  ticker: 'NVDA',
  pipelineType: 'research',
  status: 'running',
  steps: [],
  error: null,
}

beforeEach(() => {
  mockRuns = {}
  tlData = []
})

describe('AIZone tools row survives a running research run', () => {
  it('mid research run → ValuationInstruments stays mounted (locked, not hidden)', () => {
    mockRuns = { NVDA: runningResearch }
    render(<AIZone ticker="NVDA" />)
    expect(screen.getByTestId('ai-zone-tools-row')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone-standalone-launcher')).toBeInTheDocument()
  })

  it('idle (control) → tools row renders exactly the same', () => {
    render(<AIZone ticker="NVDA" />)
    expect(screen.getByTestId('ai-zone-tools-row')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone-standalone-launcher')).toBeInTheDocument()
  })
})
