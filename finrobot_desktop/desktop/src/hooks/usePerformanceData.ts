import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'

export function usePerformanceData(peerTickers: string[]) {
  const ticker = useAppStore((s) => s.ticker)
  const setPerformanceData = useAppStore((s) => s.setPerformanceData)
  const setPerformanceLoading = useAppStore((s) => s.setPerformanceLoading)

  const allTickers = ticker ? [ticker, ...peerTickers].join(',') : ''

  const { data, isLoading } = useQuery({
    queryKey: ['performance', allTickers],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/performance?tickers=${allTickers}&benchmark=SPY&period=1y`)
      if (!resp.ok) return null
      return resp.json()
    },
    enabled: !!ticker,
  })

  useEffect(() => { setPerformanceLoading(isLoading) }, [isLoading, setPerformanceLoading])
  useEffect(() => { if (data) setPerformanceData(data) }, [data, setPerformanceData])

  return { data, isLoading }
}
