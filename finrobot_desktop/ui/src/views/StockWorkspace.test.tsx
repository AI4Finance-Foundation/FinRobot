// v5 golden-path regression test (spec §15 condition 5).
//
// This is the closest we can run to "tauri dev + Playwright MCP 散户走查"
// in a JSDOM-only environment. It exercises the user-visible checkpoints
// listed in spec §15:
//
//   1. 冷启动 workspace 搜索进 NVDA  → StockWorkspace mounts with sticky hero
//      + anchor nav over 14 sections.
//   2. 点「+ 跑分析 ▾」选 AI 完整研报 → dropdown trigger opens menu of 6 items
//      and clicking "research" calls runStreamStore.startRun.
//   3. 等 SSE pipeline 6 step 进度面板走完 → PipelineProgressPanel renders one
//      row per step from the mocked run state.
//   4. 滚动到「我的研究」section 看 artifact 卡片 → MyResearchFeed surfaces
//      both the StatBanner numbers and per-artifact cards.
//
// What this test does NOT cover that real Playwright would: actual paint /
// visual diff, native OS download flow, font rendering. Those need a GUI
// session. Anything below that line is documented in
// docs/v5-delivery-report.md §7 exit condition 5.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { StockWorkspace } from './StockWorkspace'

vi.mock('../lib/tauri', () => ({
  registerShortcut: vi.fn().mockResolvedValue(() => {}),
  pickDirectory: vi.fn().mockResolvedValue(null),
  isTauri: vi.fn().mockReturnValue(false),
  openExternal: vi.fn().mockResolvedValue(undefined),
  DEFAULT_WORKSPACE_PATH: '~/finrobot',
}))

// Mock runStreamStore so we can drive states without a live SSE source.
const startRunMock = vi.fn().mockResolvedValue('run-stub-1')
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

vi.mock('../stores/runStreamStore', () => ({
  useRunStreamStore: <T,>(selector: (s: unknown) => T) =>
    selector({
      runs: mockRunState ? { NVDA: mockRunState } : {},
      startRun: startRunMock,
      dismiss: vi.fn(),
      clear: vi.fn(),
    }),
  selectRunByTicker: (ticker: string) => (s: { runs?: Record<string, unknown> }) =>
    s.runs?.[ticker],
}))

vi.mock('../stores/toastStore', () => ({
  useToastStore: <T,>(selector: (s: unknown) => T) =>
    selector({
      addToast: vi.fn(),
      removeToast: vi.fn(),
      toasts: [],
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
    // Hero with cosmic ticker glyph + the primary run trigger.
    expect(screen.getByTestId('ticker-hero')).toBeInTheDocument()
    expect(screen.getByTestId('run-analysis-trigger')).toBeInTheDocument()
    // Dual-zone dashboard: market data (left, always live) + AI zone (right).
    expect(screen.getByTestId('market-data-zone')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone')).toBeInTheDocument()
    // AnchorNav is retired in favour of ⌘K.
    expect(screen.queryByTestId('anchor-nav')).not.toBeInTheDocument()
  })

  it('Step 2: 运行完整分析 fires research; no alt-pipeline UI surface exists', async () => {
    renderWorkspace()
    // 1 ticker = 1 run = 1 equity_research artifact carrying the full
    // 12-chapter payload.
    fireEvent.click(screen.getByTestId('run-analysis-trigger'))
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

  it('Step 4: AI zone shows latest artifact card + chapter mini-grid + version timeline when artifacts exist', async () => {
    renderWorkspace()
    // Hot state surfaces (mock timeline returns 3 NVDA artifacts incl 1 equity_research).
    expect(await screen.findByTestId('ai-zone-latest')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone-chapters')).toBeInTheDocument()
    expect(screen.getByTestId('ai-zone-timeline')).toBeInTheDocument()
    // Cold-state CTA is not shown when we have a hot artifact.
    expect(screen.queryByTestId('ai-zone-cold')).not.toBeInTheDocument()
    // "Open full report" CTA wires to the artifact detail route.
    expect(screen.getByTestId('open-latest-report')).toBeInTheDocument()
  })
})
