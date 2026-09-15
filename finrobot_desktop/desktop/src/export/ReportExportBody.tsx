// The exported HTML's body. Mirrors ArtifactDetailPage's in-app type branch so a
// standalone export shows the SAME thing the page does: the 13-chapter report for
// equity_research, the compact single-computation viewer for every other type
// (dcf / ddm / lbo / comps / earnings / ic_memo / …).
//
// Before this branch existed, the export rendered <ReportChapters> for EVERY
// type, so exporting a dcf / ddm / lbo / comps artifact produced an empty
// 13-chapter equity shell (null thesis / valuation / ownership) — the very
// BUG-20260602-039 shell the in-app viewer already avoids via CompactArtifactViewer.

import type { ArtifactDetail } from '../hooks/useV5Artifacts'
import type { ArtifactSummaryV5 } from '../types/v5'
import { isEquityResearch } from '../lib/artifactKind'
import { ReportChapters } from '../pages/artifact-detail/ReportChapters'
import { CompactArtifactViewer } from '../pages/artifact-detail/CompactArtifactViewer'

export function ReportExportBody({
  artifact,
  timeline,
}: {
  artifact: ArtifactDetail
  timeline: ArtifactSummaryV5[]
}): React.ReactElement {
  return isEquityResearch(artifact.type) ? (
    <ReportChapters artifact={artifact} timeline={timeline} />
  ) : (
    <CompactArtifactViewer artifact={artifact} />
  )
}
