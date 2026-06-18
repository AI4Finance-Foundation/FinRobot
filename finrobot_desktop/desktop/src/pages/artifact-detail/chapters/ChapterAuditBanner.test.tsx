// Guards the numeric-audit gate's front-end surface: the banner renders ONLY when
// the artifact isn't publishable AND has something to show (a finding or a withhold
// note), lists every finding by field_key + evidence, and explains the withheld
// valuation. A publishable / absent audit — or a caveated status that an
// internal-only scrub (contract C7) left with no analyst row — must be
// zero-footprint (no banner) so clean reports are untouched.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterAuditBanner } from './ChapterAuditBanner'
import type { NumericAuditShape } from './types'

const CAVEATED_AUDIT: NumericAuditShape = {
  artifact_status: 'caveated',
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

  it('renders the banner + every finding (field_key + evidence) for caveated', () => {
    render(<ChapterAuditBanner audit={CAVEATED_AUDIT} />)
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
    render(<ChapterAuditBanner audit={CAVEATED_AUDIT} />)
    // zh or en copy — both mention the withheld point target (rating still stands).
    expect(screen.getByText(/已隐藏|withheld/i)).toBeInTheDocument()
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

  // ── Output-contract findings (ArtifactContract, step 1b) ───────────────────

  it('exposes the #report-audit-banner anchor so the cover can jump to it', () => {
    render(<ChapterAuditBanner audit={CAVEATED_AUDIT} />)
    expect(screen.getByTestId('report-audit-banner').id).toBe('report-audit-banner')
  })

  it('renders output-contract findings (clause id + evidence) alongside numeric ones', () => {
    render(
      <ChapterAuditBanner
        audit={CAVEATED_AUDIT}
        contractFindings={[
          {
            clause: 'C1',
            evidence:
              'headline target 2172.00 is 2.5x the entry price 864.00, outside the single-method corroboration band [0.5x, 2x]',
          },
        ]}
      />,
    )
    // Numeric findings (2) + contract findings (1) all render as rows.
    expect(screen.getAllByTestId('report-audit-finding')).toHaveLength(3)
    expect(screen.getByText('OUTPUT-CONTRACT/C1')).toBeInTheDocument()
    expect(screen.getByText(/single-method corroboration band/)).toBeInTheDocument()
  })

  it('renders for a contract withhold even when the numeric-audit block is absent', () => {
    // The contract can withhold on a clean snapshot (MU $2172): no numeric
    // findings, audit may even be null — the banner must still surface the reason.
    render(
      <ChapterAuditBanner
        audit={null}
        contractFindings={[
          {
            clause: 'C2',
            evidence: "malformed amount '$2172.062.06' (two decimal points) in narrative",
          },
        ]}
      />,
    )
    expect(screen.getByTestId('report-audit-banner')).toBeInTheDocument()
    expect(screen.getByText('OUTPUT-CONTRACT/C2')).toBeInTheDocument()
    expect(screen.getByText(/\$2172\.062\.06/)).toBeInTheDocument()
  })

  it('stays zero-footprint when publishable AND no contract findings', () => {
    const { container } = render(
      <ChapterAuditBanner
        audit={{ artifact_status: 'publishable', findings: [] }}
        contractFindings={[]}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('stays zero-footprint for a legacy review_only artifact with no findings', () => {
    // Pre-2026-06-15 artifacts carry the retired `review_only` status. It is not
    // in NumericAuditStatus, so the old `status === "caveated"` guard never matched
    // it and an EMPTY "Data Caveat" box rendered (TSLA 06-12 regression). The
    // content-gate hides it: no finding, no withhold → nothing to show.
    const legacy = {
      artifact_status: 'review_only',
      withhold_valuation: false,
      findings: [],
    } as unknown as NumericAuditShape
    const { container } = render(<ChapterAuditBanner audit={legacy} contractFindings={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('still renders a legacy review_only artifact that DOES carry findings', () => {
    const legacy = {
      artifact_status: 'review_only',
      withhold_valuation: false,
      findings: CAVEATED_AUDIT.findings,
    } as unknown as NumericAuditShape
    render(<ChapterAuditBanner audit={legacy} />)
    expect(screen.getByTestId('report-audit-banner')).toBeInTheDocument()
    expect(screen.getAllByTestId('report-audit-finding')).toHaveLength(2)
  })

  it('gives unpublishable a plain-language reason instead of an empty red box', () => {
    render(
      <ChapterAuditBanner
        audit={{ artifact_status: 'unpublishable', withhold_valuation: false, findings: [] }}
      />,
    )
    expect(screen.getByTestId('report-audit-banner')).toBeInTheDocument()
    // zh or en copy — both explain core data could not be resolved.
    expect(screen.getByText(/未能从任何数据源解析|could not be resolved/i)).toBeInTheDocument()
  })

  it('stays zero-footprint when an internal scrub left caveated status but no analyst row', () => {
    // C7's no-resurrection scrub flips the status to `caveated` without producing any
    // analyst-facing finding (its evidence is the non-surfacing /internal tag) and with
    // withhold_valuation false. An empty "Data Caveat" banner there is noise — the
    // legitimately-withheld target is already explained on the cover. (MU regression.)
    const { container } = render(
      <ChapterAuditBanner
        audit={{ artifact_status: 'caveated', withhold_valuation: false, findings: [] }}
        contractFindings={[]}
      />,
    )
    expect(container.firstChild).toBeNull()
  })
})
