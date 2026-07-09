// Regression test for the catalyst-calendar + retail-sentiment loading and
// honest-failure states (both cards live in MarketDataZone — the workspace's
// LEFT market column).
//
// Two bugs are pinned here:
//   1. The catalyst calendar (~12s endpoint) used to render the "No recent
//      events" empty copy WHILE loading, reading as "no data". It must show a
//      skeleton until the fetch resolves.
//   2. The retail-sentiment card collapsed every non-available case into
//      "Adanos not configured", so a transient/provider error told a user who
//      HAD configured the key to go configure one. It must distinguish:
//        • loading        → skeleton
//        • transport error / reason='provider_error' → retry (NOT the CTA)
//        • reason='unconfigured' → the add-key CTA
//        • available      → the aggregate

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/useTickerData', () => ({
  useTickerPrice: vi.fn(),
  useTickerFinancials: vi.fn(),
  useTickerCatalysts: vi.fn(),
  useTickerHistoricalBands: vi.fn(),
}))
vi.mock('../../hooks/useTickerSentiment', () => ({
  useTickerSentiment: vi.fn(),
}))

import { MarketDataZone } from './MarketDataZone'
import {
  useTickerPrice,
  useTickerFinancials,
  useTickerCatalysts,
  useTickerHistoricalBands,
} from '../../hooks/useTickerData'
import { useTickerSentiment, type SentimentSnapshot } from '../../hooks/useTickerSentiment'

type AnyQuery = Record<string, unknown>

function settled(data: unknown): AnyQuery {
  return { data, isError: false, error: null, isPending: false, refetch: vi.fn() }
}
function pending(): AnyQuery {
  return { data: undefined, isError: false, error: null, isPending: true, refetch: vi.fn() }
}
function errored(): AnyQuery {
  return { data: undefined, isError: true, error: null, isPending: false, refetch: vi.fn() }
}

const SENTIMENT_OK: SentimentSnapshot = {
  ticker: 'NVDA',
  days: 7,
  available: true,
  coverage: '3/3',
  bullish_pct: 67,
  bearish_pct: 33,
  average_buzz: 140,
  source_alignment: 'aligned',
  sources: [],
  warnings: [],
}

function sentiment(partial: Partial<SentimentSnapshot>): SentimentSnapshot {
  return { ...SENTIMENT_OK, available: false, coverage: null, ...partial }
}

function renderZone() {
  return render(
    <MemoryRouter>
      <MarketDataZone ticker="NVDA" />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(useTickerPrice).mockReturnValue(settled({ history: null }) as never)
  vi.mocked(useTickerFinancials).mockReturnValue(settled({}) as never)
  vi.mocked(useTickerCatalysts).mockReturnValue(settled([]) as never)
  vi.mocked(useTickerSentiment).mockReturnValue(settled(SENTIMENT_OK) as never)
  // Band card hides when no band — the existing cases don't assert on it.
  vi.mocked(useTickerHistoricalBands).mockReturnValue({ data: undefined } as never)
})

describe('MarketDataZone — catalyst calendar loading state', () => {
  it('shows a skeleton while catalysts are loading, not the empty copy', () => {
    vi.mocked(useTickerCatalysts).mockReturnValue(pending() as never)
    renderZone()
    expect(screen.getByTestId('catalyst-skeleton')).toBeInTheDocument()
    expect(screen.queryByText(/No recent events/i)).not.toBeInTheDocument()
  })

  it('shows the empty copy only once the fetch resolves empty', () => {
    vi.mocked(useTickerCatalysts).mockReturnValue(settled([]) as never)
    renderZone()
    expect(screen.queryByTestId('catalyst-skeleton')).not.toBeInTheDocument()
    expect(screen.getByText(/No recent events/i)).toBeInTheDocument()
  })
})

