// Workspace golden-path regression test.
//
// This is the closest we can run to a desktop walk-through in JSDOM. It
// exercises the user-visible checkpoints of the current workspace contract:
//
//   1. 冷启动 workspace 搜索进 NVDA → StockWorkspace mounts with sticky hero
//      + market/AI dual zones.
//   2. 点「立即跑 AI 研报」→ calls runStreamStore.startRun("research", ticker).
//   3. 等 SSE pipeline 6 step 进度面板走完 → PipelineProgressPanel renders one
//      row per step from the mocked run state.
//   4. 有 artifact 时 → AI zone surfaces latest card, chapter mini-grid, timeline.
//
// Real paint, font rendering, and native shell behavior are covered by
// Playwright/browser checks.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { StockWorkspace } from './StockWorkspace'

vi.mock('../lib/tauri', () => ({
  pickDirectory: vi.fn().mockResolvedValue(null),
  isTauri: vi.fn().mockReturnValue(false),
  openExternal: vi.fn().mockResolvedValue(undefined),
  DEFAULT_WORKSPACE_PATH: '~/finrobot',
}))

// Mock runStreamStore so we can drive states without a live SSE source.
const startRunMock = vi.fn().mockResolvedValue('run-stub-1')
const addToastMock = vi.fn()
// Returns true the first time per runId (the completion effect fires); reset in
// beforeEach so each test starts with a clean "first-notify" slate.
const markTerminalNotifiedMock = vi.fn().mockReturnValue(true)
let mockRunState: ReturnType<typeof makeRunState> | undefined

function makeRunState(overrides: Record<string, unknown> = {}) {
  return {
    runId: 'run-stub-1',
    ticker: 'NVDA',
    pipelineType: 'research',
    steps: [
      { name: 'data_collection', status: 'completed', duration_s: 4.2 },
      { name: 'catalyst_analysis', status: 'completed', duration_s: 5.8 },
      { name: 'peer_analysis', status: 'completed', duration_s: 3.1 },
      { name: 'financial_modeling', status: 'running' },
      { name: 'thesis', status: 'pending' },
      { name: 'report', status: 'pending' },
    ],
    status: 'running' as const,
    progress: 0.5,
    error: null,
    startedAt: Date.now(),
    dismissed: false,
    ...overrides,
  }
}

vi.mock('../stores/runStreamStore', () => {
  const storeState = () => ({
    runs: mockRunState ? { NVDA: mockRunState } : {},
    startRun: startRunMock,
    dismiss: vi.fn(),
    clear: vi.fn(),
    // BUG-085: terminal side-effects (toast + invalidations) dedupe at the
    // store level. Default to "first time" so the completion effect runs;
    // the dedupe-across-remount behaviour is covered in runStreamStore.test.
    markTerminalNotified: markTerminalNotifiedMock,
  })
  const useRunStreamStore = <T,>(selector: (s: unknown) => T) => selector(storeState())
  // launchResearch's duplicate-click guard reads the store imperatively
  // (useRunStreamStore.getState()) — mirror zustand's static API.
  useRunStreamStore.getState = storeState
  return {
    useRunStreamStore,
    selectRunByTicker: (ticker: string) => (s: { runs?: Record<string, unknown> }) =>
      s.runs?.[ticker],
  }
})

vi.mock('../stores/toastStore', () => ({
  useToastStore: <T,>(selector: (s: unknown) => T) =>
    selector({
      addToast: addToastMock,
      removeToast: vi.fn(),
      toasts: [],
    }),
}))

