// ChapterSensitivity — the model-vs-current assumptions reconciliation table
// (batch 1b) and the ±2pp EBITDA-margin swing note (batch 1d). The reconciliation
// renders the backend provenance prose VERBATIM in "Model uses" and the
// backend-computed latest actuals in "Current" (never re-derived here); the ⚠ is
// driven by the structured nwc_clamped boolean, never by parsing the prose. The
// app renders EN by default, so assertions use the EN catalog strings.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterSensitivity, SensitivityBody } from './ChapterSensitivity'
import type { DcfShape } from './types'

const PROVENANCE = {
  revenue_growth_rates: '10.4% avg (consensus FY1-3, fade)',
  ebitda_margin: '53.7% (trailing 3yr median)',
  capex_pct_revenue: '18.1% (trailing 3yr median)',
  nwc_pct_revenue: '10.0% (clamped, median +13.2%)',
}

function dcf(over: Partial<DcfShape> = {}): DcfShape {
  return {
    wacc: 0.09,
    inputs: {
      terminal_growth_rate: 0.025,
      ebitda_margin: 0.537,
      assumption_provenance: PROVENANCE,
      nwc_clamped: false,
    },
    assumption_current_actuals: {
      revenue_growth: 0.084,
      ebitda_margin: 0.605,
      capex_pct_revenue: 0.305,
      nwc_pct_revenue: 0.019,
    },
    assumption_current_actuals_fy: 2024,
    assumption_current_actuals_capex_ttm: true,
    margin_swing: [453.0, 531.0],
    ...over,
  }
}

function renderChapter(shape: DcfShape | null, financialSector = false) {
  return render(
    <ChapterSensitivity dcf={shape} financialSector={financialSector} quoteCurrency="USD" />,
  )
}

describe('ChapterSensitivity — assumptions reconciliation', () => {
  it('renders the four drivers with provenance VERBATIM in "Model uses"', () => {
    renderChapter(dcf())
    expect(screen.getByText('Explicit-Period Assumptions · Model vs Current')).toBeInTheDocument()
    // Provenance strings rendered as-is (never reformatted).
    expect(screen.getByText('53.7% (trailing 3yr median)')).toBeInTheDocument()
    expect(screen.getByText('18.1% (trailing 3yr median)')).toBeInTheDocument()
    expect(screen.getByText(/10\.4% avg \(consensus FY1-3, fade\)/)).toBeInTheDocument()
    // Driver labels.
    expect(screen.getByText('EBITDA margin')).toBeInTheDocument()
    expect(screen.getByText('Capex / revenue')).toBeInTheDocument()
  })

  it('renders the current actuals, signed for growth/ΔNWC', () => {
    renderChapter(dcf())
    expect(screen.getByText('60.5%')).toBeInTheDocument() // ebitda margin (TTM), unsigned
    expect(screen.getByText('30.5%')).toBeInTheDocument() // capex, unsigned
    expect(screen.getByText('+8.4%')).toBeInTheDocument() // growth, signed +
    expect(screen.getByText('+1.9%')).toBeInTheDocument() // ΔNWC, signed +
  })

  it('discloses mixed calibers per cell: margin+capex TTM, growth+ΔNWC FY<year>', () => {
    renderChapter(dcf())
    // Neutral column header (not "Latest FY") since calibers differ per cell.
    expect(screen.getByText('Current actual')).toBeInTheDocument()
    // Margin and capex are both TTM figures (assumption_current_actuals_capex_ttm
    // true in the fixture); growth + ΔNWC are the two latest-FY drivers.
    expect(screen.getAllByText('TTM').length).toBe(2)
    expect(screen.getAllByText('FY2024').length).toBe(2)
  })

  it('omits the FY caliber tag when the fiscal year is unknown (legacy)', () => {
    renderChapter(dcf({ assumption_current_actuals_fy: null }))
    expect(screen.queryByText('FY2024')).not.toBeInTheDocument()
    // Margin + capex still carry TTM (neither depends on the fiscal year).
    expect(screen.getAllByText('TTM').length).toBe(2)
  })

  it('labels capex FY<year>, not TTM, when the TTM capex figure was unavailable', () => {
    renderChapter(dcf({ assumption_current_actuals_capex_ttm: false }))
    // Only the margin row is TTM now; capex joins growth/ΔNWC at FY2024.
    expect(screen.getAllByText('TTM').length).toBe(1)
    expect(screen.getAllByText('FY2024').length).toBe(3)
  })

  it('labels capex FY<year> on a legacy artifact predating the capex-TTM field', () => {
    renderChapter(dcf({ assumption_current_actuals_capex_ttm: undefined }))
    // Legacy artifacts never had a TTM capex source — undefined must resolve to
    // the FY label, not silently claim TTM.
    expect(screen.getAllByText('TTM').length).toBe(1)
    expect(screen.getAllByText('FY2024').length).toBe(3)
  })

  it('shows the ⚠ clamp marker on ΔNWC only when nwc_clamped is true', () => {
    const { rerender } = renderChapter(dcf({ inputs: { ...dcf().inputs, nwc_clamped: true } }))
    expect(screen.getByText('⚠')).toBeInTheDocument()
    rerender(
      <ChapterSensitivity
        dcf={dcf({ inputs: { ...dcf().inputs, nwc_clamped: false } })}
        financialSector={false}
        quoteCurrency="USD"
      />,
    )
    expect(screen.queryByText('⚠')).not.toBeInTheDocument()
  })

  it('shows N/A when a current actual is missing, never fabricated', () => {
    renderChapter(
      dcf({ assumption_current_actuals: { revenue_growth: null, ebitda_margin: 0.605 } }),
    )
    // capex + nwc absent from the dict, growth explicitly null → three N/A cells.
    expect(screen.getAllByText('N/A').length).toBe(3)
  })

  it('does not render the reconciliation when provenance is absent (legacy artifact)', () => {
    renderChapter(dcf({ inputs: { terminal_growth_rate: 0.025 } }))
    expect(
      screen.queryByText('Explicit-Period Assumptions · Model vs Current'),
    ).not.toBeInTheDocument()
  })
})

