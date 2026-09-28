// Glue between the app and the pre-built viewer bundle. Kept separate from
// exportReport.ts (the pure assembler) and imported DYNAMICALLY by the export
// handler, so the multi-hundred-KB inlined bundle is a lazy chunk and the ?raw
// imports never enter the unit-test module graph.
//
// The generated/* files are produced by `npm run build:viewer`
// (vite.viewer.config.ts) and are gitignored — rebuilt on dev/build.

import viewerJs from './generated/viewer.js?raw'
import viewerCss from './generated/viewer.css?raw'
import { dehydrate, type QueryClient } from '@tanstack/react-query'
import { assembleInteractiveHtml } from '../lib/exportReport'
import type { ArtifactDetail } from '../hooks/useV5Artifacts'
import type { ArtifactSummaryV5 } from '../types/v5'
import type { Locale } from '../i18n'

// prepareReportExport (cache-seeding) lives in reportExportQueries.ts so it's
// unit-testable WITHOUT pulling the multi-hundred-KB viewer ?raw imports above
// into the test module graph. Re-exported here so the export handler imports
// both from the same lazy chunk.
export { prepareReportExport } from './reportExportQueries'

export function buildInteractiveReportHtml(opts: {
  artifact: ArtifactDetail
  timeline: ArtifactSummaryV5[]
  queryClient: QueryClient
  locale: Locale
  title: string
}): string {
  const payload = {
    artifact: opts.artifact,
    timeline: opts.timeline,
    // Capture the live query cache (historical, price, financials, valuation
    // aggregate…) so the offline viewer renders from it without any fetch.
    queryState: dehydrate(opts.queryClient),
    locale: opts.locale,
  }
  return assembleInteractiveHtml({
    title: opts.title,
    lang: opts.locale,
    css: viewerCss,
    js: viewerJs,
    payloadJson: JSON.stringify(payload),
  })
}
