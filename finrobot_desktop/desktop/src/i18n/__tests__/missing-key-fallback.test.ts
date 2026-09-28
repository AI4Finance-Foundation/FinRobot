// Missing-key guard (P2 audit 2026-06-10): dynamic keys
// (t(`prefix.${backendValue}`)) must degrade to readable copy when the
// catalog has no entry — never the raw dotted key.
import { describe, it, expect, afterEach } from 'vitest'
import { tSync, useUiPrefs } from '../index'

describe('i18n missing-key fallback', () => {
  afterEach(() => {
    useUiPrefs.setState({ locale: 'en' })
  })

  it('existing key still resolves through the catalog', () => {
    expect(tSync('chatpanel.context.label')).toBe('Context')
  })

  it('missing key humanizes the last segment instead of leaking the raw key', () => {
    expect(tSync('coverage.reason.brand_new_backend_kind')).toBe('brand new backend kind')
    expect(tSync('settings.test.result.someNewCode')).toBe('some new code')
  })

  it('never returns a dotted raw key', () => {
    expect(tSync('a.b.totally_unknown')).not.toContain('.')
  })
})
