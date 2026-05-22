import { useEffect } from 'react'
import { useAppStore } from '../stores/appStore'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { extractErrorDetail } from '../api/errors'

export function useHistoricalData() {
  const ticker = useAppStore((s) => s.ticker)
  const setHistoricalMetrics = useAppStore((s) => s.setHistoricalMetrics)
  const setHistoricalLoading = useAppStore((s) => s.setHistoricalLoading)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['historical', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/historical`)
      if (!resp.ok) {
        throw new Error(await extractErrorDetail(resp, '无法加载多年财务数据'))
      }
      return resp.json()
    },
    enabled: !!ticker,
    // Historical financials change once per quarter at most — keep a long cache.
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
    // Don't refetch on remount: ticker is the cache key, so cache hits stay
    // hot across tab switches. setTicker() clears appStore on ticker change.
    refetchOnMount: false,
  })

  useEffect(() => { setHistoricalLoading(isLoading) }, [isLoading, setHistoricalLoading])
  // Only mirror real data into the store. Writing null on every mount while
  // react-query is still resolving causes tab-switch flashes — the store
  // briefly goes null even though the cache has data.
  useEffect(() => { if (data) setHistoricalMetrics(data) }, [data, setHistoricalMetrics])

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
        throw new Error(await extractErrorDetail(resp, '无法加载季度财务数据'))
      }
      return resp.json()
    },
    enabled: !!ticker,
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
    refetchOnMount: false,
  })

  useEffect(() => { setQuarterlyLoading(isLoading) }, [isLoading, setQuarterlyLoading])
  useEffect(() => { if (data) setQuarterlyData(data) }, [data, setQuarterlyData])

  return { data, isLoading, isError, error }
}
