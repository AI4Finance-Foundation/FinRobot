// v5 artifact hooks — read the v5-shaped /api/artifacts endpoints so the
// new section components don't have to depend on the legacy ArtifactSummary
// type in useTickerData.ts.

import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { extractErrorDetail } from '../api/errors'
import { fetchWithTimeout, HEAVY_API_TIMEOUT_MS } from '../api/fetch'
import { FetchHttpError } from '../utils/errorMessage'
import type { ArtifactSummaryV5 } from '../types/v5'

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetchWithTimeout(url, { signal }, HEAVY_API_TIMEOUT_MS)
  if (!resp.ok) {
    // Read the backend's user-facing `detail` once and carry it in the typed
    // error so consumers (AIZone) can surface the real reason (BUG-053 pattern).
    throw new FetchHttpError(resp.status, resp.statusText, await extractErrorDetail(resp, ''))
  }
  return (await resp.json()) as T
}

/** Timeline of v5 ArtifactSummary entries for one ticker.
 *
 * `limit` maps to the endpoint's `?limit=` (backend default 50). Pass it
 * explicitly where the surface claims "full history" (Coverage Inspector) so a
 * heavily-run ticker isn't silently truncated at 50 while the card reports a
 * higher artifact_count — match the coverage service's own 200 ceiling. The
 * limit is part of the query key so different callers don't share a cache.
 *
 * `includeSignals` toggles the per-row hit/watching/failed lamp. Computing it
 * costs a LIVE quote per ticker (the backend fetches it synchronously before
 * returning), which bolts market-data latency onto what is otherwise a fast
 * local-DB read. Surfaces that don't render the lamp (the workspace
 * report-history preview) pass false so the history paints instantly; surfaces
 * that do (the report detail page's version rail) keep the default. It is part
 * of the query key so the with/without-lamp variants don't share a cache. */
export function useV5ArtifactTimeline(ticker: string, limit?: number, includeSignals = true) {
  return useQuery<ArtifactSummaryV5[], Error>({
    queryKey: ['v5-artifacts-timeline', ticker, limit ?? null, includeSignals],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams()
      if (limit != null) params.set('limit', String(limit))
      // Backend defaults include_signals=true; only send it when opting out so
      // existing URLs stay unchanged.
      if (!includeSignals) params.set('include_signals', 'false')
      const qs = params.toString()
      return getJson<ArtifactSummaryV5[]>(
        `${BASE_URL}/api/artifacts/by-ticker/${ticker}/timeline${qs ? `?${qs}` : ''}`,
        signal,
      )
    },
    enabled: !!ticker,
    staleTime: 60_000,
    refetchOnMount: false,
  })
}

/** Latest artifact for a ticker filtered by type — convenience derivative.
 *
 * `limit` is forwarded to useV5ArtifactTimeline so a caller that also renders
 * the timeline can pass the SAME limit and share one query/request — two
 * different limits on one surface meant two HTTP fetches with two truncation
 * calibers for the same ticker (the AIZone 50-vs-200 split). */
export function useLatestArtifact(
  ticker: string,
  type: ArtifactSummaryV5['type'],
  limit?: number,
  includeSignals = true,
) {
  const query = useV5ArtifactTimeline(ticker, limit, includeSignals)
  const latest = query.data?.find((a) => a.type === type) ?? null
  return { ...query, latest }
}

/** Full artifact (inputs / assumptions / outputs / meta) for a single id.
 *
 * Backed by `GET /api/artifacts/{id}` (defined in routes/artifacts.py). The
 * timeline endpoint only returns ArtifactSummary which strips heavy fields —
 * sections that need outputs.structured.* (risk grid, peer table, sensitivity
 * heatmap) must use this hook. Cached aggressively because artifacts are
 * immutable once written. */
export interface ArtifactDetail {
  id: string
  ticker: string | null
  type: string
  created_at: string
  // The outputs blob is intentionally unknown — each pipeline writes its own
  // structured shape; section components down-cast to the contract they care
  // about. Keeping it `unknown` here forces every consumer to define their
  // own narrow type and avoids accidental field drift across sections.
  outputs: Record<string, unknown>
  inputs: Record<string, unknown>
  assumptions: Record<string, unknown>
  meta: Record<string, unknown>
}

export function useArtifactDetail(artifactId: string | null | undefined) {
  return useQuery<ArtifactDetail, Error>({
    queryKey: ['artifact-detail', artifactId],
    queryFn: ({ signal }) =>
      getJson<ArtifactDetail>(`${BASE_URL}/api/artifacts/${artifactId}`, signal),
    enabled: !!artifactId,
    staleTime: Infinity, // artifacts are immutable once written
    refetchOnMount: false,
    // Switching versions in the report's left-rail VERSIONS tab changes the
    // artifactId (this query key). Without keepPreviousData the next version's
    // fetch flips the hook to pending/undefined, the detail page falls back to
    // its full-screen loader, and ReportLeftRail unmounts — throwing the reader
    // off the VERSIONS tab back to CONTENTS/chapter-1. Keeping the previous
    // artifact rendered until the new one resolves makes a switch a pure
    // content swap with the navigation flank untouched.
    placeholderData: keepPreviousData,
    retry: 1,
  })
}
