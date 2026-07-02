// Guards BUG-20260602-021: the report wires <TermTip> onto headline financial
// jargon so a non-IB reader gets an inline gloss. Here we assert the valuation
// chapter renders the WACC term with its glossary definition reachable on hover
// (the tooltip text comes from termDictionary, not the .po catalog).

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { ChapterValuation } from './ChapterValuation'
import type {
  DcfShape,
  ForwardEstimatesShape,
  NumericAuditShape,
  ThesisShape,
  ValuationSynthesisShape,
} from './types'

// Capture the props the football field receives so we can assert the report
// feeds it the FROZEN snapshot price + method rows — never a live refetch
// (the price-split bug this chapter's rewrite fixes). WaterfallChart is noise.
const footballProps = vi.fn()
vi.mock('../../../components/charts/FootballField', () => ({
  default: (props: Record<string, unknown>) => {
    footballProps(props)
    return null
  },
}))
vi.mock('../../../components/charts/WaterfallChart', () => ({ default: () => null }))

const DCF: DcfShape = {
  wacc: 0.0852,
  enterprise_value: 3.2e12,
  equity_value: 3.0e12,
  implied_price: 240,
  inputs: { terminal_growth_rate: 0.025, tax_rate: 0.21, beta: 1.18 },
}

function renderChapter(
  dcf: DcfShape = DCF,
  numericAudit: NumericAuditShape | null = null,
  valuationSynthesis: ValuationSynthesisShape | null = null,
  forwardEstimates: ForwardEstimatesShape | null = null,
  thesis: ThesisShape | null = null,
) {
  return render(
    <ChapterValuation
      dcf={dcf}
      thesis={thesis}
      valuationSynthesis={valuationSynthesis}
      forwardEstimates={forwardEstimates}
      quoteCurrency="USD"
      reportingCurrency="USD"
      numericAudit={numericAudit}
      sotpBreakdown={null}
    />,
  )
}

describe('ChapterValuation TermTip wiring', () => {
  it('renders the WACC value and a hoverable WACC term explainer', () => {
    renderChapter()
    // WACC value card renders.
    expect(screen.getByText('8.52%')).toBeInTheDocument()
    // The WACC label is a TermTip anchor (help cursor + aria-label).
    const anchor = screen.getByLabelText(/WACC/i)
    expect(anchor).toBeInTheDocument()
    // Hovering surfaces the glossary definition from termDictionary.
    fireEvent.mouseEnter(anchor)
    expect(
      screen.getByText(/Weighted Average Cost of Capital|加权平均资本成本/),
    ).toBeInTheDocument()
  })
})

// Reverse-DCF reality check: the deterministic market-implied growth must render
// from the computed field (compute-derived number, never LLM prose). Two states:
// a reachable implied growth %, and the option-value 'unreachable' state with the
// quantified ceiling note (the honest TSLA output: even 50% growth → $302.57).
describe('ChapterValuation market-implied growth', () => {
  it('renders the implied growth % with its horizon when reachable', () => {
    renderChapter({
      ...DCF,
      market_implied: {
        horizon_years: 10,
        implied_growth: 0.226,
        implied_wacc: 0.072,
        growth_unreachable: false,
      },
    })
    expect(screen.getByText(/市场隐含增长|Market-Implied Growth/)).toBeInTheDocument()
    expect(screen.getByText('22.6%')).toBeInTheDocument()
    // Horizon rides as the cell's secondary line.
    expect(screen.getByText(/10 年期|over 10y/)).toBeInTheDocument()
    // No unreachable note in the reachable state.
    expect(screen.queryByText(/无解|Unreachable/)).not.toBeInTheDocument()
    // Companion reverse-DCF lever: implied WACC + a descriptive delta vs our DCF
    // WACC (DCF.wacc = 0.0852 → "vs DCF 8.5%"). Was computed but never rendered.
    expect(screen.getByText(/市场隐含 WACC|Market-Implied WACC/)).toBeInTheDocument()
    expect(screen.getByText('7.2%')).toBeInTheDocument()
    expect(screen.getByText(/vs DCF 8\.5%/)).toBeInTheDocument()
  })

  it('renders the unreachable state with the quantified ceiling note', () => {
    renderChapter({
      ...DCF,
      market_implied: {
        horizon_years: 10,
        implied_growth: null,
        implied_wacc: null,
        growth_unreachable: true,
        growth_ceiling: 0.5,
        ceiling_price: 302.57,
      },
    })
    // The KV cell shows the unreachable label instead of a %.
    expect(screen.getByText(/^无解$|^Unreachable$/)).toBeInTheDocument()
    // The note quantifies the ceiling: 50% growth only reaches $302.57.
    const note = screen.getByText(/302\.57/)
    expect(note).toBeInTheDocument()
    expect(note.textContent).toMatch(/50%/)
    expect(note.textContent).toMatch(/期权价值|optionality/)
    // Implied-WACC cell is suppressed in the unreachable regime (no finite solve).
    expect(screen.queryByText(/市场隐含 WACC|Market-Implied WACC/)).not.toBeInTheDocument()
  })

  it('renders no implied-growth cell when the field is absent (legacy artifacts)', () => {
    renderChapter(DCF)
    expect(screen.queryByText(/市场隐含增长|Market-Implied Growth/)).not.toBeInTheDocument()
    expect(screen.queryByText(/市场隐含 WACC|Market-Implied WACC/)).not.toBeInTheDocument()
  })
})

