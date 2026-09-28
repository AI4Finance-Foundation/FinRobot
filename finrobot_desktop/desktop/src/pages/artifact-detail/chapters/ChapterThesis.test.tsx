// Thesis (chapter 01) — the full ARGUMENT. The rating / target / conviction /
// target band render ONCE on the cover (ChapterCover); this chapter carries NO
// rating-restatement header. It now adds, below the narrative + takeaways: the
// bull/bear case (catalysts vs risks), a valuation-bridge SUMMARY (per-method
// mids + anchor, jump to the full football field), and the market-implied
// reverse-DCF (surfaced here when a target shipped — the cover shows it only when
// the target is withheld, so exactly one of the two renders it).

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterThesis } from './ChapterThesis'
import type { DcfShape, ThesisShape, ValuationSynthesisShape } from './types'

function thesis(partial: Partial<ThesisShape>): ThesisShape {
  return partial as ThesisShape
}

// Two methods, dcf as the anchor — mirrors a real valuation_synthesis slice. mid
// 130 vs current 110 ⇒ +18.2% upside; the reverse-DCF ceiling reads the dcf mid.
const METHODS = [
  { name: 'dcf', low: 110, mid: 130, high: 150, confidence: 0.6, source: 'dcf' },
  { name: 'comps_pe', low: 100, mid: 120, high: 140, confidence: 0.4, source: 'forward' },
]
function vs(over: Partial<ValuationSynthesisShape>): ValuationSynthesisShape {
  return {
    methods: METHODS,
    current_price: 110,
    anchor_method: 'dcf',
    ...over,
  } as ValuationSynthesisShape
}
function dcfShape(over: Partial<DcfShape>): DcfShape {
  return over as DcfShape
}
const REACHABLE = {
  horizon_years: 10,
  implied_growth: 0.2,
  growth_unreachable: false,
} as NonNullable<DcfShape['market_implied']>

describe('ChapterThesis — argument only, no cover-duplicating header', () => {
  it('renders the narrative and key takeaways', () => {
    render(
      <ChapterThesis
        thesis={thesis({
          recommendation: 'BUY',
          price_target: 130,
          narrative: 'Memory cycle inflecting; ASPs bottoming into 2H.',
          key_takeaways: ['HBM share gains', 'Capex discipline'],
        })}
        valuationSynthesis={null}
        dcf={null}
        quoteCurrency="USD"
      />,
    )
    expect(screen.getByText(/Memory cycle inflecting/)).toBeInTheDocument()
    expect(screen.getByText('HBM share gains')).toBeInTheDocument()
    expect(screen.getByText('Capex discipline')).toBeInTheDocument()
  })

  it('does NOT restate the cover rating surface (no verdict badge, no target gauge, no provenance line)', () => {
    render(
      <ChapterThesis
        thesis={thesis({
          recommendation: 'SELL',
          price_target: 214,
          price_target_basis:
            'method-weighted blend: DCF $189 (wt 0.85), Comps (P/E) $193 (wt 0.80), EV/EBITDA $265 (wt 0.72)',
          narrative: 'Elevated valuation offers limited upside.',
        })}
        valuationSynthesis={null}
        dcf={null}
        quoteCurrency="USD"
      />,
    )
    // The cover owns the rating/target/conviction/provenance — none of it here.
    expect(screen.queryByTestId('thesis-verdict')).toBeNull()
    expect(screen.queryByTestId('confidence-chip')).toBeNull()
    expect(screen.queryByTestId('target-range')).toBeNull()
    // The verbose method-blend provenance line (now on the cover) must not appear here.
    expect(screen.queryByText(/method-weighted blend/)).toBeNull()
    // The argument itself still renders.
    expect(screen.getByText(/Elevated valuation offers limited upside/)).toBeInTheDocument()
  })

  it('renders the empty state when there is no thesis', () => {
    render(<ChapterThesis thesis={null} valuationSynthesis={null} dcf={null} quoteCurrency="USD" />)
    expect(screen.queryByTestId('thesis-verdict')).toBeNull()
    expect(screen.queryByTestId('target-range')).toBeNull()
  })
})

