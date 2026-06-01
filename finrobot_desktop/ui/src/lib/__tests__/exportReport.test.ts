import { describe, it, expect, afterEach } from 'vitest'
import {
  assembleStandaloneHtml,
  reportFileStem,
  buildReportHtml,
  findReportNode,
} from '../exportReport'

describe('assembleStandaloneHtml', () => {
  const out = assembleStandaloneHtml({
    title: 'NVDA · v3',
    lang: 'zh',
    css: ':root{--bg-void:#0a0a0f}.card{color:red}',
    bodyHtml: '<section data-testid="chapter-cover">cover</section>',
  })

  it('produces a complete standalone document', () => {
    expect(out.startsWith('<!doctype html>')).toBe(true)
    expect(out).toContain('<html lang="zh">')
    expect(out.trimEnd().endsWith('</html>')).toBe(true)
  })

  it('inlines the captured CSS and report body', () => {
    expect(out).toContain(':root{--bg-void:#0a0a0f}')
    expect(out).toContain('data-testid="chapter-cover"')
  })

  it('wraps the body in the centered cosmic export shell', () => {
    expect(out).toContain('class="report-export-shell"')
    expect(out).toContain('background: var(--bg-void, #0a0a0f)')
  })

  it('escapes the title to prevent markup injection', () => {
    const evil = assembleStandaloneHtml({
      title: '<script>x</script>',
      lang: 'en',
      css: '',
      bodyHtml: '',
    })
    expect(evil).toContain('<title>&lt;script&gt;x&lt;/script&gt;</title>')
    expect(evil).not.toContain('<title><script>')
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

describe('buildReportHtml (DOM capture)', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('returns null when the report node is absent', () => {
    expect(findReportNode()).toBeNull()
    expect(buildReportHtml('NVDA · v1')).toBeNull()
  })

  it('captures only the <main> chapters, excluding toolbar/TOC/rail siblings', () => {
    document.body.innerHTML = `
      <div data-testid="artifact-detail-page">
        <div data-testid="report-grid">
          <div data-testid="report-toolbar">TOOLBAR_CHROME</div>
          <nav data-testid="report-toc">TOC_CHROME</nav>
          <main>
            <section data-testid="chapter-cover"><svg><rect/></svg>COVER_BODY</section>
            <aside data-testid="report-right-rail">RAIL_CHROME</aside>
          </main>
        </div>
      </div>`
    // The right-rail in this fixture is nested in main only to prove we grab
    // main wholesale; in the real tree it is a grid sibling and never captured.
    const html = buildReportHtml('NVDA · v1')
    expect(html).not.toBeNull()
    expect(html).toContain('COVER_BODY')
    expect(html).toContain('<svg>') // Recharts-style inline SVG survives
    expect(html).not.toContain('TOOLBAR_CHROME')
    expect(html).not.toContain('TOC_CHROME')
    expect(html).toContain('<title>NVDA · v1</title>')
  })
})