// Stub network so component queries resolve without a live backend.
beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    if (url.includes('/api/artifacts/by-ticker/NVDA/timeline')) {
      return jsonResponse([
        {
          id: 'art_2026-05-21T00:00:00_NVDA_equity_research',
          ticker: 'NVDA',
          cross_tickers: [],
          type: 'equity_research',
          created_at: '2026-05-19T00:00:00Z',
          headline: 'BUY · target $920 — 数据中心增速放缓但毛利率改善',
          source: 'pipeline:equity_research',
          archived: false,
          entry_price: 866.0,
          target_price: 920.0,
          target_date: '2027-05-19T00:00:00Z',
          signal: 'hit',
        },
        {
          id: 'art_2026-05-12T00:00:00_NVDA_dcf',
          ticker: 'NVDA',
          cross_tickers: [],
          type: 'dcf',
          created_at: '2026-05-12T00:00:00Z',
          headline: 'DCF implied $890',
          source: 'cli',
          archived: false,
          entry_price: 850.0,
          target_price: 890.0,
          target_date: '2027-05-12T00:00:00Z',
          signal: 'hit',
        },
        {
          id: 'art_2026-04-01T00:00:00_NVDA_lbo',
          ticker: 'NVDA',
          cross_tickers: [],
          type: 'lbo',
          created_at: '2026-04-01T00:00:00Z',
          headline: 'LBO IRR 18%',
          source: 'pipeline:lbo',
          archived: false,
          entry_price: 820.0,
          target_price: 900.0,
          target_date: '2027-04-01T00:00:00Z',
          signal: 'failed',
        },
      ])
    }
    if (url.includes('/api/valuation/aggregate/NVDA')) {
      return jsonResponse({
        ticker: 'NVDA',
        current_price: 876.42,
        as_of: '2026-05-21T00:00:00Z',
        methods: [
          {
            method: 'dcf',
            method_type: 'valuation',
            low: 800,
            mid: 920,
            high: 1040,
            confidence: 0.85,
            source: 'monte_carlo_p10_p90',
            warnings: [],
          },
        ],
        warnings: [],
      })
    }
    if (url.includes('/api/valuation/historical-bands/NVDA')) {
      return jsonResponse({
        ticker: 'NVDA',
        metric: 'ev_ebitda',
        current: 42,
        median: 35,
        p25: 31,
        p75: 38,
        p90: 41,
        timeline: [
          { date: '2024-01-01', value: 28 },
          { date: '2025-01-01', value: 33 },
          { date: '2026-01-01', value: 42 },
        ],
        sample_count: 3,
        classification: 'expensive',
        warnings: [],
      })
    }
    if (url.includes('/api/sentiment/NVDA')) {
      return jsonResponse({
        ticker: 'NVDA',
        days: 7,
        available: true,
        coverage: '2/3',
        bullish_pct: 67,
        bearish_pct: 33,
        average_buzz: 140,
        source_alignment: 'aligned',
        sources: [],
        warnings: [],
      })
    }
    if (url.includes('/api/data/NVDA/news')) {
      return jsonResponse({ items: [] })
    }
    if (url.includes('/api/data/NVDA/catalysts')) {
      return jsonResponse([])
    }
    if (url.includes('/api/data/NVDA/price')) {
      return jsonResponse({
        current_price: 876.42,
        change_pct: 1.2,
        price_history: Array.from({ length: 60 }, (_, i) => ({
          date: `2026-${String(Math.floor(i / 28) + 1).padStart(2, '0')}-${String(
            (i % 28) + 1,
          ).padStart(2, '0')}`,
          close: 800 + i,
        })),
      })
    }
    if (url.includes('/api/data/NVDA/quarterly')) {
      return jsonResponse({
        quarters: [
          { period: '2026Q1', revenue: 30e9, gross_margin: 0.72, net_income: 10e9 },
          { period: '2025Q4', revenue: 28e9, gross_margin: 0.71, net_income: 9.5e9 },
        ],
      })
    }
    if (url.includes('/api/data/NVDA/financials')) {
      return jsonResponse({ market_cap: 2.1e12, pe_ratio: 42 })
    }
    // Health preflight (BUG-027) — happy path: backend reachable, quotes warmed,
    // providers configured, no startup error → run CTA enabled.
    if (url.includes('/api/health/quotes-warmed')) {
      return jsonResponse({ warmed: true, studied_ticker_count: 3 })
    }
    if (url.endsWith('/api/settings')) {
      return jsonResponse({
        available_providers: ['fmp', 'yfinance'],
        startup_error: null,
      })
    }
    return jsonResponse({})
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  mockRunState = undefined
  startRunMock.mockClear()
  addToastMock.mockClear()
  // restoreAllMocks() wipes the implementation — re-arm the default so the next
  // test's completion effect still sees a "first notify".
  markTerminalNotifiedMock.mockClear().mockReturnValue(true)
})

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  )
}

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/stocks/NVDA']}>
        <Routes>
          <Route path="/stocks/:ticker" element={<StockWorkspace />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('workspace dashboard contract (P3.2 — analyst dashboard)', () => {
  it('Step 1: cold start renders TickerHero + dual zones (market data + AI)', async () => {
    renderWorkspace()
    // Hero with cosmic ticker glyph.
    expect(screen.getByTestId('ticker-hero')).toBeInTheDocument()
    // On cold start the AI zone shows a NEUTRAL loading state while it checks
    // the local report DB — never the "No report · Run now" terminal (that
    // would lie before the history query returns and arm a redundant run). The
    // run trigger only appears once we KNOW there are zero reports.
    expect(screen.getByTestId('ai-zone-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('run-analysis-trigger')).not.toBeInTheDocument()
    // Dual-zone dashboard: market data (left, always live) + AI zone (right).
    expect(screen.getByTestId('market-data-zone')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone')).toBeInTheDocument()
    // AnchorNav (the retired left-rail section nav) is not rendered — the app
    // does no keyboard shortcuts, so there is no command-palette successor either.
    expect(screen.queryByTestId('anchor-nav')).not.toBeInTheDocument()
  })

  it('Step 1c: empty history → LoadingState first, then ColdState + trigger (no premature trigger)', async () => {
    // Locks the actual bug: ColdState/run-trigger must NOT appear before the
    // history query resolves. Empty history → neutral loading first, then flip
    // to the cold CTA once we KNOW there are zero reports.
    mockTimeline([])
    renderWorkspace()
    // BEFORE resolution: neutral loading, NO run trigger, NO cold terminal.
    expect(screen.getByTestId('ai-zone-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('run-analysis-trigger')).not.toBeInTheDocument()
    expect(screen.queryByTestId('ai-zone-cold')).not.toBeInTheDocument()
    // AFTER it resolves to zero reports: ColdState + trigger appear, loading gone.
    expect(await screen.findByTestId('ai-zone-cold')).toBeInTheDocument()
    expect(screen.getByTestId('run-analysis-trigger')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-zone-loading')).not.toBeInTheDocument()
  })

  it('Step 1b: retail sentiment card consumes /api/sentiment (BUG-044)', async () => {
    // The mock for /api/sentiment/NVDA returns available:true, 67/33 bull/bear.
    // This proves the section is actually wired (previously the endpoint was
    // mocked but no UI consumed it). The market column is a flat vertical stack,
    // so the sentiment card renders without any tab navigation.
    renderWorkspace()
    const card = await screen.findByTestId('sentiment-available')
    expect(card).toBeInTheDocument()
    expect(card).toHaveTextContent('67%')
    expect(card).toHaveTextContent('33%')
    // Unconfigured CTA must NOT show when the snapshot is available.
    expect(screen.queryByTestId('sentiment-settings-cta')).not.toBeInTheDocument()
  })

  it('Step 2: 运行完整分析 fires research; no alt-pipeline UI surface exists', async () => {
    // Empty history → resolves to ColdState with the run trigger (the default
    // mock has a report → HotState, which has no cold trigger). The trigger
    // only appears AFTER the history query confirms zero reports.
    mockTimeline([])
    renderWorkspace()
    // 1 ticker = 1 run = 1 equity_research artifact carrying the full
    // 13-chapter payload.
    fireEvent.click(await screen.findByTestId('run-analysis-trigger'))
    expect(startRunMock).toHaveBeenCalledWith('research', 'NVDA')
    // No chevron / dropdown / alt-pipeline menu — single canonical entry.
    for (const id of [
      'run-analysis-more',
      'run-analysis-dropdown',
      'run-research',
      'run-ic-memo',
      'run-earnings',
      'run-dcf',
      'run-lbo',
      'run-ddm',
      'run-comps',
    ]) {
      expect(screen.queryByTestId(id)).not.toBeInTheDocument()
    }
  })

  it('Step 2b: run start failure surfaces a toast instead of leaving the CTA hanging', async () => {
    // Empty history → ColdState with an enabled run trigger (see Step 2).
    mockTimeline([])
    startRunMock.mockRejectedValueOnce(new Error('网络连接失败，请检查网络'))
    renderWorkspace()
    fireEvent.click(await screen.findByTestId('run-analysis-trigger'))
    await waitFor(() =>
      expect(addToastMock).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'error',
          title: 'Failed to start report',
          description: '网络连接失败，请检查网络',
        }),
      ),
    )
  })

  it('Step 3: pipeline progress panel renders 6 step rows from SSE-driven state', async () => {
    mockRunState = makeRunState()
    renderWorkspace()
    const panel = await screen.findByTestId('pipeline-progress-panel')
    expect(panel).toBeInTheDocument()
    for (const name of [
      'data_collection',
      'catalyst_analysis',
      'peer_analysis',
      'financial_modeling',
      'thesis',
      'report',
    ]) {
      expect(screen.getByTestId(`pipeline-step-${name}`)).toBeInTheDocument()
    }
  })

  it('Step 4: AI zone shows latest artifact card + verdict block + version timeline when artifacts exist', async () => {
    renderWorkspace()
    // Hot state surfaces (mock timeline returns 3 NVDA artifacts incl 1 equity_research).
    expect(await screen.findByTestId('ai-zone-latest')).toBeInTheDocument()
    // The redesign's left verdict-emphasis block replaces the old 13-chapter grid
    // (chapter navigation now lives behind "open full report" → the detail page).
    expect(screen.getByTestId('ai-zone-verdict-block')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone-timeline')).toBeInTheDocument()
    // Cold-state CTA is not shown when we have a hot artifact.
    expect(screen.queryByTestId('ai-zone-cold')).not.toBeInTheDocument()
    // "Open full report" CTA wires to the artifact detail route.
    expect(screen.getByTestId('open-latest-report')).toBeInTheDocument()
  })
})

// ── BUG-040: non-research artifacts must be reachable from the workspace ──────
//
// Landing recent counts ALL artifact types; a ticker that only has DCF/LBO/comps
// must NOT show the cold "还没跑 AI 研报" empty state with its non-research
// artifacts buried. It surfaces them in the OtherArtifacts list + a slimmer
// "no full report yet" card.

function mockTimeline(artifacts: unknown[]) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    if (url.includes('/api/artifacts/by-ticker/NVDA/timeline')) {
      return jsonResponse(artifacts)
    }
    if (url.includes('/api/health/quotes-warmed')) {
      return jsonResponse({ warmed: true, studied_ticker_count: 1 })
    }
    if (url.endsWith('/api/settings')) {
      return jsonResponse({ available_providers: ['fmp', 'yfinance'], startup_error: null })
    }
    if (url.includes('/api/data/NVDA/price')) {
      return jsonResponse({ current_price: 876.42, change_pct: 1.2, price_history: [] })
    }
    if (url.includes('/api/sentiment/NVDA')) {
      return jsonResponse({ ticker: 'NVDA', days: 7, available: false, sources: [], warnings: [] })
    }
    return jsonResponse({})
  })
}

describe('workspace surfaces all artifact types (BUG-040)', () => {
  it('a ticker with only a dcf artifact shows the artifact, not the cold empty state', async () => {
    mockTimeline([
      {
        id: 'art_2026-05-12T00:00:00_NVDA_dcf',
        ticker: 'NVDA',
        cross_tickers: [],
        type: 'dcf',
        created_at: '2026-05-12T00:00:00Z',
        headline: 'DCF implied $890',
        source: 'cli',
        archived: false,
        target_price: 890.0,
      },
    ])
    renderWorkspace()
    // The DCF surfaces as a live valuation instrument card (reading + version),
    // not buried in a generic artifact list (slice A: valuations ARE instruments).
    const dcf = await screen.findByTestId('instrument-dcf')
    expect(dcf).toBeInTheDocument()
    expect(dcf).toHaveTextContent('$890.00')
    // The "no full report yet" nudge replaces the misleading cold empty state.
    expect(screen.getByTestId('ai-zone-no-report')).toBeInTheDocument()
    // The big cold "还没跑 AI 研报" empty state must NOT show — the ticker has data.
    expect(screen.queryByTestId('ai-zone-cold')).not.toBeInTheDocument()
  })

  it('clicking a non-research artifact routes to its detail page', async () => {
    mockTimeline([
      {
        id: 'art_comps_1',
        ticker: 'NVDA',
        cross_tickers: [],
        type: 'comps',
        created_at: '2026-05-12T00:00:00Z',
        headline: 'Comps',
        source: 'pipeline:comps',
        archived: false,
      },
    ])
    renderWorkspace()
    // The comps detail query settles async (it carries no single price → the card
    // resolves to a withheld/value state, swapping the tile node); re-query via
    // waitFor so we assert on the settled card rather than a detached handle.
    await waitFor(() =>
      expect(screen.getByTestId('instrument-comps')).toHaveTextContent(
        /Comparable Companies|可比公司/,
      ),
    )
  })

  it('maps a legacy REVIEW summary to a neutral WITHHELD pill, never the word REVIEW or a HOLD hue', async () => {
    // The REVIEW verdict is deleted. New artifacts only ship BUY/HOLD/SELL; a
    // legacy stored "REVIEW" is mapped to the neutral WITHHELD display token —
    // readable, never the forbidden string, never borrowing the amber HOLD hue.
    mockTimeline([
      {
        id: 'art_review_1',
        ticker: 'NVDA',
        cross_tickers: [],
        type: 'equity_research',
        created_at: '2026-05-21T00:00:00Z',
        headline: 'Point target withheld; rating stands',
        source: 'pipeline:equity_research',
        archived: false,
        target_price: null,
        verdict: 'REVIEW',
      },
    ])
    renderWorkspace()

    expect(await screen.findByTestId('ai-zone-timeline')).toBeInTheDocument()
    const pill = screen
      .getAllByTestId('ai-zone-timeline-verdict')
      .find((el) => el.getAttribute('data-verdict') === 'WITHHELD')

    expect(pill).toBeDefined()
    expect(pill).toHaveTextContent('WITHHELD')
    expect(pill).not.toHaveTextContent('REVIEW')
    // The legacy WITHHELD token renders in a NEUTRAL slate — never the amber HOLD
    // hue (var(--card-hold-fg)), never the forbidden "REVIEW" string.
    expect(pill!.style.color).toBe('var(--text-muted)')
    expect(pill!.style.color).not.toBe('var(--card-hold-fg)')
  })
})

// ── BUG-027: preflight gates the run CTA + run errors map to friendly copy ────

describe('run preflight + friendly errors (BUG-027)', () => {
  it('disables the run CTA and shows a settings affordance when no provider is configured', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : (input as Request).url
      if (url.includes('/api/artifacts/by-ticker/NVDA/timeline')) return jsonResponse([])
      if (url.includes('/api/health/quotes-warmed')) {
        return jsonResponse({ warmed: true, studied_ticker_count: 0 })
      }
      // No providers configured + boot-time config error → preflight blocked.
      if (url.endsWith('/api/settings')) {
        return jsonResponse({ available_providers: [], startup_error: 'missing LLM key' })
      }
      if (url.includes('/api/data/NVDA/price')) {
        return jsonResponse({ current_price: 1, change_pct: 0, price_history: [] })
      }
      return jsonResponse({})
    })
    renderWorkspace()
    // The blocked affordance appears (routes to /settings), and the normal run
    // trigger is gone.
    expect(await screen.findByTestId('run-analysis-blocked')).toBeInTheDocument()
    expect(screen.queryByTestId('run-analysis-trigger')).not.toBeInTheDocument()
  })

  it('a failed run surfaces a mapped message, not a raw HTTP string', async () => {
    // Empty timeline → stable ColdState with the run trigger (no equity_research
    // artifact to flip into HotState). Happy health keeps the CTA enabled.
    mockTimeline([])
    // startRun rejects with the dev-facing "HTTP 500" form; the toast must route
    // it through mapErrorToUserMessage so the raw string never leaks.
    startRunMock.mockRejectedValueOnce(new Error('HTTP 500 Internal Server Error'))
    renderWorkspace()
    fireEvent.click(await screen.findByTestId('run-analysis-trigger'))
    await waitFor(() => expect(addToastMock).toHaveBeenCalled())
    const errorToast = addToastMock.mock.calls
      .map((c) => c[0])
      .find((a: { type?: string }) => a.type === 'error')
    expect(errorToast).toBeDefined()
    // mapErrorToUserMessage turns "HTTP 500" into the friendly server-unavailable
    // copy — the raw dev string must not leak.
    expect(errorToast.description).not.toMatch(/HTTP 500/)
  })
})

