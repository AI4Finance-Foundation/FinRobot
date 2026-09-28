import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 min (aligned with backend cache)
      retry: 1,
      refetchOnWindowFocus: false, // local app, not needed
    },
  },
})
