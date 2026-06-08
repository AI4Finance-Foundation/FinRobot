// Shared derivation: turn a raw artifact + version timeline into the typed
// shapes the 13 chapters consume. Extracted from ArtifactDetailPage so the
// in-app report (ArtifactDetailPage) and the standalone HTML export (the viewer
// bundle in src/export/) derive chapter data identically — one source of truth.

import type { ArtifactDetail } from '../../hooks/useV5Artifacts'
import type { ArtifactSummaryV5 } from '../../types/v5'
import type {
  ArtifactStructured,
  CatalystAnalysisShape,
  DcfShape,
  NumericAuditShape,
  OwnershipGovernanceShape,
  PeerCompsShape,
  TechnicalAnalysisShape,
  ThesisShape,
  ValuationSynthesisShape,
} from './chapters'
import { formatDate } from '../../utils/format'
import type { Locale } from '../../i18n'

interface ArtifactInputs {
  data_source?: string
  data_fetched_at?: string
  raw_data?: Record<string, unknown>
}

interface ArtifactComputeVersion {
  version?: string
  git_commit?: string
  formula_id?: string
  formula_warnings?: string[]
}

interface ArtifactOutputs {
  structured?: ArtifactStructured
  summary_text?: string
  warnings?: string[]
}

interface ArtifactMeta {
  created_at?: string
  source?: string
  user_id?: string
  // Language the report's prose was generated in; body renders in this language
  // regardless of UI locale. Legacy artifacts default to 'zh'.
  language?: 'en' | 'zh'
}

export interface DerivedReportData {
  symbol: string
  inputs: ArtifactInputs
  outputs: ArtifactOutputs
  meta: ArtifactMeta
  compute_version?: ArtifactComputeVersion
  thesis: ThesisShape | null
  dcf: DcfShape | null
  peers: PeerCompsShape | null
  // Frozen football-field data (per-method ranges + the snapshot price the whole
  // report is anchored to). Persisted at generation; the report renders this
  // instead of re-fetching /api/valuation/aggregate live, so the football field
  // can never contradict the cover/narrative price (the BUG this freezing fixes).
  valuationSynthesis: ValuationSynthesisShape | null
  catalysts: CatalystAnalysisShape | null
  technical: TechnicalAnalysisShape | null
  ownership: OwnershipGovernanceShape | null
  // The single canonical SNAPSHOT quote every report surface uses (football
  // field, technical chapter, toolbar). Anchored to valuation_synthesis.current_price
  // (what the target was computed from), falling back to the raw FinancialData
  // dump. NEVER a live refetch — the report is a point-in-time artifact.
  snapshotPrice: number | null
  /** Raw 5Y provider beta at snapshot (distinct from the Blume-adjusted WACC β
   *  in dcf.inputs.beta — the latter shrinks this 2/3·β+1/3·1 toward 1.0). */
  snapshotBeta: number | null
  snapshot52wHigh: number | null
  snapshot52wLow: number | null
  /** When the underlying market data was fetched — the report's "as of" stamp. */
  snapshotAsOf: string | null
  // Numeric-audit gate verdict. null on legacy artifacts (pre-gate) → no banner.
  numericAudit: NumericAuditShape | null
  createdAt: string | null
  computeVersionStr: string | null
  reportLang: 'en' | 'zh'
  totalVersions: number
  versionNumber: number | null
  versionLabel: string
  // Currency tags (BUG-030). quote → per-share & market-cap; reporting → IS/BS
  // absolutes. Default 'USD' so legacy (untagged) artifacts render identically.
  quoteCurrency: string
  reportingCurrency: string
}

