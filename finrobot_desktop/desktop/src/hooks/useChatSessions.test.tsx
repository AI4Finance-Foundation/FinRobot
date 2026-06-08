// useChatSessions tests — the session lifecycle logic that the chat panel
// depends on: localStorage-persisted active id, delete-with-fallback, and the
// optimistic list removal. Network is mocked at globalThis.fetch.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { createElement } from 'react'
import { useChatSessions, type ChatSessionSummary } from './useChatSessions'

const ACTIVE_KEY = 'finrobot-active-session'

function summary(over: Partial<ChatSessionSummary> = {}): ChatSessionSummary {
  return {
    session_id: 's1',
    title: 'A session',
    created_at: '2026-06-08T00:00:00Z',
    last_active_at: '2026-06-08T00:00:00Z',
    turn_count: 2,
    model: 'anthropic:claude',
    user_id: 'local',
    ticker: null,
    ...over,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children)
}

beforeEach(() => {
  localStorage.clear()
  vi.spyOn(globalThis, 'fetch')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useChatSessions — active id persistence', () => {
  it('restores the active session id from localStorage on mount', async () => {
    localStorage.setItem(ACTIVE_KEY, 'restored-id')
    // sessions list + transcript fetches both resolve empty.
    vi.mocked(globalThis.fetch).mockResolvedValue(jsonResponse({ sessions: [], events: [] }))

    const { result } = renderHook(() => useChatSessions(), { wrapper: wrapper() })
    expect(result.current.activeSessionId).toBe('restored-id')
  })

  it('mints a fresh id when none is stored, and persists it', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(jsonResponse({ sessions: [], events: [] }))

    const { result } = renderHook(() => useChatSessions(), { wrapper: wrapper() })
    const id = result.current.activeSessionId
    expect(id).toMatch(/[0-9a-f-]{36}/)
    await waitFor(() => expect(localStorage.getItem(ACTIVE_KEY)).toBe(id))
  })
})

describe('useChatSessions — list filtering', () => {
  it('hides 0-turn empty-shell sessions, keeps real conversations', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url
      if (url.endsWith('/sessions')) {
        return jsonResponse({
          sessions: [
            summary({ session_id: 'real', turn_count: 3 }),
            summary({ session_id: 'empty', turn_count: 0 }),
          ],
        })
      }
      return jsonResponse({ events: [] }) // active session's transcript
    })

    const { result } = renderHook(() => useChatSessions(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.sessions.map((s) => s.session_id)).toEqual(['real']))
  })
})

describe('useChatSessions — new / switch', () => {
  it('newSession switches to a fresh id and invokes onSwitch', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(jsonResponse({ sessions: [], events: [] }))
    const onSwitch = vi.fn()
    const { result } = renderHook(() => useChatSessions(onSwitch), { wrapper: wrapper() })

    const before = result.current.activeSessionId
    act(() => result.current.newSession())
    expect(result.current.activeSessionId).not.toBe(before)
    expect(onSwitch).toHaveBeenCalled()
  })

  it('switchSession points the active id at the chosen session', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(jsonResponse({ sessions: [], events: [] }))
    const { result } = renderHook(() => useChatSessions(), { wrapper: wrapper() })

    act(() => result.current.switchSession('other-session'))
    expect(result.current.activeSessionId).toBe('other-session')
  })
})

describe('useChatSessions — delete', () => {
  it('deleting the ACTIVE session falls back to a new empty session', async () => {
    localStorage.setItem(ACTIVE_KEY, 'active-1')
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url
      if (url.includes('/api/chat/sessions') && !url.endsWith('/sessions')) {
        // transcript GET or DELETE
        return jsonResponse({ status: 'deleted', session_id: 'active-1', events: [] })
      }
      return jsonResponse({ sessions: [summary({ session_id: 'active-1' })] })
    })

    const { result } = renderHook(() => useChatSessions(), { wrapper: wrapper() })
    expect(result.current.activeSessionId).toBe('active-1')

    act(() => result.current.deleteSession('active-1'))

    // Active id must move OFF the deleted session to a fresh one.
    expect(result.current.activeSessionId).not.toBe('active-1')
    expect(result.current.activeSessionId).toMatch(/[0-9a-f-]{36}/)
  })

  it('deleting a NON-active session keeps the active id and removes the row', async () => {
    localStorage.setItem(ACTIVE_KEY, 'keep-active')
    // The server stops returning a deleted session on the next list fetch; model
    // that so the invalidate-driven refetch reconciles with the optimistic drop.
    const deleted = new Set<string>()
    vi.mocked(globalThis.fetch).mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url
      const method = (init?.method ?? (input as Request).method ?? 'GET').toUpperCase()
      if (url.endsWith('/sessions') && method === 'GET') {
        const all = [summary({ session_id: 'keep-active' }), summary({ session_id: 'doomed' })]
        return jsonResponse({ sessions: all.filter((s) => !deleted.has(s.session_id)) })
      }
      if (method === 'DELETE') {
        deleted.add('doomed')
        return jsonResponse({ status: 'deleted', session_id: 'doomed' })
      }
      return jsonResponse({ events: [] }) // transcript
    })

    const { result } = renderHook(() => useChatSessions(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.sessions.length).toBe(2))

    act(() => result.current.deleteSession('doomed'))

    // Active id unchanged; the doomed row leaves the list (optimistic, then
    // reconciled by the refetch which no longer returns it).
    expect(result.current.activeSessionId).toBe('keep-active')
    await waitFor(() =>
      expect(result.current.sessions.some((s) => s.session_id === 'doomed')).toBe(false),
    )
    expect(result.current.sessions.some((s) => s.session_id === 'keep-active')).toBe(true)
  })
})

describe('useChatSessions — transcript seeding', () => {
  it('rebuilds seedMessages from the active session transcript', async () => {
    localStorage.setItem(ACTIVE_KEY, 'with-history')
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url
      if (url.endsWith('/sessions')) return jsonResponse({ sessions: [] })
      return jsonResponse({
        session_id: 'with-history',
        events: [
          {
            timestamp: 't',
            session_id: 'with-history',
            event: 'user_msg',
            data: { text: 'hello' },
          },
          {
            timestamp: 't',
            session_id: 'with-history',
            event: 'assistant_text',
            data: { text: 'hi there' },
          },
        ],
      })
    })

    const { result } = renderHook(() => useChatSessions(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.seedMessages?.length).toBe(2))
    expect(result.current.seedMessages?.[0].role).toBe('user')
    expect(result.current.seedMessages?.[1].role).toBe('assistant')
  })
})
