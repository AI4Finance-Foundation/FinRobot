// Thesis (chapter 01) — the ARGUMENT only. The rating / target / conviction /
// method-blend provenance render ONCE on the cover (ChapterCover); repeating that
// hero block here was a same-screen duplicate, so the section now leads straight
// with the narrative + key takeaways and carries NO rating-restatement header.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterThesis } from './ChapterThesis'
import type { ThesisShape } from './types'

function thesis(partial: Partial<ThesisShape>): ThesisShape {
  return partial as ThesisShape
}

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
          price_target_basis: 'method-weighted blend: dcf=$189, comps_pe=$193, ev_ebitda=$265',
          narrative: 'Elevated valuation offers limited upside.',
        })}
      />,
    )
    // The cover owns the rating/target/conviction/provenance — none of it here.
    expect(screen.queryByTestId('thesis-verdict')).toBeNull()
    expect(screen.queryByTestId('confidence-chip')).toBeNull()
    expect(screen.queryByTestId('target-range')).toBeNull()
    // The verbose method-blend provenance line must not appear a second time.
    expect(screen.queryByText(/method-weighted blend/)).toBeNull()
    // The argument itself still renders.
    expect(screen.getByText(/Elevated valuation offers limited upside/)).toBeInTheDocument()
  })

  it('renders the empty state when there is no thesis', () => {
    render(<ChapterThesis thesis={null} />)
    expect(screen.queryByTestId('thesis-verdict')).toBeNull()
    expect(screen.queryByTestId('target-range')).toBeNull()
  })
})
