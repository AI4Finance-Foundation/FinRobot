// The read models the exported <ReportChapters> render from. The standalone
// HTML export is supposed to be deterministic — same artifact ⇒ same file. The
// valuation/price/beta surfaces AND the multi-year financial-trend charts are
// now FROZEN (rendered from the artifact's persisted valuation_synthesis +
// raw_data.market snapshot + structured.historical_metrics, no live hooks), so
// they need no prefetch. What remains is the one chapter that still pulls
// slow-changing reference data live at render time:
//   - ChapterFinancialData → ['earnings-calls', ticker]
// In the offline viewer that hook resolves PURELY from the dehydrated cache
// (refetch disabled). So whatever isn't in the live cache at export time is
// silently missing from the file — its completeness ends up depending on scroll
// position / request timing, not the artifact (BUG-20260602-028).
//
// This module is the single list of {queryKey, queryFn} to seed the cache with
// BEFORE dehydrate, so the snapshot is always complete. The queryKey + URL of
// each entry MIRRORS the chapter hook it backs (kept in sync deliberately); the
// fetch primitive (fetchWithTimeout) is reused, not re-implemented.

import type { QueryClient } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout, HEAVY_API_TIMEOUT_MS } from '../api/fetch'

export type ReportExportBlockId = 'earnings'

export interface ReportExportQuery {
  /** Stable id for failure reporting (which block could not be prefetched). */
  id: ReportExportBlockId
  queryKey: readonly unknown[]
  queryFn: () => Promise<unknown>
}

async function fetchHeavyJson(url: string): Promise<unknown> {
  const resp = await fetchWithTimeout(url, {}, HEAVY_API_TIMEOUT_MS)
  if (!resp.ok) throw new Error(`${resp.status}`)
  return resp.json()
}

/**
 * Every server read model the report chapters consume, for a given ticker.
 * Keys + fetchers mirror the chapter hooks so the dehydrated cache resolves
 * them identically in the offline viewer.
 */
export function reportExportQueries(ticker: string): ReportExportQuery[] {
  return [
    {
      // ChapterFinancialData — EarningsCallSection (limit=8 must match the hook)
      id: 'earnings',
      queryKey: ['earnings-calls', ticker],
      queryFn: () => fetchHeavyJson(`${BASE_URL}/api/data/${ticker}/earnings-calls?limit=8`),
    },
  ]
}

/**
 * Seed the query cache with EVERY read model the report chapters render from,
 * so the dehydrated snapshot in the exported file is complete regardless of
 * what the user had scrolled into view at click time (BUG-20260602-028).
 *
 * Uses `ensureQueryData` with the chapters' exact queryKey + a mirrored fetcher,
 * so the offline viewer resolves the same keys with refetch disabled. Each query
 * is awaited independently; a failed block does NOT abort the export — its id is
 * returned so the caller can warn precisely which section will be missing,
 * instead of silently dropping it.
 *
 * @returns the ids of the read models that could not be prefetched (empty = all
 *   present). The cache is mutated in place; build the HTML AFTER this resolves.
 */
export async function prepareReportExport(
  queryClient: QueryClient,
  ticker: string,
): Promise<ReportExportBlockId[]> {
  const queries = reportExportQueries(ticker)
  const results = await Promise.allSettled(
    queries.map((q) =>
      queryClient.ensureQueryData({
        queryKey: q.queryKey,
        queryFn: q.queryFn,
        // Treat a just-fetched value as fresh so ensureQueryData reuses an
        // already-cached entry instead of re-hitting the network on export.
        staleTime: 5 * 60_000,
      }),
    ),
  )
  return queries.filter((_, i) => results[i].status === 'rejected').map((q) => q.id)
}

const BLOCK_LABELS: Record<ReportExportBlockId, { zh: string; en: string }> = {
  earnings: { zh: '财报电话会逐字稿', en: 'earnings call transcripts' },
}

/** Human-readable "these blocks couldn't be prefetched" line for the export toast. */
export function missingExportBlocksMessage(
  missing: ReportExportBlockId[],
  locale: 'zh' | 'en',
): string {
  const names = missing.map((id) => BLOCK_LABELS[id][locale])
  return locale === 'zh' ? `缺失：${names.join('、')}` : `Missing: ${names.join(', ')}`
}
