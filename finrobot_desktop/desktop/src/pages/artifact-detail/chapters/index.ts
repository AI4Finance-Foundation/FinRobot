// Barrel export for the 13 chapters.

export { ChapterCover } from './ChapterCover'
export { ChapterThesis } from './ChapterThesis'
export { ChapterCompanyOverview } from './ChapterCompanyOverview'
export { ChapterFinancialAnalysis } from './ChapterFinancialAnalysis'
export { ChapterValuation, ValuationBody } from './ChapterValuation'
export { ChapterNews } from './ChapterNews'
export { ChapterSensitivity, SensitivityBody } from './ChapterSensitivity'
export { ChapterCatalysts } from './ChapterCatalysts'
export { ChapterTechnical } from './ChapterTechnical'
export { ChapterCompetitive, CompetitiveBody } from './ChapterCompetitive'
// Standalone tool-page bodies — reuse the report's chapter primitives without the
// numbered <Chapter> chrome (rendered by CompactArtifactViewer under its own header).
export { DcfForecastTable } from './DcfForecastTable'
export { DdmBody } from './DdmPanel'
export { LboBody } from './LboPanel'
export { ChapterFinancialData } from './ChapterFinancialData'
export { ChapterOwnershipGovernance } from './ChapterOwnershipGovernance'
export { ChapterDisclaimer } from './ChapterDisclaimer'

export type {
  ArtifactStructured,
  ThesisShape,
  DcfShape,
  ValuationMethodShape,
  ValuationSynthesisShape,
  SOTPBreakdownShape,
  SegmentValuationShape,
  SegmentOverviewShape,
  SegmentShareShape,
  ForwardEstimatesShape,
  CatalystAnalysisShape,
  CatalystEventShape,
  PeerCompsShape,
  CompanyFinancialsShape,
  MonteCarloShape,
  SniperShape,
  HistoricalBandShape,
  TechnicalAnalysisShape,
  OwnershipGovernanceShape,
  InsiderTransactionShape,
  InstitutionalHoldingShape,
  ProxyCompensationShape,
  ScheduleThirteenAlertShape,
  FilingProvenanceShape,
  SecFilingsShape,
  SecFilingShape,
  SecEvent8KShape,
  XbrlFactsSnapshotShape,
  NumericAuditShape,
  NumericAuditFinding,
  NumericAuditSeverity,
  NumericAuditStatus,
} from './types'

export { ChapterAuditBanner } from './ChapterAuditBanner'
