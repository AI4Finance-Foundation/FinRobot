// Regression test for the MarketEventsZone loading + honest-failure states.
// (Catalyst calendar + retail sentiment now live in MarketEventsZone — the
// full-width band below the workspace grid — split out of MarketDataZone.)
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

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/useTickerData', () => ({
  useTickerPrice: vi.fn(),
  useTickerFinancials: vi.fn(),
  useTickerCatalysts: vi.fn(),
}))
vi.mock('../../hooks/useTickerSentiment', () => ({
  useTickerSentiment: vi.fn(),
}))

import { MarketEventsZone } from './MarketDataZone'
import { useTickerPrice, useTickerFinancials, useTickerCatalysts } from '../../hooks/useTickerData'
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
      <MarketEventsZone ticker="NVDA" />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(useTickerPrice).mockReturnValue(settled({ history: null }) as never)
  vi.mocked(useTickerFinancials).mockReturnValue(settled({}) as never)
  vi.mocked(useTickerCatalysts).mockReturnValue(settled([]) as never)
  vi.mocked(useTickerSentiment).mockReturnValue(settled(SENTIMENT_OK) as never)
})

describe('MarketEventsZone — catalyst calendar loading state', () => {
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

describe('MarketEventsZone — retail sentiment honest states', () => {
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
})
