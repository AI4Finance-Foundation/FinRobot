import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'
import { extractErrorDetail } from '../api/errors'

export function usePerformanceData(peerTickers: string[]) {
  const ticker = useAppStore((s) => s.ticker)
  const setPerformanceData = useAppStore((s) => s.setPerformanceData)
  const setPerformanceLoading = useAppStore((s) => s.setPerformanceLoading)

  const allTickers = ticker ? [ticker, ...peerTickers].join(',') : ''

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['performance', allTickers],
    queryFn: async () => {
      const resp = await fetch(
        `${BASE_URL}/api/data/performance?tickers=${allTickers}&benchmark=SPY&period=1y`,
      )
      if (!resp.ok) {
        throw new Error(await extractErrorDetail(resp, '无法加载相对走势数据'))
      }
      return resp.json()
    },
    enabled: !!ticker,
    // Relative-perf comparison against SPY over 1y; daily refresh is plenty.
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
    refetchOnMount: false,
  })

  useEffect(() => {
    setPerformanceLoading(isLoading)
  }, [isLoading, setPerformanceLoading])
  useEffect(() => {
    if (data) setPerformanceData(data)
  }, [data, setPerformanceData])

  return { data, isLoading, isError, error }
}
