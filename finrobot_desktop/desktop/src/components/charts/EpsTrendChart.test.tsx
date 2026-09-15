import { describe, it, expect, beforeEach } from 'vitest'
import { epsBarColor } from './EpsTrendChart'
import { tSync, useUiPrefs } from '../../i18n'

// EPS bars are colored by YoY direction so the growth trajectory is scannable
// without hovering (涨绿跌红). The exact % stays in the tooltip.
describe('epsBarColor — YoY-direction coloring', () => {
  it('greens EPS growth (and flat counts as non-negative)', () => {
    expect(epsBarColor(12)).toBe('var(--success)')
    expect(epsBarColor(0)).toBe('var(--success)')
  })

  it('reds EPS contraction', () => {
    expect(epsBarColor(-8)).toBe('var(--danger)')
  })

  it('keeps the baseline year (no prior → null / non-finite YoY) neutral', () => {
    expect(epsBarColor(null)).toBe('var(--primary)')
    expect(epsBarColor(Number.NaN)).toBe('var(--primary)')
  })
})

// BUG-10 regression: the historical EPS series is basic EPS, not diluted —
// FMP's `eps` field is documented basic (fmp_provider.py), and the yfinance
// path preferentially matches a "Basic EPS" row when the statement carries
// one. QA verified 5/5 AAPL years hit SEC Basic EPS and 0/5 hit Diluted. The
// chart title must say BASIC, never DILUTED (which this pipeline never has).
describe('chapter.financial.chart.title.eps — caliber label', () => {
  beforeEach(() => {
    useUiPrefs.getState().setLocale('en')
  })

  it('labels the chart Basic EPS in English', () => {
    expect(tSync('chapter.financial.chart.title.eps')).toBe('Basic EPS · by Year')
  })

  it('labels the chart 基本 EPS in Chinese, not 摊薄 (diluted)', () => {
    useUiPrefs.getState().setLocale('zh')
    expect(tSync('chapter.financial.chart.title.eps')).toBe('基本 EPS · 逐年')
  })
})