// The cold catalyst fetch is ~12–18s; a bare shimmer reads as "broken" long
// before it returns. After a threshold the skeleton must surface a "classifying
// news" hint — but NOT immediately, so a warm-cache fetch returning in 1–2s
// never flashes copy that would itself look like a stall.
describe('MarketDataZone — catalyst skeleton progress hint', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not show the classify hint immediately (warm fetch must not flash it)', () => {
    vi.useFakeTimers()
    vi.mocked(useTickerCatalysts).mockReturnValue(pending() as never)
    renderZone()
    expect(screen.getByTestId('catalyst-skeleton')).toBeInTheDocument()
    expect(screen.queryByTestId('catalyst-classify-hint')).not.toBeInTheDocument()
  })

  it('surfaces the classify hint after the delay while still pending', () => {
    vi.useFakeTimers()
    vi.mocked(useTickerCatalysts).mockReturnValue(pending() as never)
    renderZone()
    act(() => {
      vi.advanceTimersByTime(6000)
    })
    expect(screen.getByTestId('catalyst-classify-hint')).toBeInTheDocument()
    expect(screen.getByText(/Classifying news/i)).toBeInTheDocument()
  })
})

// Cold-start: live-data routes 503 "starting" for the ~2s warmup window after the
// sidecar shows the WebView. The card must read as a CALM "engine starting" state
// (self-healing, the hooks fast-refetch on 503) — never the red "data unavailable"
// outage, which on every cold open would look like the app is broken.
describe('MarketDataZone — cold-start warming (503)', () => {
  function coldStart503(): AnyQuery {
    return {
      data: undefined,
      isError: true,
      error: { status: 503 },
      isPending: false,
      refetch: vi.fn(),
    }
  }

  it('a 503 renders the calm starting state, not the red outage error', () => {
    vi.mocked(useTickerPrice).mockReturnValue(coldStart503() as never)
    vi.mocked(useTickerFinancials).mockReturnValue(coldStart503() as never)
    renderZone()
    expect(screen.getAllByTestId('market-card-starting').length).toBeGreaterThan(0)
    expect(screen.queryByTestId('market-card-error')).not.toBeInTheDocument()
    expect(screen.getAllByText(/Data engine is starting/i).length).toBeGreaterThan(0)
  })

  it('a non-503 error still shows the red outage error (not mistaken for warming)', () => {
    vi.mocked(useTickerPrice).mockReturnValue({
      data: undefined,
      isError: true,
      error: { status: 502 },
      isPending: false,
      refetch: vi.fn(),
    } as never)
    renderZone()
    expect(screen.getByTestId('market-card-error')).toBeInTheDocument()
    expect(screen.queryByTestId('market-card-starting')).not.toBeInTheDocument()
  })
})

