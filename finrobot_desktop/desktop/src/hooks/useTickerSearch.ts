// Debounced, race-safe ticker autocomplete. Returns suggestions for the current
// query string; the caller owns open/active state. The debounce keeps keystrokes
// from fanning out a request each, and the monotonic request id drops any stale
// in-flight response so a slow older query can never overwrite a newer result.

import { useEffect, useRef, useState } from 'react'
import { searchSymbols, type SymbolSuggestion } from '../api/search'

export const TICKER_SEARCH_DEBOUNCE_MS = 180

export function useTickerSearch(query: string): SymbolSuggestion[] {
  const [results, setResults] = useState<SymbolSuggestion[]>([])
  const latestRequest = useRef(0)

  useEffect(() => {
    const q = query.trim()
    if (!q) {
      latestRequest.current += 1 // invalidate any in-flight response
      setResults([])
      return
    }
    const requestId = ++latestRequest.current
    const timer = setTimeout(() => {
      void searchSymbols(q).then((hits) => {
        if (requestId === latestRequest.current) setResults(hits)
      })
    }, TICKER_SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query])

  return results
}
