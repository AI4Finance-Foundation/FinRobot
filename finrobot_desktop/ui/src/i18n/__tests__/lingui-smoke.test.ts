import { describe, it, expect, beforeEach } from 'vitest'
import { i18n, tSync, useUiPrefs } from '..'

describe('i18n / lingui runtime', () => {
  beforeEach(() => {
    // Reset to zh for each test (StrictMode + persist may carry state).
    useUiPrefs.getState().setLocale('zh')
  })

  it('translates a static zh key', () => {
    expect(tSync('nav.stocks')).toBe('股票')
  })

  it('falls back to key when missing', () => {
    expect(tSync('this.key.does.not.exist')).toBe('this.key.does.not.exist')
  })

  it('interpolates {param} placeholders', () => {
    const out = tSync('chat.empty.example.1', { ticker: 'AAPL' })
    expect(out).toContain('AAPL')
    expect(out).toContain('今天为什么跌')
  })

  it('switches locale via setLocale', () => {
    useUiPrefs.getState().setLocale('en')
    expect(i18n.locale).toBe('en')
    expect(tSync('nav.stocks')).toBe('Stocks')
  })

  it('zh catalog and en catalog have the same key set', () => {
    const zh = i18n.messages // current after setLocale('en') above
    // re-activate both and pull keys
    useUiPrefs.getState().setLocale('zh')
    const zhKeys = Object.keys(i18n.messages).sort()
    useUiPrefs.getState().setLocale('en')
    const enKeys = Object.keys(i18n.messages).sort()
    expect(enKeys).toEqual(zhKeys)
    expect(zhKeys.length).toBeGreaterThan(150)
  })
})
