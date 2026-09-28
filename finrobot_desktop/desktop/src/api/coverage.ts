// Coverage Desk API — typed request functions for /api/coverage/*. Hand-written
// interfaces (not generated schema.d.ts) mirror the backend Pydantic models,
// matching the established inline-type pattern for endpoints newer than the last
// `npm run generate:api` (see VersionDiffBanner).

import { BASE_URL } from './client'
import { fetchWithTimeout } from './fetch'
import { FetchHttpError } from '../utils/errorMessage'
import { extractErrorDetail } from './errors'
import type { NumberSource } from '../components/SourcedNumber'

// ── Types (mirror finrobot/coverage/models.py) ───────────────────────────────

export interface CoverageMember {
  ticker: string
  added_at: string
  note: string | null
  priority: number
}

export interface CoverageGroup {
  id: string
  name: string
  description: string | null
  is_system: boolean
  created_at: string
  updated_at: string
}

export interface CoverageGroupSummary extends CoverageGroup {
  member_count: number
}

export interface CoverageGroupDetail extends CoverageGroup {
  members: CoverageMember[]
}

export interface NeedsRefreshReason {
  kind: string
  detail: string
  artifact_id: string | null
}

export type SignalStatus = 'hit' | 'watching' | 'failed'
export type RunStatus = 'created' | 'running' | 'completed' | 'failed'

// What the LIVE price implies, re-solved from the ticker's latest stored DCF
// (mirrors MarketImpliedNature in finrobot/engine/models/financial.py). A
// per-name classification, NOT a cross-name implied-growth ranking — the reverse
// solver fits a flat constant while the forward DCF decays, so a cross-name gap
// would rank growth-curve steepness, not expectation stretch.
export type MarketImpliedKind = 'fundamental' | 'option_value' | 'near_ceiling'

export interface MarketImpliedNature {
  kind: MarketImpliedKind
  // Constant annual revenue growth the live price implies (fundamental only).
  implied_growth: number | null
  implied_wacc: number | null
  horizon_years: number
  // Ceiling context for the unreachable paths (option_value / near_ceiling).
  growth_ceiling: number | null
  ceiling_price: number | null
}

// Per-cell provenance for the numeric columns (mirrors CoverageRowSources in
// finrobot/coverage/models.py). Each slot feeds a <SourcedNumber> popover; a
// null slot (degraded fetch) renders the bare value.
export interface CoverageRowSources {
  price: NumberSource | null
  change_pct_1d: NumberSource | null
  market_cap: NumberSource | null
  revenue_ttm: NumberSource | null
  ev_ebitda: NumberSource | null
  pe: NumberSource | null
  upside_to_target_live: NumberSource | null
  market_implied: NumberSource | null
}

export interface CoverageRow {
  ticker: string
  company: string | null
  price: number | null
  change_pct_1d: number | null
  price_as_of: string | null
  // Whether `price` is a live intraday quote, a session close (weekend / after-
  // hours / holiday), or undeterminable — classified server-side at read time
  // against the exchange clock. Drives the card's freshness affordance: a closed
  // market shows a static "Close · date", never a "refreshing"/live pulse.
  session_state: 'live' | 'closed' | 'unknown' | null
  market_cap: number | null
  revenue_ttm: number | null
  ev_ebitda: number | null
  pe: number | null
  currency: string | null
  latest_verdict: string | null
  target_price: number | null
  target_date: string | null
  entry_price: number | null
  upside_to_target_live: number | null
  signal: SignalStatus | null
  // artifact_count = every artifact for the ticker (research + dcf/lbo/comps/…);
  // research_count = only thesis-bearing research (verdict set). The card labels
  // "研报" off research_count so a model run never inflates the report tally.
  artifact_count: number
  research_count: number
  latest_artifact_id: string | null
  latest_type: string | null
  latest_at: string | null
  run_status: RunStatus | null
  run_error: string | null
  // What the live price implies vs the name's stored DCF — null when the ticker
  // has no DCF, no live price, or on the cache-only first paint.
  market_implied: MarketImpliedNature | null
  // The market cells came from a cache snapshot past its freshness TTL — real
  // last-known numbers (rendered with their price_as_of age), NOT pending. The
  // card shows them with a "refreshing" affordance, never a blank shimmer; a
  // background revalidate (refresh=true) replaces them. false = fresh, or a cold
  // row whose market is genuinely absent (price null → shimmer).
  market_stale: boolean
  needs_refresh: NeedsRefreshReason[]
  warnings: string[]
  sources: CoverageRowSources
}

export interface CoverageOverview {
  group_id: string
  group_name: string
  rows: CoverageRow[]
  generated_at: string
  partial: boolean
  // True when assembled from the canonical cache with NO network (the instant
  // first paint). Market cells are last-known snapshots; per-row market_stale
  // flags the ones past TTL. The client revalidates via a refresh=true pass.
  cache_only: boolean
  // True when a network refresh made ZERO price provider calls because every
  // row's market is closed and already at its latest settled close (the calendar
  // no-op). Lets the refresh button confirm "已是最新收盘" instead of implying it
  // pulled live quotes. Always false on the cache-only paint.
  refresh_noop: boolean
}

// ── Requests ─────────────────────────────────────────────────────────────────

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetchWithTimeout(`${BASE_URL}${path}`, init)
  if (!r.ok) {
    // FastAPI ships a 中文 user-facing `detail` on coverage errors (422 ticker
    // 非法 / 已在组内 / 分组名重复, 502 provider 失败, 503 能力未配置). statusText
    // is empty/English under HTTP/2 — read the body once and carry detail into
    // the typed error so mapErrorToUserMessage surfaces the real reason instead
    // of a generic "添加失败" (BUG-053).
    const detail = await extractErrorDetail(r, '')
    throw new FetchHttpError(r.status, r.statusText, detail)
  }
  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const coverageApi = {
  listGroups: () => req<CoverageGroupSummary[]>('/api/coverage/groups'),

  // Auto-add: enrol an opened ticker into the default Studied Tickers workspace
  // (find-or-create, idempotent). The write side of "opening /stocks/:ticker
  // enrols it"; surfaced UI does not expose manual group membership edits.
  addStudiedTicker: (ticker: string) =>
    req<CoverageGroupDetail>('/api/coverage/studied-tickers/members', jsonInit('POST', { ticker })),

  // refresh=false → instant cache-only paint (server reads canonical cache,
  // allow-stale, no network). refresh=true → bounded network revalidate.
  overview: (id: string, refresh = false) => {
    const suffix = refresh ? '?refresh=true' : ''
    return req<CoverageOverview>(`/api/coverage/groups/${id}/overview${suffix}`)
  },
}
