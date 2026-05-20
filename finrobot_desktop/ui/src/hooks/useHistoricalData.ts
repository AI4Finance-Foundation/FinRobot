import { useEffect } from 'react'
import { useAppStore } from '../stores/appStore'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'

export function useHistoricalData() {
  const ticker = useAppStore((s) => s.ticker)
  const setHistoricalMetrics = useAppStore((s) => s.setHistoricalMetrics)
  const setHistoricalLoading = useAppStore((s) => s.setHistoricalLoading)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['historical', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/historical`)
      if (!resp.ok) {
        const detail = await resp.text().catch(() => '')
        throw new Error(`historical ${resp.status}: ${detail || resp.statusText}`)
      }
      return resp.json()
    },
    enabled: !!ticker,
    // Historical financials change once per quarter at most — keep a long cache.
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
  })

  useEffect(() => { setHistoricalLoading(isLoading) }, [isLoading, setHistoricalLoading])
  useEffect(() => { setHistoricalMetrics(data ?? null) }, [data, setHistoricalMetrics])

  return { data, isLoading, isError, error }
}

export function useQuarterlyData() {
  const ticker = useAppStore((s) => s.ticker)
  const setQuarterlyData = useAppStore((s) => s.setQuarterlyData)
  const setQuarterlyLoading = useAppStore((s) => s.setQuarterlyLoading)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['quarterly', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/quarterly`)
      if (!resp.ok) {
        const detail = await resp.text().catch(() => '')
        throw new Error(`quarterly ${resp.status}: ${detail || resp.statusText}`)
      }
      return resp.json()
    },
    enabled: !!ticker,
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
  })

  useEffect(() => { setQuarterlyLoading(isLoading) }, [isLoading, setQuarterlyLoading])
  useEffect(() => { setQuarterlyData(data ?? null) }, [data, setQuarterlyData])

  return { data, isLoading, isError, error }
}
