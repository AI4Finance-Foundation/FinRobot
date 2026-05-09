import { describe, it, expect, beforeEach } from 'vitest'
import { useAppStore } from './appStore'

describe('appStore', () => {
  beforeEach(() => {
    useAppStore.getState().reset()
  })

  it('sets ticker', () => {
    useAppStore.getState().setTicker('AAPL')
    expect(useAppStore.getState().ticker).toBe('AAPL')
  })

  it('sets phase', () => {
    useAppStore.getState().setPhase('data_ready')
    expect(useAppStore.getState().phase).toBe('data_ready')
  })

  it('sets and resets DCF inputs', () => {
    const inputs = {
      revenue_base: 1e9,
      revenue_growth_rates: [0.05, 0.05],
      ebitda_margin: 0.35,
      capex_pct_revenue: 0.04,
      nwc_pct_revenue: 0.02,
      tax_rate: 0.21,
      risk_free_rate: 0.043,
      beta: 1.2,
      equity_risk_premium: 0.055,
      cost_of_debt: 0.035,
      debt_ratio: 0.15,
      terminal_growth_rate: 0.025,
      shares_outstanding: 1e8,
      net_debt: 2e8,
    }
    useAppStore.getState().setDcfInputs(inputs)
    expect(useAppStore.getState().dcfInputs).toEqual(inputs)

    useAppStore.getState().reset()
    expect(useAppStore.getState().dcfInputs).toBeNull()
    expect(useAppStore.getState().ticker).toBe('')
    expect(useAppStore.getState().phase).toBe('idle')
  })

  it('sets warnings', () => {
    useAppStore.getState().setWarnings(['test warning'])
    expect(useAppStore.getState().warnings).toEqual(['test warning'])
  })

  it('tracks showSettings', () => {
    expect(useAppStore.getState().showSettings).toBe(false)
    useAppStore.getState().setShowSettings(true)
    expect(useAppStore.getState().showSettings).toBe(true)
  })
})