export function deriveReportData(
  artifact: ArtifactDetail,
  timeline: ArtifactSummaryV5[],
  locale: Locale,
): DerivedReportData {
  const inputs = artifact.inputs as ArtifactInputs
  const outputs = artifact.outputs as ArtifactOutputs
  const meta = artifact.meta as ArtifactMeta
  const compute_version = (artifact as unknown as { compute_version?: ArtifactComputeVersion })
    .compute_version

  const structured = outputs.structured ?? {}
  const thesis = (structured.thesis as ThesisShape | undefined) ?? null
  const dcf = (structured.financial_modeling as DcfShape | undefined) ?? null
  const peers = (structured.peer_analysis as PeerCompsShape | undefined) ?? null
  const valuationSynthesis =
    (structured.valuation_synthesis as ValuationSynthesisShape | undefined) ?? null
  const catalysts = (structured.catalyst_analysis as CatalystAnalysisShape | undefined) ?? null
  const technical = (structured.technical_analysis as TechnicalAnalysisShape | undefined) ?? null
  const ownership =
    (structured.ownership_governance as OwnershipGovernanceShape | undefined) ?? null
  const numericAudit = (structured.numeric_audit as NumericAuditShape | undefined) ?? null

  // Frozen snapshot quote — the ONE price/beta/52w the whole report renders, so
  // no surface re-fetches live and contradicts the cover. raw_data.market is the
  // FinancialData dump captured at fetch time (summary_extractor.py); the price
  // prefers valuation_synthesis.current_price (the value the target was computed
  // against) and falls back to the market dump.
  const marketSnap = ((inputs.raw_data ?? {}) as Record<string, unknown>)['market']
  const market = (
    typeof marketSnap === 'object' && marketSnap !== null ? marketSnap : {}
  ) as Record<string, unknown>
  const num = (v: unknown): number | null =>
    typeof v === 'number' && Number.isFinite(v) ? v : null
  const snapshotPrice = valuationSynthesis?.current_price ?? num(market['current_price'])
  const snapshotBeta = num(market['beta'])
  const snapshot52wHigh = num(market['price_52w_high'])
  const snapshot52wLow = num(market['price_52w_low'])
  const snapshotAsOf = inputs.data_fetched_at ?? null

  const createdAt = meta.created_at ?? null
  const computeVersionStr = compute_version?.version ?? null
  const reportLang: 'en' | 'zh' = meta.language ?? 'zh'

  // Currency: canonical source is structured.currency (the BUG-030 backend tag);
  // fall back to the raw_data snapshot tags, then USD for legacy artifacts.
  const rawData = (inputs.raw_data ?? {}) as Record<string, unknown>
  const quoteCurrency =
    structured.currency?.quote_currency ??
    (typeof rawData['quote_currency'] === 'string'
      ? (rawData['quote_currency'] as string)
      : null) ??
    'USD'
  const reportingCurrency =
    structured.currency?.reporting_currency ??
    (typeof rawData['reporting_currency'] === 'string'
      ? (rawData['reporting_currency'] as string)
      : null) ??
    'USD'

  // Version number (v1/v2/…) from the timeline (newest→oldest; oldest is v1).
  const sameTypeTimeline = timeline.filter((a) => a.type === artifact.type)
  const totalVersions = sameTypeTimeline.length
  const idxFromEnd = sameTypeTimeline.findIndex((a) => a.id === artifact.id)
  const versionNumber = idxFromEnd === -1 ? null : totalVersions - idxFromEnd
  const versionLabel =
    versionNumber !== null
      ? `v${versionNumber}${createdAt ? ` · ${formatDate(createdAt, locale, 'short')}` : ''}`
      : createdAt
        ? formatDate(createdAt, locale, 'short')
        : artifact.id.slice(0, 12)

  return {
    symbol: (artifact.ticker || '').toUpperCase(),
    inputs,
    outputs,
    meta,
    compute_version,
    thesis,
    dcf,
    peers,
    valuationSynthesis,
    catalysts,
    technical,
    ownership,
    numericAudit,
    snapshotPrice,
    snapshotBeta,
    snapshot52wHigh,
    snapshot52wLow,
    snapshotAsOf,
    createdAt,
    computeVersionStr,
    reportLang,
    totalVersions,
    versionNumber,
    versionLabel,
    quoteCurrency,
    reportingCurrency,
  }
}
