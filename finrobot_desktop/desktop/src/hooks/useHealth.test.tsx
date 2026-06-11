// useHealth boot-state tests — the 'starting' contract that gates BootSplash:
// an unreachable backend before first contact = 'starting' (inside the grace
// window), beyond the grace window = 'offline', and once the backend has
// answered this session, any later failure = 'offline' (never 'starting').
//
// Module state (BOOT_TIME + the backendSeenOnce latch) is reset per test via
// vi.resetModules() + dynamic import; Date.now is stubbed (no fake timers, so
// react-query's microtasks run normally).

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { createElement } from 'react'

const mockFetch = vi.fn()
vi.mock('../api/fetch', () => ({
  fetchWithTimeout: (...args: unknown[]) => mockFetch(...args),
}))

const T0 = 1_750_000_000_000

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children)
}

async function freshUseHealth() {
  vi.resetModules()
  const mod = await import('./useHealth')
  return mod.useHealth
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

function healthyBackend(): void {
  mockFetch.mockImplementation((input: string) => {
    if (String(input).includes('/api/health/quotes-warmed')) {
      return Promise.resolve(jsonResponse({ warmed: true, studied_ticker_count: 1 }))
    }
    return Promise.resolve(
      jsonResponse({ available_providers: ['fmp'], startup_error: null, model_configured: true }),
    )
  })
}

beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(T0)
  mockFetch.mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useHealth — starting vs offline', () => {
  it("reports 'starting' while unreachable inside the boot grace window", async () => {
    const useHealth = await freshUseHealth()
    mockFetch.mockRejectedValue(new TypeError('fetch failed'))

    const { result } = renderHook(() => useHealth(), { wrapper: wrapper() })

    await waitFor(() => expect(result.current.isPlaceholderData).toBe(false))
    expect(result.current.data?.level).toBe('starting')
    expect(result.current.data?.backendReachable).toBe(false)
  })

  it("reports 'offline' when still unreachable past the grace window", async () => {
    const useHealth = await freshUseHealth() // BOOT_TIME captured at T0
    vi.mocked(Date.now).mockReturnValue(T0 + 120_001)
    mockFetch.mockRejectedValue(new TypeError('fetch failed'))

    const { result } = renderHook(() => useHealth(), { wrapper: wrapper() })

    await waitFor(() => expect(result.current.isPlaceholderData).toBe(false))
    expect(result.current.data?.level).toBe('offline')
  })

  it("latches: once reachable, a later failure is 'offline', never 'starting'", async () => {
    const useHealth = await freshUseHealth()
    healthyBackend()

    const { result } = renderHook(() => useHealth(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.data?.level).toBe('connected'))

    mockFetch.mockReset()
    mockFetch.mockRejectedValue(new TypeError('fetch failed'))
    await result.current.refetch()

    await waitFor(() => expect(result.current.data?.level).toBe('offline'))
  })

  it("reports 'connected' once the backend answers fully", async () => {
    const useHealth = await freshUseHealth()
    healthyBackend()

    const { result } = renderHook(() => useHealth(), { wrapper: wrapper() })

    await waitFor(() => expect(result.current.data?.level).toBe('connected'))
    expect(result.current.data?.backendReachable).toBe(true)
    expect(result.current.data?.availableProviders).toEqual(['fmp'])
  })
})
