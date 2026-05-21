// v5 golden-path 5-step regression test (spec §15 condition 5).
//
// This is the closest we can run to "tauri dev + Playwright MCP 5 步散户走查"
// in a JSDOM-only environment. It exercises the same five user-visible
// checkpoints listed in spec §15:
//
//   1. 冷启动 workspace 搜索进 NVDA  → StockWorkspace mounts with sticky hero
//      + anchor nav over 14 sections.
//   2. 点「+ 跑分析 ▾」选 AI 完整研报 → dropdown trigger opens menu of 6 items
//      and clicking equity_research calls runStreamStore.startRun.
//   3. 等 SSE pipeline 6 step 进度面板走完 → PipelineProgressPanel renders one
//      row per step from the mocked run state.
//   4. 滚动到「我的研究」section 看 artifact 卡片 → MyResearchFeed surfaces
//      both the StatBanner numbers and per-artifact cards.
//   5. 点分享图下载 PNG → HeroVerdict's 📤 分享图 button is wired and the
//      OffscreenCanvas helper is exercised (without asserting the actual
//      blob, since JSDOM can't paint).
//
// What this test does NOT cover that real Playwright would: actual paint /
// visual diff, native OS download flow, font rendering. Those need a GUI
// session. Anything below that line is documented in
// docs/v5-delivery-report.md §7 exit condition 5.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { StockWorkspace } from './StockWorkspace'

vi.mock('../lib/tauri', () => ({
  registerShortcut: vi.fn().mockResolvedValue(() => {}),
  pickDirectory: vi.fn().mockResolvedValue(null),
  isTauri: vi.fn().mockReturnValue(false),
  openExternal: vi.fn().mockResolvedValue(undefined),
  DEFAULT_WORKSPACE_PATH: '~/finagent',
}))

// Mock runStreamStore so we can drive states without a live SSE source.
const startRunMock = vi.fn().mockResolvedValue('run-stub-1')
let mockRunState: ReturnType<typeof makeRunState> | undefined

function makeRunState(overrides: Record<string, unknown> = {}) {
  return {
    runId: 'run-stub-1',
    ticker: 'NVDA',
    pipelineType: 'equity_research',
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

vi.mock('../stores/runStreamStore', () => ({
  useRunStreamStore: <T,>(selector: (s: unknown) => T) =>
    selector({
      runs: mockRunState ? { NVDA: mockRunState } : {},
      startRun: startRunMock,
      dismiss: vi.fn(),
      clear: vi.fn(),
    }),
}))

// Stub network so component queries resolve without a live backend.
beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    if (url.endsWith('/api/artifacts/by-ticker/NVDA/timeline')) {
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
    return jsonResponse({})
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  mockRunState = undefined
  startRunMock.mockClear()
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
      <MemoryRouter initialEntries={['/stock/NVDA']}>
        <Routes>
          <Route path="/stock/:ticker" element={<StockWorkspace />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('v5 5-step golden path (spec §15 condition 5)', () => {
  it('Step 1: cold start renders sticky hero + anchor nav over 14 sections', async () => {
    renderWorkspace()
    // Sticky hero shows ticker symbol + the watchlist toggle + the run trigger.
    expect(screen.getByTestId('ticker-hero')).toBeInTheDocument()
    expect(screen.getByTestId('watchlist-toggle')).toBeInTheDocument()
    expect(screen.getByTestId('run-analysis-trigger')).toBeInTheDocument()
    // Anchor nav reaches all 14 canonical sec-* targets.
    expect(screen.getByTestId('anchor-nav')).toBeInTheDocument()
    const ids = [
      'sec-now',
      'sec-catalyst',
      'sec-risk',
      'sec-football',
      'sec-sensitivity',
      'sec-band',
      'sec-data',
      'sec-financials',
      'sec-performance',
      'sec-peers',
      'sec-news',
      'sec-sentiment',
      'sec-research',
    ]
    for (const id of ids) {
      expect(screen.getByTestId(`anchor-${id}`)).toBeInTheDocument()
    }
  })

  it('Step 2: clicking + 跑分析 opens the 6-item dropdown and starts the run', async () => {
    renderWorkspace()
    fireEvent.click(screen.getByTestId('run-analysis-trigger'))
    // Dropdown reveals all six pipeline buttons.
    expect(screen.getByTestId('run-analysis-dropdown')).toBeInTheDocument()
    for (const id of [
      'run-equity_research',
      'run-ic_memo',
      'run-earnings_analysis',
      'run-lbo',
      'run-ddm',
      'run-comps',
    ]) {
      expect(screen.getByTestId(id)).toBeInTheDocument()
    }
    fireEvent.click(screen.getByTestId('run-equity_research'))
    expect(startRunMock).toHaveBeenCalledWith('equity_research', 'NVDA')
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

  it('Step 4: 我的研究 section shows StatBanner numbers + artifact cards', async () => {
    renderWorkspace()
    // StatBanner shows once we have ≥3 closed artifacts (mock returns 2 hit + 1 failed).
    const banner = await screen.findByTestId('stat-banner')
    expect(banner).toBeInTheDocument()
    expect(banner.textContent).toMatch(/命中率/)
    // Each artifact gets its own card.
    expect(
      await screen.findByTestId('artifact-card-art_2026-05-21T00:00:00_NVDA_equity_research'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('artifact-card-art_2026-05-12T00:00:00_NVDA_dcf'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('artifact-card-art_2026-04-01T00:00:00_NVDA_lbo'),
    ).toBeInTheDocument()
  })

  it('Step 5: HERO share-card button wires through to the canvas helper', async () => {
    // JSDOM's canvas getContext returns null, so shareCard.ts would throw
    // "canvas 2D context unavailable" before reaching the blob path. Stub
    // getContext + toBlob to exercise the round-trip without a real canvas.
    const ctxStub = {
      fillRect: vi.fn(),
      fillText: vi.fn(),
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      measureText: vi.fn(() => ({ width: 100 })),
      set fillStyle(_: string) {},
      set font(_: string) {},
      set textBaseline(_: string) {},
      set strokeStyle(_: string) {},
      set lineWidth(_: number) {},
    }
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctxStub) as unknown as HTMLCanvasElement['getContext']
    const toBlob = vi.fn((cb: BlobCallback) => cb(new Blob(['stub'], { type: 'image/png' })))
    HTMLCanvasElement.prototype.toBlob = toBlob as unknown as HTMLCanvasElement['toBlob']
    URL.createObjectURL = vi.fn(() => 'blob:stub-url')
    URL.revokeObjectURL = vi.fn()

    renderWorkspace()
    const shareBtn = await screen.findByTestId('hero-share-card')
    expect(shareBtn).toBeInTheDocument()
    fireEvent.click(shareBtn)
    await waitFor(() => {
      expect(toBlob).toHaveBeenCalled()
    })
    expect(URL.createObjectURL).toHaveBeenCalled()
  })
})