describe('ChapterThesis — full argument surface', () => {
  it('renders the bull/bear case from thesis catalysts and risks', () => {
    render(
      <ChapterThesis
        thesis={thesis({
          catalysts: ['HBM ramp into AI demand'],
          risks: ['China export controls'],
        })}
        valuationSynthesis={null}
        dcf={null}
        quoteCurrency="USD"
      />,
    )
    expect(screen.getByText('HBM ramp into AI demand')).toBeInTheDocument()
    expect(screen.getByText('China export controls')).toBeInTheDocument()
  })

  it('renders the valuation-bridge summary with method labels (same source as the football field), the anchor, and a jump to the full bridge — never a per-method weight', () => {
    render(
      <ChapterThesis
        thesis={thesis({ recommendation: 'BUY', price_target: 130 })}
        valuationSynthesis={vs({})}
        dcf={null}
        quoteCurrency="USD"
      />,
    )
    // Labels come from the shared METHOD_LABEL (football-field source), not a
    // bespoke map: 'dcf' → 'DCF', 'comps_pe' → 'Comps (P/E)'.
    expect(screen.getByText('DCF')).toBeInTheDocument()
    expect(screen.getByText('Comps (P/E)')).toBeInTheDocument()
    // The anchor method is flagged.
    expect(screen.getByText('anchor')).toBeInTheDocument()
    // A jump to the full football field in the Valuation chapter.
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '#valuation')
    // No per-method weight is invented (the schema carries none) — guard against a
    // "%" weight column sneaking in beside the methods.
    expect(screen.queryByText(/weight/i)).toBeNull()
  })

  it('aligns the comps_pe label caliber with the football field (core P/E shows as "Comps (core P/E)", not a bare "Comps (P/E)")', () => {
    // Same method, same label in both chapters — a bare "Comps (P/E)" in the
    // summary while the full bridge says "Comps (core P/E)" reads as two methods.
    render(
      <ChapterThesis
        thesis={thesis({ recommendation: 'BUY', price_target: 130 })}
        valuationSynthesis={vs({
          methods: [
            {
              name: 'comps_pe',
              low: 100,
              mid: 120,
              high: 140,
              confidence: 0.5,
              source: 'peer_median_core_pe × core_eps',
            },
          ],
        })}
        dcf={null}
        quoteCurrency="USD"
      />,
    )
    expect(screen.getByText('Comps (core P/E)')).toBeInTheDocument()
  })

  it('surfaces the market-implied reverse-DCF when a target shipped (the cover suppressed it to keep one price axis)', () => {
    render(
      <ChapterThesis
        thesis={thesis({ recommendation: 'BUY', price_target: 130 })}
        valuationSynthesis={vs({})}
        dcf={dcfShape({ market_implied: REACHABLE })}
        quoteCurrency="USD"
      />,
    )
    expect(screen.getByTestId('reverse-dcf-headline')).toBeInTheDocument()
  })

  it('does NOT render the market-implied panel when the target is withheld (the cover owns it then — never both)', () => {
    // Withheld = recommendation present + null price_target (the cover's own gate).
    render(
      <ChapterThesis
        thesis={thesis({ recommendation: 'HOLD' })}
        valuationSynthesis={vs({})}
        dcf={dcfShape({ market_implied: REACHABLE })}
        quoteCurrency="USD"
      />,
    )
    expect(screen.queryByTestId('reverse-dcf-headline')).toBeNull()
  })

  it('renders the momentum-divergence hedge note when present (BACKLOG A2/P1-1)', () => {
    render(
      <ChapterThesis
        thesis={thesis({
          recommendation: 'BUY',
          price_target: 130,
          narrative: 'The setup is compelling despite the pullback.',
          momentum_divergence_note:
            'The market is pricing in a demand air-pocket; we see a temporary inventory correction.',
        })}
        valuationSynthesis={null}
        dcf={null}
        quoteCurrency="USD"
      />,
    )
    expect(screen.getByText(/pricing in a demand air-pocket/)).toBeInTheDocument()
  })

  it('does NOT render a momentum-divergence section when the note is null (ordinary, non-divergent call)', () => {
    render(
      <ChapterThesis
        thesis={thesis({
          recommendation: 'HOLD',
          narrative: 'Fairly valued at current levels.',
          momentum_divergence_note: null,
        })}
        valuationSynthesis={null}
        dcf={null}
        quoteCurrency="USD"
      />,
    )
    expect(screen.queryByText(/pricing in/i)).toBeNull()
  })

  it('degrades gracefully — no bridge, no market-implied, no crash — when synthesis and dcf are absent', () => {
    render(
      <ChapterThesis
        thesis={thesis({ narrative: 'Just prose, no structured valuation.' })}
        valuationSynthesis={null}
        dcf={null}
        quoteCurrency="USD"
      />,
    )
    expect(screen.getByText('Just prose, no structured valuation.')).toBeInTheDocument()
    expect(screen.queryByTestId('reverse-dcf-headline')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
  })
})
