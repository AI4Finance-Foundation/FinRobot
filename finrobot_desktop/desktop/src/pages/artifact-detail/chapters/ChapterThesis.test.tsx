// Thesis (chapter 01) — the rating restatement header. It mirrors the cover's
// verdict surface: a verdict-TONED badge (涨绿跌红, never flat purple), a
// confidence-tier chip on a non-hue channel, and a <TargetRange> that replaces
// the old bare `Target $X` false-precise number with a confidence-scaled band +
// drill-down. When the point target is honestly withheld the band still frames
// where a defensible target sits — the point tick is dropped, never fabricated.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterThesis } from './ChapterThesis'
import type { ThesisShape } from './types'

function thesis(partial: Partial<ThesisShape>): ThesisShape {
  return partial as ThesisShape
}

describe('ChapterThesis — rating restatement header', () => {
  it('renders a verdict-toned badge (not flat purple) + a confidence chip + a non-withheld TargetRange', () => {
    render(
      <ChapterThesis
        thesis={thesis({ recommendation: 'BUY', price_target: 130 })}
        confidence="high"
        targetLow={120}
        targetHigh={140}
        currentPrice={110}
        anchorMethod="dcf"
      />,
    )
    const badge = screen.getByTestId('thesis-verdict')
    // Directional verdict drives the badge — and its tone (not the old
    // --secondary flat purple). The data hook lets the tone be asserted.
    expect(badge).toHaveAttribute('data-verdict', 'BUY')
    expect(badge).toHaveAttribute('data-confidence', 'high')
    expect(badge.style.background).toBe('var(--success-soft)')
    expect(badge.style.color).toBe('var(--success)')

    // Confidence tier on its own non-hue chip.
    const chip = screen.getByTestId('confidence-chip')
    expect(chip).toHaveAttribute('data-confidence', 'high')

    // The bare `Target $130.00` span is gone — the number is a TargetRange now,
    // rendered with a point tick (not withheld).
    const range = screen.getByTestId('target-range')
    expect(range).toHaveAttribute('data-withheld', 'false')
  })

  it('tones the badge to the directional call (HOLD → warning, SELL → danger)', () => {
    const { rerender } = render(
      <ChapterThesis thesis={thesis({ recommendation: 'HOLD', price_target: 100 })} />,
    )
    let badge = screen.getByTestId('thesis-verdict')
    expect(badge.style.color).toBe('var(--warning)')

    rerender(<ChapterThesis thesis={thesis({ recommendation: 'SELL', price_target: 80 })} />)
    badge = screen.getByTestId('thesis-verdict')
    expect(badge.style.color).toBe('var(--danger)')
  })

  it('renders the withheld TargetRange (no point tick) when the point is null but a band ships — never fabricating a point', () => {
    render(
      <ChapterThesis
        thesis={thesis({ recommendation: 'HOLD' })}
        // Synthesis withholds the precise point but still ships a defensible band.
        targetLow={90}
        targetHigh={140}
        currentPrice={110}
      />,
    )
    // The directional verdict still stands.
    const badge = screen.getByTestId('thesis-verdict')
    expect(badge).toHaveAttribute('data-verdict', 'HOLD')
    expect(badge).not.toHaveTextContent('REVIEW')
    // TargetRange renders in withheld mode — the point tick is dropped.
    expect(screen.getByTestId('target-range')).toHaveAttribute('data-withheld', 'true')
  })

  it('falls back to plain "target withheld" text when the point is null AND there is no band to draw', () => {
    render(<ChapterThesis thesis={thesis({ recommendation: 'HOLD' })} />)
    // No point + no low/high → TargetRange has nothing to draw and returns null;
    // the header must not silently drop the withheld state.
    expect(screen.queryByTestId('target-range')).toBeNull()
    const badge = screen.getByTestId('thesis-verdict')
    expect(badge).toHaveAttribute('data-verdict', 'HOLD')
    expect(screen.getByText(/withheld/i)).toBeInTheDocument()
  })

  it('keeps the price_target_basis line, the narrative and key takeaways intact', () => {
    render(
      <ChapterThesis
        thesis={thesis({
          recommendation: 'BUY',
          price_target: 130,
          price_target_basis: 'blended DCF + comps',
          narrative: 'Memory cycle inflecting; ASPs bottoming into 2H.',
          key_takeaways: ['HBM share gains', 'Capex discipline'],
        })}
        targetLow={120}
        targetHigh={140}
      />,
    )
    expect(screen.getByText(/blended DCF \+ comps/)).toBeInTheDocument()
    expect(screen.getByText(/Memory cycle inflecting/)).toBeInTheDocument()
    expect(screen.getByText('HBM share gains')).toBeInTheDocument()
    expect(screen.getByText('Capex discipline')).toBeInTheDocument()
  })

  it('legacy artifacts with null confidence/band degrade gracefully (chip defaults to low, band derives from the point)', () => {
    render(<ChapterThesis thesis={thesis({ recommendation: 'BUY', price_target: 130 })} />)
    // No confidence prop → normalizeConfidence floors to 'low' (no fabricated conviction).
    const chip = screen.getByTestId('confidence-chip')
    expect(chip).toHaveAttribute('data-confidence', 'low')
    // No explicit band → TargetRange derives one from the point; still a point tick.
    expect(screen.getByTestId('target-range')).toHaveAttribute('data-withheld', 'false')
  })

  it('renders the empty state when there is no thesis', () => {
    render(<ChapterThesis thesis={null} />)
    expect(screen.queryByTestId('thesis-verdict')).toBeNull()
    expect(screen.queryByTestId('target-range')).toBeNull()
  })
})
