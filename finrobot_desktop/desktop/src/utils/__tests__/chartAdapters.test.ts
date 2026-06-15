import { describe, it, expect } from 'vitest'
import { compsResultToRadarData, dcfResultToMarginData } from '../chartAdapters'
import type { CompsResult, DCFResult } from '../../types/finance'

// Only the fields the radar reads; the cast mirrors ChapterCompetitive's own
// `as unknown as CompsResult` (the full shape is large and irrelevant here).
function makeCompsResult(): CompsResult {
  return {
    target: {
      ticker: 'TGT',
      pe_ratio: 20, // vs median 40 → 2x cheaper → outward (capped 200)
      ev_ebitda: 20, // vs median 10 → expensive → inside (50)
      ev_revenue: 5, // vs median 5 → at median (100)
      gross_margin: 0.6, // vs peer median 0.4 → outward (150)
      operating_margin: 0.3, // vs peer median 0.2 → outward (150)
    },
    peers: [
      { gross_margin: 0.3, operating_margin: 0.1 },
      { gross_margin: 0.4, operating_margin: 0.2 },
      { gross_margin: 0.5, operating_margin: 0.3 },
    ],
    median_pe: 40,
    median_ev_ebitda: 10,
    median_ev_revenue: 5,
  } as unknown as CompsResult
}

function makeDcfResult(daPct: number | undefined): DCFResult {
  return {
    cost_of_equity: 0.1,
    wacc: 0.1,
    projection_years: 2,
    projected_revenue: [110, 120],
    projected_ebitda: [33, 36],
    projected_fcf: [20, 22],
    terminal_value: 500,
    pv_terminal: 300,
    pv_fcf_total: 40,
    enterprise_value: 340,
    equity_value: 320,
    implied_price: 32,
    sensitivity_table: null,
    inputs: {
      revenue_base: 100,
      revenue_growth_rates: [0.1, 0.09],
      ebitda_margin: 0.3,
      capex_pct_revenue: 0.03,
      nwc_pct_revenue: 0.01,
      da_pct_revenue: daPct,
      tax_rate: 0.21,
      risk_free_rate: 0.04,
      beta: 1.1,
      equity_risk_premium: 0.05,
      cost_of_debt: 0.04,
      debt_ratio: 0.2,
      terminal_growth_rate: 0.025,
      shares_outstanding: 10,
      net_debt: 20,
    },
  }
}

describe('dcfResultToMarginData operating margin (D5)', () => {
  it('derives EBIT margin = EBITDA margin - D&A% when D&A is known', () => {
    const rows = dcfResultToMarginData(makeDcfResult(0.05))
    // base year: ebitda_margin 0.30, operating 0.30 - 0.05 = 0.25
    expect(rows[0].ebitda_margin).toBeCloseTo(0.3)
    expect(rows[0].operating_margin).toBeCloseTo(0.25)
  })

  it('emits null operating_margin when D&A% is unknown — never equals EBITDA margin', () => {
    const rows = dcfResultToMarginData(makeDcfResult(undefined))
    for (const row of rows) {
      expect(row.operating_margin).toBeNull()
      // EBITDA margin still rendered; the two must not silently coincide.
      expect(row.ebitda_margin).not.toBeNull()
    }
  })

  it('treats da_pct_revenue=0 as unknown rather than zero-D&A', () => {
    const rows = dcfResultToMarginData(makeDcfResult(0))
    expect(rows[0].operating_margin).toBeNull()
  })
})

describe('compsResultToRadarData — outward = favorable vs peer median', () => {
  it('pins the benchmark ring to 100 and pushes cheaper multiples / higher margins outward', () => {
    const rows = compsResultToRadarData(makeCompsResult())
    // Fixed-order axes (pe, evEbitda, evRevenue, grossMargin, operatingMargin).
    expect(rows).toHaveLength(5)
    rows.forEach((r) => expect(r.benchmark).toBe(100)) // peer median = the ring
    expect(rows[0].value).toBe(200) // P/E 20 vs 40 → 2x cheaper, capped outward
    expect(rows[1].value).toBe(50) // EV/EBITDA 20 vs 10 → expensive, inside
    expect(rows[2].value).toBe(100) // EV/Rev at median
    expect(rows[3].value).toBe(150) // gross margin above peer median → outward
    expect(rows[4].value).toBe(150) // operating margin above peer median → outward
  })

  it('drops an ill-defined valuation axis (negative P/E) instead of plotting it', () => {
    const r = makeCompsResult()
    ;(r.target as { pe_ratio: number }).pe_ratio = -15 // a loss → P/E is N/A, not "cheap"
    const rows = compsResultToRadarData(r)
    expect(rows).toHaveLength(4) // the P/E axis is excluded, not mapped to a bogus value
  })
})