// ── Gate tests (P0 事实层根治 Task 13) ────────────────────────────────────────
//
// These tests exercise the StockWorkspace price gate. Invalid tickers still
// stop at the gate; upstream price outages render the workspace shell so the
// AI run/timeline column remains usable while market data degrades locally.
//
// Protocol:
//   - FetchHttpError(422) → TickerNotFoundView (data-testid="ticker-not-found")
//   - anything else → workspace shell (data-testid="stock-workspace")
//
// The mock replaces the global fetch so that calls to /api/data/*/price get
// the desired failure, while all other endpoints return {} so react-query
// doesn't pile up unrelated errors that could mask the gate signal.
//
// Note: we do NOT construct FetchHttpError directly in the test — the fetcher
// inside useTickerData reads Response.ok and throws FetchHttpError itself.
// TypeError / plain Error tests reject the promise to simulate network-layer
// failures.

function mockPriceFetchError(err: Error | Response) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    if (url.includes('/api/data/') && url.includes('/price')) {
      if (err instanceof Response) {
        return Promise.resolve(err)
      }
      return Promise.reject(err)
    }
    // List endpoints must return shape-correct empties ([]), not {} — AIZone's
    // useLatestArtifact calls .find() on the timeline payload and an {} body
    // crashes the whole tree before the gate can render.
    if (url.includes('/timeline') || url.includes('/catalysts')) {
      return jsonResponse([])
    }
    // All other endpoints return 200 {} so no unrelated query errors mask the gate.
    return jsonResponse({})
  })
}

