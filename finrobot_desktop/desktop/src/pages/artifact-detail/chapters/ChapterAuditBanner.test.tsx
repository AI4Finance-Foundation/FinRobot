// Guards the numeric-audit gate's front-end surface: the banner renders ONLY
// when the artifact isn't publishable, lists every finding by field_key +
// evidence, and explains the withheld valuation. A publishable / absent audit
// must be zero-footprint (no banner) so clean reports are untouched.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterAuditBanner } from './ChapterAuditBanner'
import type { NumericAuditShape } from './types'

const REVIEW_AUDIT: NumericAuditShape = {
  artifact_status: 'review_only',
  withhold_valuation: true,
  findings: [
    {
      field_key: 'ev_ebitda',
      check: 'financial_sector_ev_meaningless',
      severity: 'blocked_field',
      evidence: 'JPM industry=banks: ev_ebitda=8.1 is a category error. Value on P/B, ROTCE.',
    },
    {
      field_key: 'pe_ratio',
      check: 'non_positive_earnings_pe_nm',
      severity: 'review',
      evidence: 'JPM net_income=-1.2e9 ≤ 0: P/E is not meaningful by economics.',
    },
  ],
}

describe('ChapterAuditBanner', () => {
  it('renders nothing when the artifact is publishable', () => {
    const { container } = render(
      <ChapterAuditBanner audit={{ artifact_status: 'publishable', findings: [] }} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when there is no audit block (legacy artifacts)', () => {
    const { container } = render(<ChapterAuditBanner audit={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders the banner + every finding (field_key + evidence) for review_only', () => {
    render(<ChapterAuditBanner audit={REVIEW_AUDIT} />)
    expect(screen.getByTestId('report-audit-banner')).toBeInTheDocument()
    // One row per finding.
    expect(screen.getAllByTestId('report-audit-finding')).toHaveLength(2)
    // field_key shown verbatim (it references the static caliber registry).
    expect(screen.getByText('ev_ebitda')).toBeInTheDocument()
    expect(screen.getByText('pe_ratio')).toBeInTheDocument()
    // The evidence string (carrying the actual numbers) is the banner body.
    expect(screen.getByText(/category error/)).toBeInTheDocument()
    expect(screen.getByText(/not meaningful by economics/)).toBeInTheDocument()
  })

  it('explains the withheld valuation when withhold_valuation is set', () => {
    render(<ChapterAuditBanner audit={REVIEW_AUDIT} />)
    // zh or en copy — both mention the withheld rating / target.
    expect(screen.getByText(/暂缓发布|withheld/i)).toBeInTheDocument()
  })

  it('uses the danger accent for unpublishable status', () => {
    render(
      <ChapterAuditBanner
        audit={{ artifact_status: 'unpublishable', withhold_valuation: false, findings: [] }}
      />,
    )
    const banner = screen.getByTestId('report-audit-banner')
    // Left accent border resolves to the danger token in the unpublishable path.
    expect(banner.style.borderLeft).toContain('var(--danger)')
  })
})
