import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'

export function useCatalysts() {
  const ticker = useAppStore((s) => s.ticker)
  const setCatalysts = useAppStore((s) => s.setCatalysts)
  const setCatalystsLoading = useAppStore((s) => s.setCatalystsLoading)

  const { data, isLoading } = useQuery({
    queryKey: ['catalysts', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/catalysts`)
      if (!resp.ok) return null
      return resp.json()
    },
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000, // 5 minutes — news doesn't change that fast
  })

  useEffect(() => { setCatalystsLoading(isLoading) }, [isLoading, setCatalystsLoading])
  useEffect(() => { setCatalysts(data ?? null) }, [data, setCatalysts])

  return { data, isLoading }
}
