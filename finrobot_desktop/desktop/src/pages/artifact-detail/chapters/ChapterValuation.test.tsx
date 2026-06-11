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
) {
  return render(
    <ChapterValuation
      dcf={dcf}
      thesis={null}
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
  })

  it('renders no implied-growth cell when the field is absent (legacy artifacts)', () => {
    renderChapter(DCF)
    expect(screen.queryByText(/市场隐含增长|Market-Implied Growth/)).not.toBeInTheDocument()
  })
})

// The EV KvGrid cell carries a hover caveat when the numeric-audit gate flagged
// an EV-family field (bank EV category error / cross-currency ratio). No flag ⇒
// no marker, so clean reports are untouched.
describe('ChapterValuation EV audit caveat', () => {
  const EV_AUDIT: NumericAuditShape = {
    artifact_status: 'review_only',
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
