// Cover (chapter 00) — the REVIEW self-explain surface (ArtifactContract step
// 1b). When the output contract withholds, the cover must state WHY at a glance
// and offer a jump to the per-finding audit banner — not just a bare "N/A".

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

describe('ChapterCover — REVIEW self-explanation', () => {
  it('renders the withheld reason + a jump to the audit banner when REVIEW', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'REVIEW' })}
        withheldReason="headline target 2172.00 is 2.5x the entry price 864.00, outside the single-method corroboration band [0.5x, 2x]"
      />,
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '#report-audit-banner')
    // The reason is visible at a glance on the cover (not buried in the banner).
    expect(screen.getByText(/2\.5x the entry price/)).toBeInTheDocument()
  })

  it('shows no reason line / anchor for a normal directional call', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'BUY', price_target: 130 })}
        withheldReason={null}
      />,
    )
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('shows no reason line when REVIEW but the withhold came from upstream (no contract reason)', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'REVIEW' })}
        withheldReason={null}
      />,
    )
    expect(screen.queryByRole('link')).toBeNull()
  })
})
