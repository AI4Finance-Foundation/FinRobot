// Coverage Desk API — typed request functions for /api/coverage/* and
// /api/compare. Hand-written interfaces (not generated schema.d.ts) mirror the
// backend Pydantic models, matching the established inline-type pattern for
// endpoints newer than the last `npm run generate:api` (see VersionDiffBanner).

import { BASE_URL } from './client'
import { fetchWithTimeout } from './fetch'
import { FetchHttpError } from '../utils/errorMessage'

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
  run_count: number
  latest_artifact_id: string | null
  latest_type: string | null
  latest_at: string | null
  run_status: RunStatus | null
  run_error: string | null
  needs_refresh: NeedsRefreshReason[]
  warnings: string[]
}

export interface CoverageOverview {
  group_id: string
  group_name: string
  rows: CoverageRow[]
  generated_at: string
  partial: boolean
}

export interface BatchRunItem {
  ticker: string
  run_id: string
}

export interface BatchRunResponse {
  group_id: string
  pipeline_type: string
  runs: BatchRunItem[]
  skipped: { ticker: string; reason: string }[]
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
  if (!r.ok) throw new FetchHttpError(r.status, r.statusText)
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

  createGroup: (name: string, description?: string) =>
    req<CoverageGroupDetail>('/api/coverage/groups', jsonInit('POST', { name, description })),

  getGroup: (id: string) => req<CoverageGroupDetail>(`/api/coverage/groups/${id}`),

  updateGroup: (id: string, patch: { name?: string; description?: string }) =>
    req<CoverageGroupDetail>(`/api/coverage/groups/${id}`, jsonInit('PATCH', patch)),

  deleteGroup: (id: string) => req<void>(`/api/coverage/groups/${id}`, { method: 'DELETE' }),

  addMembers: (id: string, tickers: string[], note?: string) =>
    req<CoverageGroupDetail>(
      `/api/coverage/groups/${id}/members`,
      jsonInit('POST', { tickers, note }),
    ),

  removeMember: (id: string, ticker: string) =>
    req<CoverageGroupDetail>(`/api/coverage/groups/${id}/members/${encodeURIComponent(ticker)}`, {
      method: 'DELETE',
    }),

  overview: (id: string, refresh = false) =>
    req<CoverageOverview>(`/api/coverage/groups/${id}/overview${refresh ? '?refresh=true' : ''}`),

  batchRun: (id: string, tickers: string[], pipelineType = 'equity_research', language?: string) =>
    req<BatchRunResponse>(
      `/api/coverage/groups/${id}/runs`,
      jsonInit('POST', { tickers, pipeline_type: pipelineType, language }),
    ),

  compare: (tickers: string[]) =>
    req<ComparisonResult>(`/api/compare?tickers=${encodeURIComponent(tickers.join(','))}`),
}
