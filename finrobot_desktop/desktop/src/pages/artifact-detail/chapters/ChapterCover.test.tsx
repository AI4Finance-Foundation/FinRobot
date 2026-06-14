// Cover (chapter 00) — the withheld-target self-explain surface (ArtifactContract
// step 1b). When the point target is withheld, the cover must state WHY at a
// glance and offer a jump to the per-finding audit banner — not just a bare
// "N/A". The directional verdict still ships; only the precise number is held.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterCover } from './ChapterCover'
import type { ThesisShape } from './types'

const BASE = {
  ticker: 'MU',
  createdAt: '2026-06-08T00:00:00Z',
  artifactId: 'art_MU_equity_research',
  computeVersion: 'equity_research_v1',
  reportType: 'equity_research',
  versionNumber: 1,
  totalVersions: 1,
}

function thesis(partial: Partial<ThesisShape>): ThesisShape {
  return partial as ThesisShape
}

describe('ChapterCover — withheld-target self-explanation', () => {
  it('renders the withheld reason + a jump to the audit banner when the point target is null (verdict still directional)', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'HOLD' })}
        withheldReason="headline target 2172.00 is 2.5x the entry price 864.00, outside the single-method corroboration band [0.5x, 2x]"
        // The synthesis can still ship a defensible band even when the point is
        // withheld — the range renders without a point tick.
        targetLow={900}
        targetHigh={1400}
        currentPrice={864}
      />,
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '#report-audit-banner')
    // The reason is visible at a glance on the cover (not buried in the banner).
    expect(screen.getByText(/2\.5x the entry price/)).toBeInTheDocument()
    // The directional badge keeps its hue — never "REVIEW".
    const badge = screen.getByTestId('cover-verdict')
    expect(badge).toHaveAttribute('data-verdict', 'HOLD')
    expect(badge).not.toHaveTextContent('REVIEW')
    // The TargetRange renders in withheld mode (no point tick).
    expect(screen.getByTestId('target-range')).toHaveAttribute('data-withheld', 'true')
  })

  it('renders a confidence chip + a non-withheld TargetRange for a normal directional call', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'BUY', price_target: 130 })}
        withheldReason={null}
        confidence="high"
        targetLow={120}
        targetHigh={140}
        currentPrice={110}
        anchorMethod="dcf"
      />,
    )
    expect(screen.queryByRole('link')).toBeNull()
    const chip = screen.getByTestId('confidence-chip')
    expect(chip).toHaveAttribute('data-confidence', 'high')
    const range = screen.getByTestId('target-range')
    expect(range).toHaveAttribute('data-withheld', 'false')
  })

  it('maps a legacy REVIEW recommendation to a neutral WITHHELD badge, never the word REVIEW', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'REVIEW' })}
        withheldReason={null}
      />,
    )
    // No contract reason → no link, but the badge still renders neutrally.
    expect(screen.queryByRole('link')).toBeNull()
    const badge = screen.getByTestId('cover-verdict')
    expect(badge).toHaveAttribute('data-verdict', 'REVIEW')
    expect(badge).toHaveTextContent('WITHHELD')
    expect(badge).not.toHaveTextContent('REVIEW')
  })
})
