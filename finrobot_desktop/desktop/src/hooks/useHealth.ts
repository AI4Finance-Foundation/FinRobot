// useHealth — derives the backend's connection/health state from its real
// signals (consumed by AIZone to gate the cold/running/hot workspace state).
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
// Failure is graceful: a thrown fetch never throws to the caller — the hook
// resolves to an `offline`/`degraded` status object instead. react-query `retry: false`
// keeps a wedged backend from spamming the network; the refetch interval picks
// state back up once the server returns.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'

export type HealthLevel = 'starting' | 'connected' | 'degraded' | 'offline'

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
  /** True when a usable LLM is selected (model chosen AND keyed). False on a
   *  fresh install — distinct from `startupError` (a chosen-but-broken model).
   *  Drives the first-run onboarding overlay + the AI-CTA preflight. Defaults
   *  to `true` while unknown/offline so we never nag before the real answer. */
  modelConfigured: boolean
  /** Data-provider chain wired by the post-yield warmup. False for the brief
   *  cold-start window only — live-data panels show "starting engine" and the
   *  live-data 503s are pending (retry), not errors. False while offline. */
  engineReady: boolean
  /** LLM agents built. False during cold start — AI surfaces show "starting"
   *  rather than nagging "configure a model". False while offline. */
  agentsReady: boolean
}

interface QuotesWarmedShape {
  warmed: boolean
  studied_ticker_count: number
  // Cold-start readiness (added with the sidecar warmup split). Optional so a
  // pre-split backend (no field) reads as ready — `!== false` below.
  engine_ready?: boolean
  agents_ready?: boolean
}

interface SettingsHealthShape {
  available_providers: string[]
  startup_error: string | null
  model_configured: boolean
}

// WebView module-load time ≈ app launch. The Python sidecar needs a few
// seconds after that before :8321 answers (one-dir PyInstaller boot; the very
// first launch after install can add a one-time Gatekeeper scan).
const BOOT_TIME = Date.now()

// How long an unreachable backend counts as "still starting" instead of dead.
// lib.rs exits the whole app if the sidecar misses its 90 s readiness window,
// so anything still unreachable past this is a genuinely broken backend (or a
// browser-dev session with no `dev.sh` server).
const STARTUP_GRACE_MS = 120_000

// Latch: once the backend has answered ONCE this session, a later failed probe
// means the backend died (offline), never "starting".
let backendSeenOnce = false

// Steady-state heartbeat once the backend is fully ready. Two serial fetches
// (quotes-warmed + settings) fire every tick; at 15s that was a needless ~8
// round-trips/min against a server whose ready state barely changes. 30s halves
// that idle load while still catching a mid-session provider/model change within
// a tick. The cold-start window keeps polling fast (BOOT_POLL_MS) so the UI
// flips from "starting engine" to live the instant the warmup finishes.
const STEADY_HEARTBEAT_MS = 30_000
const BOOT_POLL_MS = 1_500

function unreachableState(): HealthState {
  const starting = !backendSeenOnce && Date.now() - BOOT_TIME < STARTUP_GRACE_MS
  return {
    level: starting ? 'starting' : 'offline',
    backendReachable: false,
    quotesWarmed: false,
    availableProviders: [],
    startupError: null,
    // Optimistic default: never show onboarding/preflight nags until the
    // backend actually says the model is unconfigured.
    modelConfigured: true,
    // Offline/booting → the engine is by definition not serving yet.
    engineReady: false,
    agentsReady: false,
  }
}

export function useHealth() {
  return useQuery<HealthState>({
    queryKey: ['health'],
    queryFn: async ({ signal }): Promise<HealthState> => {
      // 1) Reachability + warmup. If this throws/!ok the backend is offline
      //    (or, before the first successful contact, still starting).
      let warmed: QuotesWarmedShape
      try {
        const r = await fetchWithTimeout(`${BASE_URL}/api/health/quotes-warmed`, { signal })
        if (!r.ok) return unreachableState()
        warmed = (await r.json()) as QuotesWarmedShape
      } catch {
        return unreachableState()
      }
      backendSeenOnce = true

      // 2) Honest provider/config snapshot. Backend is already reachable, so a
      //    failure here is a soft-miss — keep the connection green but report
      //    no specific providers rather than guessing.
      let providers: string[] = []
      let startupError: string | null = null
      let modelConfigured = true
      try {
        const r = await fetchWithTimeout(`${BASE_URL}/api/settings`, { signal })
        if (r.ok) {
          const s = (await r.json()) as SettingsHealthShape
          providers = Array.isArray(s.available_providers) ? s.available_providers : []
          startupError = s.startup_error ?? null
          modelConfigured = s.model_configured ?? true
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
        modelConfigured,
        // `!== false`: a pre-split backend omits these → treated as ready.
        engineReady: warmed.engine_ready !== false,
        agentsReady: warmed.agents_ready !== false,
      }
    },
    // Poll fast while the backend hasn't answered yet (sidecar booting — the
    // BootGate splash clears the moment this flips) AND through the cold-start
    // warmup window (engine/agents wiring in the background), so live-data UI
    // flips from "starting engine" to real the instant the warmup finishes.
    // Once fully ready, settle into a calm 30 s heartbeat (STEADY_HEARTBEAT_MS).
    staleTime: 15_000,
    refetchInterval: (query) => {
      const d = query.state.data
      const fullyReady = d?.backendReachable && d?.engineReady && d?.agentsReady
      return fullyReady ? STEADY_HEARTBEAT_MS : BOOT_POLL_MS
    },
    retry: false,
    placeholderData: unreachableState,
  })
}