describe('MarketDataZone — retail sentiment honest states', () => {
  it('loading → skeleton, never the unconfigured CTA', () => {
    vi.mocked(useTickerSentiment).mockReturnValue(pending() as never)
    renderZone()
    expect(screen.getByTestId('sentiment-skeleton')).toBeInTheDocument()
    expect(screen.queryByTestId('sentiment-unconfigured')).not.toBeInTheDocument()
  })

  it('transport error → retry card, NOT "Adanos not configured"', () => {
    vi.mocked(useTickerSentiment).mockReturnValue(errored() as never)
    renderZone()
    expect(screen.getByTestId('market-card-error')).toBeInTheDocument()
    expect(screen.queryByTestId('sentiment-unconfigured')).not.toBeInTheDocument()
  })

  it('reason=provider_error (key IS set, call failed) → retry, NOT the CTA', () => {
    vi.mocked(useTickerSentiment).mockReturnValue(
      settled(sentiment({ reason: 'provider_error' })) as never,
    )
    renderZone()
    expect(screen.getByTestId('market-card-error')).toBeInTheDocument()
    expect(screen.queryByTestId('sentiment-unconfigured')).not.toBeInTheDocument()
    // The sentiment failure arrives as a 200 body (no HTTP status) — the card
    // must NOT fabricate "Upstream returned 5xx" (the prior `status ?? '5xx'`
    // bug). A status-free hint instead.
    expect(screen.queryByText(/5xx/i)).not.toBeInTheDocument()
  })

  it('reason=rate_limited → soft auto-retry notice, NOT the red 5xx error card', () => {
    vi.mocked(useTickerSentiment).mockReturnValue(
      settled(sentiment({ reason: 'rate_limited' })) as never,
    )
    renderZone()
    // Soft, self-healing state — distinct from the red outage error and never a
    // fabricated 5xx (the reported "Upstream returned 5xx" for a 429 throttle).
    expect(screen.getByTestId('sentiment-rate-limited')).toBeInTheDocument()
    expect(screen.queryByTestId('market-card-error')).not.toBeInTheDocument()
    expect(screen.queryByTestId('sentiment-unconfigured')).not.toBeInTheDocument()
    expect(screen.queryByText(/5xx/i)).not.toBeInTheDocument()
    expect(screen.getByText(/auto-retrying/i)).toBeInTheDocument()
  })

  it('reason=unconfigured → the add-key CTA', () => {
    vi.mocked(useTickerSentiment).mockReturnValue(
      settled(sentiment({ reason: 'unconfigured' })) as never,
    )
    renderZone()
    expect(screen.getByTestId('sentiment-unconfigured')).toBeInTheDocument()
    expect(screen.queryByTestId('market-card-error')).not.toBeInTheDocument()
  })

  it('available → the sentiment aggregate', () => {
    vi.mocked(useTickerSentiment).mockReturnValue(settled(SENTIMENT_OK) as never)
    renderZone()
    expect(screen.getByTestId('sentiment-available')).toBeInTheDocument()
    expect(screen.queryByTestId('sentiment-unconfigured')).not.toBeInTheDocument()
  })

  it('filters blank backend warnings instead of rendering empty warning glyphs', () => {
    vi.mocked(useTickerSentiment).mockReturnValue(
      settled({ ...SENTIMENT_OK, warnings: ['', '   ', 'stale sentiment cache used'] }) as never,
    )
    renderZone()
    expect(screen.getAllByTestId('market-warning-line')).toHaveLength(1)
    expect(screen.getByText(/stale sentiment cache used/)).toBeInTheDocument()
  })
})

describe('MarketDataZone — valuation band card', () => {
  const BAND = {
    ticker: 'NVDA',
    metric: 'ev_ebitda',
    current: 15,
    p25: 22,
    median: 24,
    p75: 26,
    p90: 29,
    sample_count: 751,
    classification: 'cheap',
  }

  it('renders the multiple-vs-own-history card when a band is present', () => {
    vi.mocked(useTickerHistoricalBands).mockReturnValue({ data: BAND } as never)
    renderZone()
    expect(screen.getByText(/Multiple vs Own History/i)).toBeInTheDocument()
    expect(screen.getByText('cheap')).toBeInTheDocument() // classification badge
    expect(screen.getByText(/now 15\.0/)).toBeInTheDocument() // current multiple marker
  })

  it('hides the card when no band could be computed (cold ticker / thin history)', () => {
    vi.mocked(useTickerHistoricalBands).mockReturnValue({ data: undefined } as never)
    renderZone()
    expect(screen.queryByText(/Multiple vs Own History/i)).not.toBeInTheDocument()
  })
})

// BACKLOG A6 呈现批 ②: this raw 5Y beta sits right next to the AI report's
// Blume-adjusted DCF/WACC β (same workspace, split view) with no reconcile —
// analysts flagged the two numbers as "disagreeing". Pins the caliber note.
describe('MarketDataZone — beta caliber reconcile', () => {
  it('labels Beta (5Y) as the raw regression value with an explanatory hover', () => {
    vi.mocked(useTickerFinancials).mockReturnValue(settled({ market: { beta: 1.13 } }) as never)
    renderZone()
    expect(screen.getByText('1.13')).toBeInTheDocument()
    expect(screen.getByText('Raw regression')).toBeInTheDocument()
    expect(screen.getByText('Raw regression')).toHaveAttribute(
      'title',
      expect.stringContaining('Blume'),
    )
  })
})
