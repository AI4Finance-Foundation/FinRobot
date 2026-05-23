// Vitest coverage for chapter 09 (Technical & Advanced Analysis).
// The chapter now reads its 3 quant overlays from the persisted artifact
// payload rather than firing on-demand compute calls.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../../../hooks/useTickerData', () => ({
  useTickerPrice: vi.fn(() => ({ data: { current_price: 162.0, change_pct: 1.5 } })),
  useTickerFinancials: vi.fn(() => ({
    data: {
      market: { price_52w_high: 180, price_52w_low: 110, beta: 1.2 },
    },
  })),
}))

// Import after the mocks so the module picks up the mocked hooks.
import { ChapterTechnical } from './ChapterTechnical'
import type { TechnicalAnalysisShape } from './types'

function renderChapter(technical: TechnicalAnalysisShape | null) {
  return render(<ChapterTechnical ticker="AAPL" technical={technical} />)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ChapterTechnical', () => {
  it('renders cold state when the artifact carries no technical payload', () => {
    renderChapter(null)
    expect(screen.getByTestId('technical-cold-state')).toBeInTheDocument()
    expect(screen.queryByTestId('mc-histogram')).not.toBeInTheDocument()
    expect(screen.queryByTestId('band-timeline')).not.toBeInTheDocument()
  })

  it('renders Monte Carlo histogram with percentile stats from the artifact', () => {
    renderChapter({
      monte_carlo: {
        histogram_bins: [100, 120, 140, 160, 180, 200],
        histogram_counts: [50, 120, 230, 180, 90],
        percentiles: { '5': 110, '50': 150, '95': 195 },
        mean: 152.4,
        std: 24.1,
        current_price_percentile: 38,
        n_valid: 9876,
      },
    })
    expect(screen.getByTestId('mc-histogram')).toBeInTheDocument()
    expect(screen.getByText('Monte Carlo Distribution')).toBeInTheDocument()
    expect(screen.getByText('9,876')).toBeInTheDocument()
    expect(screen.getByText('$150.00')).toBeInTheDocument()
    expect(screen.getByText('38th')).toBeInTheDocument()
  })

  it('renders sniper levels with buy / stop / target and R/R ratio', () => {
    renderChapter({
      sniper: {
        ideal_buy: 162.5,
        secondary_buy: 154.0,
        stop_loss: 138.0,
        take_profit: 200.0,
        position_size_pct: 3.0,
        safety_margin: 0.15,
        support_level: 154.0,
        resistance_level: 178.0,
        risk_reward_ratio: 2.4,
      },
    })
    expect(screen.getByText('Support / Resistance Levels')).toBeInTheDocument()
    expect(screen.getByText('Ideal Buy')).toBeInTheDocument()
    expect(screen.getByText('$162.50')).toBeInTheDocument()
    expect(screen.getByText('Stop Loss')).toBeInTheDocument()
    expect(screen.getByText('$138.00')).toBeInTheDocument()
    expect(screen.getByText('Take Profit')).toBeInTheDocument()
    expect(screen.getByText('$200.00')).toBeInTheDocument()
    expect(screen.getByText('R / R Ratio')).toBeInTheDocument()
    expect(screen.getByText('2.40')).toBeInTheDocument()
  })

  it('renders historical EV/EBITDA bands with timeline and classification badge', () => {
    renderChapter({
      historical_bands: {
        metric: 'ev_ebitda',
        current: 22.1,
        median: 18.0,
        p25: 14.0,
        p75: 20.0,
        p90: 23.0,
        sample_count: 36,
        classification: 'expensive',
        timeline: [
          ['2023-01-01', 16.0],
          ['2023-07-01', 19.0],
          ['2024-01-01', 21.0],
          ['2024-07-01', 22.1],
        ],
        warnings: [],
      },
    })
    expect(screen.getByText('Historical EV/EBITDA Bands')).toBeInTheDocument()
    expect(screen.getByTestId('band-timeline')).toBeInTheDocument()
    const badge = screen.getByTestId('band-classification')
    expect(badge).toHaveTextContent(/expensive/i)
    expect(screen.getByText('22.1x')).toBeInTheDocument()
    expect(screen.getByText('18.0x')).toBeInTheDocument()
  })

  it('omits sub-sections for branches that are null and never shows the old placeholder text', () => {
    renderChapter({
      monte_carlo: {
        histogram_bins: [1, 2, 3],
        histogram_counts: [1, 1],
        percentiles: { '5': 1.1, '50': 2.0, '95': 2.9 },
        mean: 2,
        std: 0.4,
        current_price_percentile: 50,
        n_valid: 100,
      },
      sniper: null,
      historical_bands: null,
    })
    expect(screen.getByText('Monte Carlo Distribution')).toBeInTheDocument()
    expect(screen.queryByText('Support / Resistance Levels')).not.toBeInTheDocument()
    expect(screen.queryByText('Historical EV/EBITDA Bands')).not.toBeInTheDocument()
    // The legacy placeholder language must be gone.
    expect(screen.queryByText(/computed on-demand via/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/P4 — desktop augmentation/i)).not.toBeInTheDocument()
  })
})