// The EV KvGrid cell carries a hover caveat when the numeric-audit gate flagged
// an EV-family field (bank EV category error / cross-currency ratio). No flag ⇒
// no marker, so clean reports are untouched.
describe('ChapterValuation EV audit caveat', () => {
  const EV_AUDIT: NumericAuditShape = {
    artifact_status: 'caveated',
    withhold_valuation: true,
    findings: [
      {
        field_key: 'enterprise_value',
        check: 'financial_sector_ev_meaningless',
        severity: 'blocked_field',
        evidence: 'JPM industry=banks: enterprise_value is a category error. Value on P/B, ROTCE.',
      },
    ],
  }

  it('shows the EV caveat marker (with evidence on hover) when EV is flagged', () => {
    renderChapter(DCF, EV_AUDIT)
    const caveat = screen.getByTestId('field-caveat')
    expect(caveat).toBeInTheDocument()
    expect(caveat.getAttribute('title')).toMatch(/category error/)
  })

  it('shows no EV caveat when the audit is clean / absent', () => {
    renderChapter(DCF, null)
    expect(screen.queryByTestId('field-caveat')).not.toBeInTheDocument()
  })
})

// The football field MUST render from the frozen valuation_synthesis (the
// snapshot the report's target was computed against), never a live refetch —
// otherwise the football "current" price drifts away from the cover/narrative
// price (the reported bug: narrative $307.34 vs football $312).
describe('ChapterValuation frozen football field', () => {
  const SYNTHESIS: ValuationSynthesisShape = {
    current_price: 307.34,
    weighted_price: 174.14,
    upside_downside: -0.4334,
    reliable: true,
    methods: [
      {
        name: 'dcf',
        low: 108.94,
        mid: 136.18,
        high: 163.41,
        confidence: 0.85,
        source: 'implied_price ± 20%',
      },
      {
        name: 'comps_pe',
        low: 193.02,
        mid: 214.47,
        high: 235.92,
        confidence: 0.8,
        source: 'peer_median_forward_pe × forward_eps',
      },
    ],
  }

  it('feeds the football field the frozen snapshot price + method rows', () => {
    footballProps.mockClear()
    renderChapter(DCF, null, SYNTHESIS)
    expect(footballProps).toHaveBeenCalled()
    const props = footballProps.mock.calls.at(-1)![0] as Record<string, unknown>
    // Snapshot price flows straight through — no live quote anywhere.
    expect(props.currentPrice).toBe(307.34)
    // Method `name` (dcf / comps_pe) becomes the football row `method` key.
    expect(props.data).toEqual([
      expect.objectContaining({ method: 'dcf', mid: 136.18 }),
      expect.objectContaining({ method: 'comps_pe', mid: 214.47 }),
    ])
  })

  it('renders no football field when the artifact carries no synthesis', () => {
    footballProps.mockClear()
    renderChapter(DCF, null, null)
    expect(footballProps).not.toHaveBeenCalled()
  })

  it('passes the frozen forward fiscal period + renders the source footnote', () => {
    footballProps.mockClear()
    renderChapter(DCF, null, SYNTHESIS, {
      fiscal_period: '2026-09-30',
      source: 'FMP /v3/analyst-estimates (FY1 consensus)',
      confidence: 'high',
    })
    const props = footballProps.mock.calls.at(-1)![0] as Record<string, unknown>
    // FY tag comes from the frozen provenance, not a live aggregate refetch.
    expect(props.forwardFiscalPeriod).toBe('2026-09-30')
    // Footnote cites the frozen source + confidence.
    expect(screen.getByText(/FMP \/v3\/analyst-estimates/)).toBeInTheDocument()
    expect(screen.getByText(/high/)).toBeInTheDocument()
  })
})

