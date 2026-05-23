import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'
import { extractErrorDetail } from '../api/errors'

export function useCatalysts() {
  const ticker = useAppStore((s) => s.ticker)
  const setCatalysts = useAppStore((s) => s.setCatalysts)
  const setCatalystsLoading = useAppStore((s) => s.setCatalystsLoading)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['catalysts', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/catalysts`)
      if (!resp.ok) {
        throw new Error(await extractErrorDetail(resp, '无法加载催化剂事件'))
      }
      return resp.json()
    },
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000, // 5 minutes — news doesn't change that fast
    refetchOnMount: false,
    // Catalysts depend on LLM availability; don't hammer the backend on transient failures.
    retry: 1,
  })

  useEffect(() => {
    setCatalystsLoading(isLoading)
  }, [isLoading, setCatalystsLoading])
  // Only mirror real data into the store to avoid tab-switch null flashes.
  useEffect(() => {
    if (data) setCatalysts(data)
  }, [data, setCatalysts])

  return { data, isLoading, isError, error }
}