describe('ChapterSensitivity — ±2pp margin swing note', () => {
  it('renders the swing range when both ends resolved', () => {
    renderChapter(dcf())
    expect(
      screen.getByText(/±2pp EBITDA-margin shift moves implied price across/),
    ).toBeInTheDocument()
    expect(screen.getByText('$453–$531')).toBeInTheDocument()
  })

  it('omits the swing note when one end degraded (null)', () => {
    renderChapter(dcf({ margin_swing: [453.0, null] }))
    expect(screen.queryByText(/±2pp EBITDA-margin shift/)).not.toBeInTheDocument()
  })

  it('omits the swing note when margin_swing is absent', () => {
    renderChapter(dcf({ margin_swing: null }))
    expect(screen.queryByText(/±2pp EBITDA-margin shift/)).not.toBeInTheDocument()
  })
})

describe('SensitivityBody — showReconciliation gate (compact tool page)', () => {
  it('hides the reconciliation table but keeps the margin swing note when false', () => {
    render(
      <SensitivityBody
        dcf={dcf()}
        financialSector={false}
        quoteCurrency="USD"
        showReconciliation={false}
      />,
    )
    // Reconciliation suppressed → its "Model uses" strings must not double-list the
    // CompactArtifactViewer's own ProvenanceList (同源双列 red line).
    expect(
      screen.queryByText('Explicit-Period Assumptions · Model vs Current'),
    ).not.toBeInTheDocument()
    // The margin swing note is non-duplicative → still renders.
    expect(screen.getByText('$453–$531')).toBeInTheDocument()
  })
})

describe('ChapterSensitivity — financial-sector degradation preserved', () => {
  it('shows the not-applicable note and no reconciliation for a balance-sheet financial', () => {
    renderChapter(dcf(), true)
    expect(
      screen.queryByText('Explicit-Period Assumptions · Model vs Current'),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/±2pp EBITDA-margin shift/)).not.toBeInTheDocument()
  })
})
