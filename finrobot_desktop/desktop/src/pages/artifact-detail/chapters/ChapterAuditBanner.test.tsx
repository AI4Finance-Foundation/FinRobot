// Guards the numeric-audit gate's front-end surface. The banner separates TWO kinds
// of "the number isn't clean":
//   • DEFECT / data-quality (cross-currency, contract withhold) → prominent warning
//     rows: humanised field LABEL (not the raw snake_case key) + the evidence string.
//   • STRUCTURAL / expected-by-economics (EV is a category error for a bank; P/E NM
//     for a loss-maker) → a calm, demoted "Valuation Notes" line, grouped per rule,
//     with NO raw value dumped. When a report has ONLY these, the whole banner drops
//     the warning treatment (role=note, no glow) — a routine sector fact must not
//     read like broken software (the JPM regression).
// A publishable / absent audit — or a caveated status an internal-only scrub left
// with no analyst row — must be zero-footprint.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterAuditBanner } from './ChapterAuditBanner'
import type { NumericAuditShape } from './types'

// The JPM case: a bank's EV/EV-EBITDA flagged as a category error. Expected
// structural fact (review severity), NOT a withhold.
const STRUCTURAL_AUDIT: NumericAuditShape = {
  artifact_status: 'caveated',
  withhold_valuation: false,
  findings: [
    {
      field_key: 'enterprise_value',
      check: 'financial_sector_ev_meaningless',
      severity: 'review',
      evidence:
        "JPM industry='Banks - Diversified': … enterprise_value=284630945210.52 is a category error. Value on P/B, P/TBV, ROTCE, DDM.",
    },
    {
      field_key: 'ev_ebitda',
      check: 'financial_sector_ev_meaningless',
      severity: 'review',
      evidence:
        'JPM … ev_ebitda=3.395699707835984 is a category error. Value on P/B, P/TBV, ROTCE, DDM.',
    },
  ],
}

// A genuine data DEFECT: mixed-currency EV. blocked_field → withholds the target.
const DEFECT_AUDIT: NumericAuditShape = {
  artifact_status: 'caveated',
  withhold_valuation: true,
  findings: [
    {
      field_key: 'enterprise_value',
      check: 'cross_currency_ratio',
      severity: 'blocked_field',
      evidence:
        'TSM EV mixes a USD market cap with TWD-denominated debt — the bridge is unit-inconsistent.',
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

  // ── Structural notes (expected-by-economics) — demoted, humanised, no raw value ──

  it('renders a bank EV note as a calm, grouped, humanised note — not an alarm', () => {
    render(<ChapterAuditBanner audit={STRUCTURAL_AUDIT} />)
    const banner = screen.getByTestId('report-audit-banner')
    expect(banner).toBeInTheDocument()
    // Calm, not alarm: role=note (a warning would be role=alert).
    expect(banner.getAttribute('role')).toBe('note')
    // The two EV findings collapse into ONE note (grouped by check), never two rows.
    expect(screen.getAllByTestId('report-audit-note')).toHaveLength(1)
    // No prominent DEFECT rows.
    expect(screen.queryAllByTestId('report-audit-finding')).toHaveLength(0)
  })

  it('humanises the field labels and never leaks the raw key or raw float', () => {
    render(<ChapterAuditBanner audit={STRUCTURAL_AUDIT} />)
    // Humanised metric names (EV/EBITDA stays English per the i18n exemption list).
    expect(screen.getByText(/Enterprise Value/)).toBeInTheDocument()
    expect(screen.getByText(/EV\/EBITDA/)).toBeInTheDocument()
    // The raw snake_case key and the full-precision floats must NOT reach the user.
    expect(screen.queryByText('enterprise_value')).toBeNull()
    expect(screen.queryByText(/284630945210/)).toBeNull()
    expect(screen.queryByText(/3\.395699707835984/)).toBeNull()
    // The raw audit evidence string is not dumped for a structural note.
    expect(screen.queryByText(/category error/)).toBeNull()
  })

  it('renders a loss-maker P/E note for non_positive_earnings_pe_nm', () => {
    render(
      <ChapterAuditBanner
        audit={{
          artifact_status: 'caveated',
          withhold_valuation: false,
          findings: [
            {
              field_key: 'pe_ratio',
              check: 'non_positive_earnings_pe_nm',
              severity: 'review',
              evidence: 'RIVN net_income=-1.2e9 ≤ 0: P/E is not meaningful by economics.',
            },
          ],
        }}
      />,
    )
    expect(screen.getAllByTestId('report-audit-note')).toHaveLength(1)
    expect(screen.getByText(/P\/E is not meaningful/i)).toBeInTheDocument()
    // raw evidence not dumped
    expect(screen.queryByText(/net_income/)).toBeNull()
  })

  // ── Defect rows (genuine data-quality) — prominent, humanised label + evidence ──

  it('renders a genuine defect as a prominent warning row with a humanised label', () => {
    render(<ChapterAuditBanner audit={DEFECT_AUDIT} />)
    const banner = screen.getByTestId('report-audit-banner')
    expect(banner.getAttribute('role')).toBe('alert')
    expect(screen.getAllByTestId('report-audit-finding')).toHaveLength(1)
    // Humanised label, NOT the raw key.
    expect(screen.getByText('Enterprise Value')).toBeInTheDocument()
    expect(screen.queryByText('enterprise_value')).toBeNull()
    // The evidence string (the diagnostic detail) IS shown for a real defect.
    expect(screen.getByText(/unit-inconsistent/)).toBeInTheDocument()
  })

  it('explains the withheld valuation when withhold_valuation is set', () => {
    render(<ChapterAuditBanner audit={DEFECT_AUDIT} />)
    // en or zh copy — both mention the withheld point target (rating still stands).
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

  it('exposes the #report-audit-banner anchor so the cover can jump to it', () => {
    render(<ChapterAuditBanner audit={STRUCTURAL_AUDIT} />)
    expect(screen.getByTestId('report-audit-banner').id).toBe('report-audit-banner')
  })

  // ── Output-contract findings (ArtifactContract, step 1b) ───────────────────

  it('renders output-contract findings (clause id + evidence) as defect rows', () => {
    render(
      <ChapterAuditBanner
        audit={STRUCTURAL_AUDIT}
        contractFindings={[
          {
            clause: 'C1',
            evidence:
              'headline target 2172.00 is 2.5x the entry price 864.00, outside the single-method corroboration band [0.5x, 2x]',
          },
        ]}
      />,
    )
    // The contract finding is a DEFECT row; the two structural EV findings are ONE note.
    expect(screen.getAllByTestId('report-audit-finding')).toHaveLength(1)
    expect(screen.getAllByTestId('report-audit-note')).toHaveLength(1)
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
      findings: STRUCTURAL_AUDIT.findings,
    } as unknown as NumericAuditShape
    render(<ChapterAuditBanner audit={legacy} />)
    expect(screen.getByTestId('report-audit-banner')).toBeInTheDocument()
    // Structural findings → one grouped note, not raw finding rows.
    expect(screen.getAllByTestId('report-audit-note')).toHaveLength(1)
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
