import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { extractErrorDetail } from '../api/errors'
import { tSync } from '../i18n'

export function useHistoricalData(ticker: string) {
  return useQuery({
    queryKey: ['historical', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/historical`)
      if (!resp.ok) {
        throw new Error(await extractErrorDetail(resp, tSync('errors.dataLoad.historical')))
      }
      return resp.json()
    },
    enabled: !!ticker,
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
    refetchOnMount: false,
  })
}
