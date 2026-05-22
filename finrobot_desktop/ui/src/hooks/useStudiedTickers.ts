// useStudiedTickers — pulls /api/artifacts/studied-tickers for the
// landing "我研究过的所有股票" table.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'

export interface StudiedTicker {
  ticker: string
  run_count: number
  latest_created_at: string
  latest_type: string
  latest_artifact_id: string
  latest_target_price: number | null
  latest_entry_price: number | null
  latest_signal: 'hit' | 'watching' | 'failed' | null
  types: string[]
}

export interface StudiedTickersResponse {
  items: StudiedTicker[]
  generated_at: string
}

export function useStudiedTickers(limit = 100) {
  return useQuery<StudiedTickersResponse>({
    queryKey: ['studied-tickers', limit],
    queryFn: async ({ signal }) => {
      const r = await fetch(
        `${BASE_URL}/api/artifacts/studied-tickers?limit=${limit}`,
        { signal },
      )
      if (!r.ok) throw new Error(`studied-tickers HTTP ${r.status}`)
      return r.json() as Promise<StudiedTickersResponse>
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
