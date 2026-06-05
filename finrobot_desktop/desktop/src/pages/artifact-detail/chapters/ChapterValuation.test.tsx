// Guards BUG-20260602-021: the report wires <TermTip> onto headline financial
// jargon so a non-IB reader gets an inline gloss. Here we assert the valuation
// chapter renders the WACC term with its glossary definition reachable on hover
// (the tooltip text comes from termDictionary, not the .po catalog).

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ChapterValuation } from './ChapterValuation'
import type { DcfShape } from './types'

// Charts hit nothing relevant to the KV cards; render them as no-ops so the
// chapter mounts without canvas/Recharts noise.
vi.mock('../../../components/charts/FootballField', () => ({ default: () => null }))
vi.mock('../../../components/charts/WaterfallChart', () => ({ default: () => null }))

// The valuation-aggregate query is enabled by ticker; stub fetch so it resolves
// to an empty payload instead of hitting the network.
vi.mock('../../../api/fetch', () => ({
  HEAVY_API_TIMEOUT_MS: 1000,
  fetchWithTimeout: () =>
    Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve({ ticker: 'AAPL', current_price: null, methods: [], warnings: [] }),
    }),
}))

const DCF: DcfShape = {
  wacc: 0.0852,
  enterprise_value: 3.2e12,
  equity_value: 3.0e12,
  implied_price: 240,
  inputs: { terminal_growth_rate: 0.025, tax_rate: 0.21, beta: 1.18 },
}

function renderChapter(dcf: DcfShape = DCF) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ChapterValuation
        dcf={dcf}
        thesis={null}
        ticker="AAPL"
        quoteCurrency="USD"
        reportingCurrency="USD"
      />
    </QueryClientProvider>,
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
