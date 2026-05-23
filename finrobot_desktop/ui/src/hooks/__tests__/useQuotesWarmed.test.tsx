// useQuotesWarmed — polling stops once `warmed` flips to true.
//
// The contract we lock in:
//   - while warmed=false, the hook refetches at ~500ms intervals
//   - once warmed=true is observed, the hook stops refetching
//   - the studied_ticker_count value propagates verbatim
//
// We mock `fetch` directly (no MSW) so the test stays a single file.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import React from 'react'
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import { useQuotesWarmed } from '../useQuotesWarmed'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

describe('useQuotesWarmed', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch')
  })

  afterEach(() => {
    fetchSpy.mockRestore()
  })

  it('returns warmed=false initially while backend is still warming', async () => {
    fetchSpy.mockResolvedValue(jsonResponse({ warmed: false, studied_ticker_count: 0 }))
    const { result } = renderHook(() => useQuotesWarmed(), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual({
      warmed: false,
      studied_ticker_count: 0,
    })
  })

  it('reflects warmed=true with ticker count once backend reports it', async () => {
    fetchSpy.mockResolvedValue(jsonResponse({ warmed: true, studied_ticker_count: 7 }))
    const { result } = renderHook(() => useQuotesWarmed(), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.data?.warmed).toBe(true))
    expect(result.current.data).toEqual({
      warmed: true,
      studied_ticker_count: 7,
    })
  })

  it('stops refetching once warmed flips to true', async () => {
    // First response: still warming. Subsequent: warmed.
    fetchSpy
      .mockResolvedValueOnce(jsonResponse({ warmed: false, studied_ticker_count: 0 }))
      .mockResolvedValue(jsonResponse({ warmed: true, studied_ticker_count: 3 }))

    const { result } = renderHook(() => useQuotesWarmed(), {
      wrapper: makeWrapper(),
    })

    // Wait until warmed flips true (react-query polls per the hook's
    // refetchInterval: 500ms while warmed=false).
    await waitFor(() => expect(result.current.data?.warmed).toBe(true), { timeout: 3000 })

    const callsAtWarmed = fetchSpy.mock.calls.length
    // Wait longer than the 500ms refetch interval; if the hook was
    // still polling we'd see more fetch calls.
    await new Promise((r) => setTimeout(r, 1200))
    expect(fetchSpy.mock.calls.length).toBe(callsAtWarmed)
  })
})
