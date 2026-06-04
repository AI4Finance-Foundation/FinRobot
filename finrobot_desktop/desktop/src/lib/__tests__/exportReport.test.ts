import { describe, it, expect } from 'vitest'
import { assembleInteractiveHtml, reportFileStem } from '../exportReport'

describe('assembleInteractiveHtml', () => {
  const out = assembleInteractiveHtml({
    title: 'NVDA · v3',
    lang: 'zh',
    css: '.card{color:red}',
    js: 'console.log("viewer")',
    payloadJson: '{"artifact":{"id":"a1"},"locale":"zh"}',
  })

  it('produces a complete standalone document', () => {
    expect(out.startsWith('<!doctype html>')).toBe(true)
    expect(out).toContain('<html lang="zh">')
    expect(out.trimEnd().endsWith('</html>')).toBe(true)
  })

  it('inlines the css, the data payload, and the viewer bundle', () => {
    expect(out).toContain('.card{color:red}')
    expect(out).toContain('window.__FINROBOT_REPORT__ = ')
    expect(out).toContain('console.log("viewer")')
    expect(out).toContain('"id":"a1"')
  })

  it('escapes the title to prevent markup injection', () => {
    const evil = assembleInteractiveHtml({
      title: '<script>x</script>',
      lang: 'en',
      css: '',
      js: '',
      payloadJson: '{}',
    })
    expect(evil).toContain('<title>&lt;script&gt;x&lt;/script&gt;</title>')
    expect(evil).not.toContain('<title><script>')
  })

  it('hardens inlined JS so a literal </script> cannot break out of the tag', () => {
    const out2 = assembleInteractiveHtml({
      title: 't',
      lang: 'en',
      css: '',
      js: 'var s = "</script>"',
      payloadJson: '{}',
    })
    expect(out2).toContain('<\\/script>')
    expect(out2).not.toContain('"</script>"')
  })

  it('escapes < inside the JSON payload so it cannot close the script tag', () => {
    const out3 = assembleInteractiveHtml({
      title: 't',
      lang: 'en',
      css: '',
      js: '',
      payloadJson: '{"x":"a</script>b"}',
    })
    expect(out3).toContain('\\u003c/script>')
    expect(out3).not.toContain('"a</script>b"')
  })
})

describe('reportFileStem', () => {
  it('keeps simple alphanumerics', () => {
    expect(reportFileStem('NVDA', 'v3')).toBe('NVDA_v3')
  })

  it('sanitizes spaces and unsafe chars to single underscores', () => {
    expect(reportFileStem('BRK.B', 'v2 (latest)')).toBe('BRK.B_v2_latest')
  })

  it('falls back to "report" when nothing usable remains', () => {
    expect(reportFileStem('/', '?')).toBe('report')
  })
})