// 🔴 Surface gate #1 (prop chain): the football field's Target point MUST be the
// HEADLINE target (thesis.price_target — the same number the cover / left-rail /
// synthesis publish), NEVER valuation_synthesis.weighted_price. When the confidence
// dial judges a method an outlier it DISCARDS the blend and anchors the headline on
// a single method (anchor-not-blend), so weighted_price is the rejected midpoint;
// feeding it to the football field printed "Target $209" while the cover said $188
// (the price-split bug, AAPL art_2026-07-02). Render-side companion gate lives in
// FootballField.test.tsx ("Target" label points only at the headline point).
type TargetBandProps = {
  targetBand?: { point?: number | null; low?: number | null; high?: number | null }
}
function lastTargetBand(): TargetBandProps['targetBand'] {
  return (footballProps.mock.calls.at(-1)![0] as TargetBandProps).targetBand
}

describe('ChapterValuation football-field target = headline, not the discarded blend', () => {
  // Anchor regime: EV/EBITDA judged an outlier → headline anchored to DCF $188.31,
  // the weighted blend $208.65 rejected (AAPL art_2026-07-02 shape).
  const ANCHORED: ValuationSynthesisShape = {
    current_price: 210.02,
    weighted_price: 208.65, // the DISCARDED blend — must NOT be the Target point
    target_low: 170,
    target_high: 205,
    anchor_method: 'dcf',
    confidence: 'medium',
    methods: [
      {
        name: 'dcf',
        low: 165,
        mid: 188.31,
        high: 210,
        confidence: 0.85,
        source: 'implied_price ± 12%',
      },
      {
        name: 'comps_pe',
        low: 240,
        mid: 266,
        high: 292,
        confidence: 0.8,
        source: 'peer_median_forward_pe × forward_eps',
      },
      {
        name: 'ev_ebitda',
        low: 150,
        mid: 183,
        high: 210,
        confidence: 0.7,
        source: 'peer_median_ev_ebitda × ebitda',
      },
    ],
  }

  it('feeds the anchored headline target ($188.31), not the rejected blend ($208.65)', () => {
    footballProps.mockClear()
    renderChapter(DCF, null, ANCHORED, null, {
      recommendation: 'HOLD',
      price_target: 188.31,
      price_target_basis: 'anchored to the corroborated DCF $188 rather than a blend',
    })
    const band = lastTargetBand()
    expect(band?.point).toBe(188.31) // headline (anchor value)
    expect(band?.point).not.toBe(208.65) // never the discarded weighted blend
  })

  it('withheld point (thesis.price_target absent) draws no marker but keeps the band', () => {
    footballProps.mockClear()
    renderChapter(DCF, null, { ...ANCHORED, valuation_withheld: true }, null, {
      recommendation: 'HOLD',
      price_target_basis: 'FAIRLY VALUED — price sits inside the fair-value range',
    })
    const band = lastTargetBand()
    expect(band?.point).toBeNull() // 撤点: no headline point → no marker
    expect(band?.low).toBe(170) // ≠撤区间: the fair-value band still renders
    expect(band?.high).toBe(205)
  })

  // Regression (no-anchor / TSM shape): when methods corroborate, the backend
  // publishes the blend AS the headline, so thesis.price_target == weighted_price
  // and the Target point must still equal that value. This coincidence (anchor ==
  // weighted) is exactly what masked the bug on TSM.
  it('no-anchor regime keeps the Target point == weighted blend (headline == blend)', () => {
    footballProps.mockClear()
    const CORROBORATED: ValuationSynthesisShape = {
      current_price: 180,
      weighted_price: 205.5,
      target_low: 190,
      target_high: 221,
      confidence: 'high',
      methods: [
        {
          name: 'dcf',
          low: 185,
          mid: 204,
          high: 223,
          confidence: 0.85,
          source: 'implied_price ± 10%',
        },
        {
          name: 'comps_pe',
          low: 190,
          mid: 207,
          high: 224,
          confidence: 0.8,
          source: 'peer_median_forward_pe × forward_eps',
        },
      ],
    }
    renderChapter(DCF, null, CORROBORATED, null, {
      recommendation: 'BUY',
      price_target: 205.5, // backend publishes the blend as the headline
    })
    expect(lastTargetBand()?.point).toBe(205.5) // == weighted_price, unchanged
  })
})
