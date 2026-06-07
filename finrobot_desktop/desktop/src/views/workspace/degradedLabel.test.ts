import { describe, it, expect, beforeEach } from 'vitest'
import { tSync, useUiPrefs } from '../../i18n'
import { degradedLabel } from './degradedLabel'

// Every backend degradation marker (contracts.py) must resolve to a human label,
// never leak the raw developer code to the analyst (可溯源 readability). The four
// markers below previously fell through MarketDataZone's lookup and rendered raw
// (e.g. "circuit_open:fmp"). The prefixed ones interpolate their provider/field.
describe('degradedLabel', () => {
  beforeEach(() => {
    useUiPrefs.getState().setLocale('en')
  })

  it('labels the simple markers without leaking the raw code', () => {
    for (const flag of [
      'close_only',
      'ttm_lag',
      'ccy_inferred',
      'price_fallback_close',
      'period_basis_unknown',
    ]) {
      const label = degradedLabel(tSync, flag)
      expect(label).not.toBe(flag) // resolved, not the raw marker
      expect(label).not.toContain('workspace.market.degraded') // not the raw i18n id
    }
  })

  it('interpolates the skipped provider name for circuit_open', () => {
    const label = degradedLabel(tSync, 'circuit_open:fmp')
    expect(label).toContain('FMP')
    expect(label).not.toContain('circuit_open:fmp')
  })

  it('interpolates the field for provider_divergence', () => {
    const label = degradedLabel(tSync, 'provider_divergence:revenue')
    expect(label).toContain('revenue')
    expect(label).not.toContain('provider_divergence:revenue')
  })

  it('interpolates the field for price_divergence', () => {
    const label = degradedLabel(tSync, 'price_divergence:current_price')
    expect(label).toContain('current_price')
    expect(label).not.toContain('price_divergence:current_price')
  })

  it('falls back to the raw flag for a genuinely unknown marker', () => {
    expect(degradedLabel(tSync, 'totally_unknown_marker')).toBe('totally_unknown_marker')
  })
})
