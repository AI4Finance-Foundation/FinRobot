// Standalone HTML export for the 13-chapter research report.
//
// Why HTML and not (only) PDF: PDF goes through the print pipeline, which
// deliberately flips the cosmic dark theme to light ink-on-paper and forces a
// page break per chapter — so the deliverable never looks like what the analyst
// sees on screen. HTML export is a true mirror: the SAME rendered DOM + the SAME
// stylesheets + the SAME Recharts SVGs, continuous scroll, dark cosmic theme.
// Open it in any browser and it is pixel-identical to the in-app report.
//
// Mechanism: clone the report <main> (chapters only — toolbar/TOC/rail are
// siblings and stay out), concatenate every accessible stylesheet into one
// inline <style>, and wrap it in a self-contained document. Recharts renders to
// inline SVG with concrete dimensions baked in at capture time, so charts
// serialize losslessly. There is no theme toggle in the app (data-theme is
// stripped on load — see uiStore), so the captured :root tokens ARE the cosmic
// dark palette; nothing extra to copy.

/** The report content node — chapters only, excluding toolbar/TOC/right-rail. */
export function findReportNode(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[data-testid="artifact-detail-page"] main')
}

/**
 * Concatenate the text of every same-origin stylesheet into one CSS string.
 * Cross-origin sheets (rare here — all CSS is bundled same-origin) throw on
 * .cssRules access; we skip them rather than abort the whole export.
 */
export function collectDocumentCss(): string {
  const chunks: string[] = []
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      const rules = sheet.cssRules
      if (!rules) continue
      for (const rule of Array.from(rules)) chunks.push(rule.cssText)
    } catch {
      // Inaccessible (cross-origin) sheet — skip; the rest still style the doc.
    }
  }
  return chunks.join('\n')
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * Pure assembler — given the captured CSS and the report's inner HTML, produce a
 * complete standalone document. Kept side-effect-free so it is unit-testable
 * without a DOM. The wrapper recreates the page's reading column on the cosmic
 * background; the hex fallbacks cover the instant before :root tokens parse.
 */
export function assembleStandaloneHtml(parts: {
  title: string
  lang: string
  css: string
  bodyHtml: string
}): string {
  const { title, lang, css, bodyHtml } = parts
  return `<!doctype html>
<html lang="${escapeHtml(lang)}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="generator" content="FinRobot" />
<title>${escapeHtml(title)}</title>
<style>
${css}
</style>
<style>
/* Export shell — mirror the in-app reading column on the cosmic backdrop.
   The captured App.css locks scrolling with html,body{height:100%} +
   body{overflow:hidden} (the app scrolls inside an inner .main-content, absent
   here). Re-enable normal document scroll, or the export is a frozen viewport. */
html, body {
  margin: 0;
  padding: 0;
  height: auto !important;
  overflow: auto !important;
  background: var(--bg-void, #0a0a0f);
}
.report-export-shell {
  max-width: 920px;
  margin: 0 auto;
  padding: 28px 24px 72px;
}
</style>
</head>
<body>
<div class="report-export-shell">
${bodyHtml}
</div>
</body>
</html>`
}

/**
 * Capture the live report into a standalone HTML string. Returns null if the
 * report node is not present (e.g. called off the detail page).
 */
export function buildReportHtml(title: string): string | null {
  const node = findReportNode()
  if (!node) return null
  return assembleStandaloneHtml({
    title,
    lang: document.documentElement.lang || 'zh',
    css: collectDocumentCss(),
    bodyHtml: node.outerHTML,
  })
}

/** Filesystem-safe filename stem from a ticker + version label. */
export function reportFileStem(ticker: string, versionLabel: string): string {
  const safe = `${ticker}_${versionLabel}`.replace(/[^\w.-]+/g, '_').replace(/_+/g, '_')
  return safe.replace(/^_|_$/g, '') || 'report'
}
