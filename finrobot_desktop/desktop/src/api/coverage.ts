// Coverage Desk API — typed request functions for /api/coverage/* and
// /api/compare. Hand-written interfaces (not generated schema.d.ts) mirror the
// backend Pydantic models, matching the established inline-type pattern for
// endpoints newer than the last `npm run generate:api` (see VersionDiffBanner).

import { BASE_URL } from './client'
import { fetchWithTimeout } from './fetch'
import { FetchHttpError } from '../utils/errorMessage'
import { extractErrorDetail } from './errors'
import type { NumberSource } from '../components/SourcedNumber'

// ── Types (mirror finrobot/coverage/models.py + compute/compare.py) ──────────

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
}

export interface CoverageRow {
  ticker: string
  company: string | null
  price: number | null
  change_pct_1d: number | null
  price_as_of: string | null
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
}

export interface CompanyValuation {
  ticker: string
  company_name: string
  current_price: number | null
  implied_price: number | null
  upside_pct: number | null
  wacc: number | null
  terminal_growth: number | null
  ev_ebitda: number | null
  pe_ratio: number | null
  // Vintage/provenance of the DCF this row's implied_price + WACC came from.
  // current_price is live, but these numbers are only as fresh as dcf_as_of —
  // a comparison can mix today's run with a weeks-old stored artifact, so the
  // table discloses each row's date. null = computed live (no stored artifact).
  dcf_as_of: string | null
  dcf_artifact_id: string | null
  warnings: string[]
  error: string | null
}

export interface ComparisonResult {
  companies: CompanyValuation[]
  generated_at: string
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

  compare: (tickers: string[]) =>
    req<ComparisonResult>(`/api/compare?tickers=${encodeURIComponent(tickers.join(','))}`),
}
