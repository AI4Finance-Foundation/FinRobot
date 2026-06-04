// Standalone INTERACTIVE HTML export for the research report.
//
// Earlier this serialized the live DOM to a static file — but a static snapshot
// has no JavaScript, so Recharts hover tooltips, the sensitivity heatmap and the
// football field were all dead. This now ships a real, self-contained mini-app:
// a lean React+Recharts bundle (built from src/export/viewer.tsx) plus the
// report's data inlined as JSON. Opened in any browser it re-renders the exact
// same <ReportChapters>, fully interactive, fully offline.
//
// This module is the PURE assembler + filename helper — no bundle imports, so it
// stays unit-testable without the generated viewer build. The bundle wiring
// lives in src/export/bundle.ts.

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** Neutralize a literal `</script` so inlined JS can't break out of its tag. */
function hardenScript(js: string): string {
  return js.replace(/<\/(script)/gi, '<\\/$1')
}

/** JSON inside a <script> must not contain a raw `<` (it could close the tag or
 *  open an HTML comment). `<` is valid JSON and parses identically. */
function hardenJson(json: string): string {
  return json.replace(/</g, '\\u003c')
}

/**
 * Assemble a complete, self-contained interactive report document: the viewer
 * CSS in <head>, the data payload and the viewer IIFE bundle at end of <body>.
 * Pure — given the four strings it returns the final HTML.
 */
export function assembleInteractiveHtml(parts: {
  title: string
  lang: string
  css: string
  js: string
  payloadJson: string
}): string {
  const { title, lang, css, js, payloadJson } = parts
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
</head>
<body>
<div id="root"></div>
<script>window.__FINROBOT_REPORT__ = ${hardenJson(payloadJson)};</script>
<script>${hardenScript(js)}</script>
</body>
</html>`
}

/** Filesystem-safe filename stem from a ticker + version label. */
export function reportFileStem(ticker: string, versionLabel: string): string {
  const safe = `${ticker}_${versionLabel}`.replace(/[^\w.-]+/g, '_').replace(/_+/g, '_')
  return safe.replace(/^_|_$/g, '') || 'report'
}
