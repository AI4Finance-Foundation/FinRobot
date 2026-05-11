import { useEffect } from 'react'
import { useAppStore } from '../stores/appStore'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'

export function useHistoricalData() {
  const ticker = useAppStore((s) => s.ticker)
  const setHistoricalMetrics = useAppStore((s) => s.setHistoricalMetrics)
  const setHistoricalLoading = useAppStore((s) => s.setHistoricalLoading)

  const { data, isLoading } = useQuery({
    queryKey: ['historical', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/historical`)
      if (!resp.ok) return null
      return resp.json()
    },
    enabled: !!ticker,
  })

  useEffect(() => { setHistoricalLoading(isLoading) }, [isLoading, setHistoricalLoading])
  useEffect(() => { if (data) setHistoricalMetrics(data) }, [data, setHistoricalMetrics])

  return { data, isLoading }
}

export function useQuarterlyData() {
  const ticker = useAppStore((s) => s.ticker)
  const setQuarterlyData = useAppStore((s) => s.setQuarterlyData)
  const setQuarterlyLoading = useAppStore((s) => s.setQuarterlyLoading)

  const { data, isLoading } = useQuery({
    queryKey: ['quarterly', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/quarterly`)
      if (!resp.ok) return null
      return resp.json()
    },
    enabled: !!ticker,
  })

  useEffect(() => { setQuarterlyLoading(isLoading) }, [isLoading, setQuarterlyLoading])
  useEffect(() => { if (data) setQuarterlyData(data) }, [data, setQuarterlyData])

  return { data, isLoading }
}