describe('workspace gate (P0 事实层根治 Task 13)', () => {
  it('422 from /price → renders TickerNotFoundView', async () => {
    mockPriceFetchError(
      new Response('{"detail":"未知 ticker"}', {
        status: 422,
        statusText: 'Unprocessable Entity',
      }),
    )
    renderWorkspace()
    expect(await screen.findByTestId('ticker-not-found')).toBeInTheDocument()
    expect(screen.queryByTestId('market-data-zone')).not.toBeInTheDocument()
  })

  it('502 from /price → still renders workspace shell', async () => {
    mockPriceFetchError(
      new Response('{"detail":"数据源暂不可用"}', { status: 502, statusText: 'Bad Gateway' }),
    )
    renderWorkspace()
    expect(await screen.findByTestId('stock-workspace')).toBeInTheDocument()
    expect(screen.getByTestId('market-data-zone')).toBeInTheDocument()
  })

  it('503 from /price → still renders workspace shell', async () => {
    mockPriceFetchError(
      new Response('{"detail":"capability disabled"}', {
        status: 503,
        statusText: 'Service Unavailable',
      }),
    )
    renderWorkspace()
    expect(await screen.findByTestId('stock-workspace')).toBeInTheDocument()
  })

  it('500 from /price → still renders workspace shell', async () => {
    mockPriceFetchError(
      new Response('{"detail":"unexpected"}', {
        status: 500,
        statusText: 'Internal Server Error',
      }),
    )
    renderWorkspace()
    expect(await screen.findByTestId('stock-workspace')).toBeInTheDocument()
  })

  it('network error (TypeError) → still renders workspace shell', async () => {
    mockPriceFetchError(new TypeError('Failed to fetch'))
    renderWorkspace()
    expect(await screen.findByTestId('stock-workspace')).toBeInTheDocument()
  })

  it('plain Error → still renders workspace shell', async () => {
    mockPriceFetchError(new Error('Network request failed'))
    renderWorkspace()
    expect(await screen.findByTestId('stock-workspace')).toBeInTheDocument()
  })
})
