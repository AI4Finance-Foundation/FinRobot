// useHealth — derives the global StatusBar's connection/health state from the
// backend's real signals, so the footer stops lying about being "已连接".
//
// Two independent signals are combined:
//   GET /api/health/quotes-warmed → { warmed, studied_ticker_count }
//       Reachability probe + whether the lifespan QuoteCache warmup finished.
//       A failed fetch here = backend unreachable (offline).
//   GET /api/settings → { available_providers, startup_error, ... }
//       Honest list of the data providers the backend ACTUALLY has configured
//       (e.g. "fmp" only appears if the FMP key is set), plus a boot-time
//       config error if validate_runtime_config() failed.
//
// Failure is graceful: a thrown fetch never blanks the bar — the hook resolves
// to an `offline`/`degraded` status object instead. react-query `retry: false`
// keeps a wedged backend from spamming the network; the refetch interval picks
// state back up once the server returns.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'

export type HealthLevel = 'connected' | 'degraded' | 'offline'

export interface HealthState {
  level: HealthLevel
  /** True only when the reachability probe succeeded. */
  backendReachable: boolean
  /** Lifespan QuoteCache warmup finished (or had nothing to warm). */
  quotesWarmed: boolean
  /** Provider ids the backend reports as actually configured, e.g.
   *  ["fmp", "yfinance", "sec_edgar", ...]. Empty when unknown/offline. */
  availableProviders: string[]
  /** Boot-time config error surfaced by /api/settings, if any. */
  startupError: string | null
}

interface QuotesWarmedShape {
  warmed: boolean
  studied_ticker_count: number
}

interface SettingsHealthShape {
  available_providers: string[]
  startup_error: string | null
}

const OFFLINE: HealthState = {
  level: 'offline',
  backendReachable: false,
  quotesWarmed: false,
  availableProviders: [],
  startupError: null,
}

export function useHealth() {
  return useQuery<HealthState>({
    queryKey: ['health'],
    queryFn: async ({ signal }): Promise<HealthState> => {
      // 1) Reachability + warmup. If this throws/!ok the backend is offline.
      let warmed: QuotesWarmedShape
      try {
        const r = await fetchWithTimeout(`${BASE_URL}/api/health/quotes-warmed`, { signal })
        if (!r.ok) return OFFLINE
        warmed = (await r.json()) as QuotesWarmedShape
      } catch {
        return OFFLINE
      }

      // 2) Honest provider/config snapshot. Backend is already reachable, so a
      //    failure here is a soft-miss — keep the connection green but report
      //    no specific providers rather than guessing.
      let providers: string[] = []
      let startupError: string | null = null
      try {
        const r = await fetchWithTimeout(`${BASE_URL}/api/settings`, { signal })
        if (r.ok) {
          const s = (await r.json()) as SettingsHealthShape
          providers = Array.isArray(s.available_providers) ? s.available_providers : []
          startupError = s.startup_error ?? null
        }
      } catch {
        // ignore — reachability already established
      }

      const quotesWarmed = Boolean(warmed.warmed)
      // Degraded: reachable but the backend isn't fully serving data — either a
      // boot-time config error, or quotes haven't warmed yet, or no data
      // providers are configured at all.
      const degraded = startupError != null || !quotesWarmed || providers.length === 0

      return {
        level: degraded ? 'degraded' : 'connected',
        backendReachable: true,
        quotesWarmed,
        availableProviders: providers,
        startupError,
      }
    },
    // Eagerly retry from a cold/offline state, then settle into a calm poll.
    staleTime: 15_000,
    refetchInterval: 15_000,
    retry: false,
    placeholderData: OFFLINE,
  })
}
