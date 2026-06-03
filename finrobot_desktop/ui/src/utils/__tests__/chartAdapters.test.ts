import { describe, it, expect } from 'vitest'
import { dcfResultToMarginData } from '../chartAdapters'
import type { DCFResult } from '../../types/finance'

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
