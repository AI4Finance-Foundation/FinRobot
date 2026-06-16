// Ticker autocomplete client. Hits GET /api/search/symbols (local SEC symbol
// index, in-memory on the backend) through fetchWithTimeout so the capability
// token is injected. Never throws: a timeout / network error / non-200 degrades
// to an empty list so the homepage search box keeps working without suggestions.

import { fetchWithTimeout } from './fetch'
import { BASE_URL } from './client'

export interface SymbolSuggestion {
  symbol: string
  name: string
}

const SEARCH_LIMIT = 8

export async function searchSymbols(query: string): Promise<SymbolSuggestion[]> {
  const q = query.trim()
  if (!q) return []
  const url = `${BASE_URL}/api/search/symbols?q=${encodeURIComponent(q)}&limit=${SEARCH_LIMIT}`
  try {
    const resp = await fetchWithTimeout(url)
    if (!resp.ok) return []
    const data = (await resp.json()) as { results?: SymbolSuggestion[] }
    return Array.isArray(data.results) ? data.results : []
  } catch {
    return [] // degrade silently — suggestions are an enhancement, never a blocker
  }
}
