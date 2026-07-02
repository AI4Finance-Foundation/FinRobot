// Vitest coverage for chapter 10 (Technical Analysis).
// The chapter reads its 3 quant overlays AND its price/52w/beta from the frozen
// artifact snapshot (props), not live hooks — a report is a point-in-time
// artifact, so nothing here refetches a live quote.

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterTechnical } from './ChapterTechnical'
import type { TechnicalAnalysisShape } from './types'

function renderChapter(technical: TechnicalAnalysisShape | null, financialSector = false) {
  return render(
    <ChapterTechnical
      technical={technical}
      financialSector={financialSector}
      quoteCurrency="USD"
      snapshotPrice={162.0}
      snapshotBeta={1.2}
      snapshot52wHigh={180}
      snapshot52wLow={110}
    />,
  )
}

describe('ChapterTechnical', () => {
  it('renders the frozen snapshot price + raw 5Y beta from props (no live refetch)', () => {
    renderChapter(null)
    expect(screen.getByText('$162.00')).toBeInTheDocument()
    expect(screen.getByText('1.20')).toBeInTheDocument()
  })

  it('renders cold state when the artifact carries no technical payload', () => {
    renderChapter(null)
    expect(screen.getByTestId('technical-cold-state')).toBeInTheDocument()
    expect(screen.queryByTestId('mc-histogram')).not.toBeInTheDocument()
    expect(screen.queryByTestId('band-timeline')).not.toBeInTheDocument()
  })

  it('frames the empty overlays as a category error (not "re-run") for a balance-sheet financial', () => {
    // A bank / insurer report has no Monte Carlo / EV-EBITDA band by design — the
    // backend withholds the DCF-derived overlays at the source. The empty state must
    // read as "not applicable to a balance-sheet financial", never "re-run".
    renderChapter(null, true)
    const note = screen.getByTestId('technical-cold-state')
    expect(note).toHaveTextContent(/balance-sheet financial/i)
    expect(note).toHaveTextContent(/P\/B/)
    expect(note).not.toHaveTextContent(/re-run/i)
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

  it('staggers the Current/P95 marker labels onto different rows when the current price sits near a percentile (they would otherwise render on top of each other)', () => {
    // current (snapshotPrice=193) sits 2 price-units from P95 (195) — a real
    // symptom for a name trading near its Monte Carlo distribution's tail
    // (e.g. AAPL at the 97.6th percentile). Both markers land within a few
    // pixels of each other on the x-axis.
    render(
      <ChapterTechnical
        technical={{
          monte_carlo: {
            histogram_bins: [100, 120, 140, 160, 180, 200],
            histogram_counts: [50, 120, 230, 180, 90],
            percentiles: { '5': 110, '50': 150, '95': 195 },
            mean: 152.4,
            std: 24.1,
            current_price_percentile: 97.6,
            n_valid: 9876,
          },
        }}
        financialSector={false}
        quoteCurrency="USD"
        snapshotPrice={193}
        snapshotBeta={1.2}
        snapshot52wHigh={180}
        snapshot52wLow={110}
      />,
    )
    const chart = screen.getByTestId('mc-histogram')
    const p95Label = Array.from(chart.querySelectorAll('text')).find(
      (el) => el.textContent === 'P95',
    )
    const currentLabel = Array.from(chart.querySelectorAll('text')).find(
      (el) => el.textContent === 'Current',
    )
    expect(p95Label).toBeDefined()
    expect(currentLabel).toBeDefined()
    // Different label rows ⇒ different y — the old code placed every label
    // at the same y regardless of x-proximity, so this failed pre-fix.
    expect(p95Label?.getAttribute('y')).not.toBe(currentLabel?.getAttribute('y'))
  })

  it('splits objective S/R levels from a separate Tactical Trade Reference block (entries / stop / target / R-R)', () => {
    renderChapter({
      sniper: {
        ideal_buy: 162.5,
        secondary_buy: 150.0,
        stop_loss: 138.0,
        take_profit: 200.0,
        position_size_pct: 3.0,
        safety_margin: 0.15,
        support_level: 154.0,
        resistance_level: 178.0,
        risk_reward_ratio: 2.4,
      },
    })
    // Objective technical-level module (the analytical content).
    expect(screen.getByText('Support / Resistance Levels')).toBeInTheDocument()
    expect(screen.getByText('Support (20d)')).toBeInTheDocument()
    expect(screen.getByText('$154.00')).toBeInTheDocument()
    // The trade-desk fields live in a distinct, clearly-labelled adjunct block
    // with an IB-framing caption — not embedded as the section's headline.
    expect(screen.getByText('Tactical Trade Reference')).toBeInTheDocument()
    expect(screen.getByTestId('sniper-tactical-note')).toBeInTheDocument()
    expect(screen.getByText('Ideal Buy')).toBeInTheDocument()
    expect(screen.getByText('$162.50')).toBeInTheDocument()
    expect(screen.getByText('Stop Loss')).toBeInTheDocument()
    expect(screen.getByText('$138.00')).toBeInTheDocument()
    expect(screen.getByText('Take Profit')).toBeInTheDocument()
    expect(screen.getByText('$200.00')).toBeInTheDocument()
    expect(screen.getByText('R / R Ratio')).toBeInTheDocument()
    expect(screen.getByText('2.40')).toBeInTheDocument()
  })

  it('NEUTRAL sniper shows the withheld note + support/resistance, no directional trade', () => {
    renderChapter({
      sniper: {
        ideal_buy: null,
        secondary_buy: null,
        stop_loss: null,
        take_profit: null,
        position_size_pct: null,
        safety_margin: null,
        support_level: 292.68,
        resistance_level: 315.2,
        risk_reward_ratio: null,
        direction: 'NEUTRAL',
        sell_mode: false,
      },
    })
    // Explicit honest note instead of a silent drop.
    expect(screen.getByTestId('sniper-neutral-note')).toBeInTheDocument()
    // Support / resistance (pure price facts) still render.
    expect(screen.getByText('$292.68')).toBeInTheDocument()
    expect(screen.getByText('$315.20')).toBeInTheDocument()
    // No directional trade may leak: no entry / stop / target / R/R cells, and
    // the Tactical Trade Reference adjunct block must not render at all.
    expect(screen.queryByText('Tactical Trade Reference')).not.toBeInTheDocument()
    expect(screen.queryByTestId('sniper-tactical-note')).not.toBeInTheDocument()
    expect(screen.queryByText('Ideal Buy')).not.toBeInTheDocument()
    expect(screen.queryByText('Take Profit')).not.toBeInTheDocument()
    expect(screen.queryByText('Stop Loss')).not.toBeInTheDocument()
    expect(screen.queryByText('R / R Ratio')).not.toBeInTheDocument()
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
