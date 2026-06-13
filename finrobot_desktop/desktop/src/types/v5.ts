// v5 frontend types, in a dedicated file separate from
// `hooks/useTickerData.ts` (which carries the ArtifactSummary shape used by
// HistoryTab and friends).

// Keep this list in sync with `finrobot.artifact.models.ArtifactType`
// (Literal). Drift between frontend and backend silently breaks type-narrow
// switches in chapter renderers.
export type ArtifactType =
  | 'dcf'
  | 'lbo'
  | 'comps'
  | 'ddm'
  | 'earnings'
  | 'ic_memo'
  | 'equity_research'
  | 'peer_research'
  | 'ad_hoc'

export type Signal = 'hit' | 'watching' | 'failed'

/** Mirror of `finrobot.artifact.models.ArtifactSummary` (PR1 ADR-0001). */
export interface ArtifactSummaryV5 {
  id: string
  ticker: string | null
  cross_tickers: string[]
  type: ArtifactType
  created_at: string
  headline: string
  source: string
  archived: boolean

  // v5 PR1 additions — backend populates from artifact.outputs.structured.
  // Optional + nullable: missing on legacy artifacts (field absent → undefined
  // in JSON) and explicitly null on v5 artifacts whose pipeline has no thesis.
  entry_price?: number | null
  target_price?: number | null
  target_date?: string | null
  /**
   * Realised-vs-target outcome — hit / watching / failed. Lazy-computed by
   * the backend against a fresh quote. DO NOT use as the LLM verdict; that
   * lives in the `verdict` field below.
   */
  signal?: Signal | null
  /**
   * LLM-emitted BUY / HOLD / SELL recommendation from the thesis step.
   * Populated by summary_extractor.extract_verdict. None when the artifact
   * has no thesis (peer_research / ad_hoc) or recommendation is malformed.
   */
  verdict?: string | null
  /**
   * ≤ 60 char shareable conclusion written by the synthesis_agent
   * (narrative slot). Use this on dashboard entry cards
   * instead of `headline` (which is just pipeline.format_summary preview).
   * None for legacy artifacts produced before the narrative bump.
   */
  tagline?: string | null
  /**
   * Data provider that fed this artifact (backend inputs.data_source, mirrored
   * to a summary column at save time — 门四溯源半). null for the backend's
   * "unknown" placeholder and for legacy rows until the projection rebuild
   * backfills them.
   */
  primary_provider?: string | null
}

/** Mirror of sentiment endpoint (PR4b §6.12). */
export interface SentimentSnapshot {
  ticker: string
  days: number
  available: boolean
  // Why `available` is false, so the UI never mislabels a transient hiccup as a
  // missing key: 'unconfigured' → show the "add Adanos key" CTA; 'provider_error'
  // → key IS set but the call failed, show a retry (not the config CTA); null →
  // available (or success). Optional for back-compat with older payloads.
  reason?: 'unconfigured' | 'provider_error' | null
  coverage: string | null
  bullish_pct: number | null
  bearish_pct: number | null
  average_buzz: number | null
  // Backend AlignmentToken Literal — cross-platform agreement only; direction
  // lives in bullish_pct/bearish_pct.
  source_alignment: 'aligned' | 'partial_divergence' | 'split' | 'single_source' | 'no_data' | null
  sources: {
    platform: string
    has_data: boolean
    bullish_pct: number | null
    activity_label: string
    activity_value: number | null
  }[]
  warnings: string[]
}
