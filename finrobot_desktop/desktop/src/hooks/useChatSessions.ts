// useChatSessions — chat sessions as first-class, ticker-decoupled objects.
//
// Sessions are persistent (backend JSONL transcripts), switchable, resumable
// (you can keep chatting), and deletable. The active session id is the single
// source of truth for which conversation `useChat` is bound to; it is persisted
// to localStorage so a reload reopens the same conversation (its transcript is
// re-seeded via `reconstructMessages`).
//
// Decoupled from ticker on purpose: navigating to another stock does NOT switch
// or destroy the conversation. A session records its *origin* ticker once (at
// creation, as a label) — the live per-turn ticker still flows to the backend
// through the transport `context_bundle`, untouched by this hook.
//
// Server state (the session list + a single transcript) is TanStack Query;
// delete is a mutation that invalidates the list. The active id is local
// React state mirrored to localStorage.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'
import { reconstructMessages, type TranscriptEvent } from '../lib/transcriptReplay'
import type { UIMessage } from 'ai'

// localStorage key for the active session id. Mirrors the project's
// `finrobot-*` localStorage naming (finrobot-ui-shell / finrobot-ui-prefs).
const ACTIVE_SESSION_KEY = 'finrobot-active-session'

/** Session summary as returned by GET /api/chat/sessions. */
export interface ChatSessionSummary {
  session_id: string
  title: string
  created_at: string
  last_active_at: string
  turn_count: number
  model: string
  user_id: string
  ticker: string | null
}

// ── localStorage helpers (guarded — SSR / disabled storage safe) ──────────

function readActiveSession(): string | null {
  try {
    return localStorage.getItem(ACTIVE_SESSION_KEY)
  } catch {
    return null
  }
}

function writeActiveSession(id: string): void {
  try {
    localStorage.setItem(ACTIVE_SESSION_KEY, id)
  } catch {
    // Storage unavailable (private mode / quota) — the in-memory id still drives
    // the session this run; only cross-reload persistence is lost.
  }
}

// ── Server fetchers ───────────────────────────────────────────────────────

/** Global session list — newest-first, NO ticker filter (sessions are global). */
async function fetchSessions(signal?: AbortSignal): Promise<ChatSessionSummary[]> {
  const res = await fetchWithTimeout(`${BASE_URL}/api/chat/sessions`, { signal })
  if (!res.ok) throw new Error(`sessions ${res.status}`)
  const body = (await res.json()) as { sessions: ChatSessionSummary[] }
  return body.sessions
}

/** One session's full transcript (events), for re-seeding the chat. */
async function fetchTranscript(
  sessionId: string,
  signal?: AbortSignal,
): Promise<TranscriptEvent[]> {
  const res = await fetchWithTimeout(
    `${BASE_URL}/api/chat/sessions/${encodeURIComponent(sessionId)}`,
    { signal },
  )
  // 404 = brand-new session never written to disk yet → empty transcript, not
  // an error (a freshly-created session has no JSONL until its first turn).
  if (res.status === 404) return []
  if (!res.ok) throw new Error(`transcript ${res.status}`)
  const body = (await res.json()) as { events: TranscriptEvent[] }
  return body.events
}

/** DELETE one session's transcript. Token-injected via fetchWithTimeout. */
async function deleteSessionRequest(sessionId: string): Promise<void> {
  const res = await fetchWithTimeout(
    `${BASE_URL}/api/chat/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' },
  )
  // 404 = already gone; treat as success so the row leaves the list regardless.
  if (!res.ok && res.status !== 404) throw new Error(`delete ${res.status}`)
}

// ── Hook return shape ──────────────────────────────────────────────────────

export interface UseChatSessions {
  /** All sessions, newest-first (global, ticker-independent). */
  sessions: ChatSessionSummary[]
  sessionsLoading: boolean
  sessionsError: boolean
  /** The conversation `useChat` is bound to. */
  activeSessionId: string
  /** Messages rebuilt from the active session's transcript, to seed `useChat`.
   * Empty for a brand-new session. `undefined` while the transcript is loading
   * so the caller can avoid seeding the chat with a stale/empty list mid-fetch. */
  seedMessages: UIMessage[] | undefined
  /** Whether the active session's transcript is still loading. */
  seedLoading: boolean
  /** Start a fresh empty session and switch to it (does not touch existing ones). */
  newSession: () => void
  /** Switch to an existing session — its transcript re-seeds the chat (resume). */
  switchSession: (id: string) => void
  /** Permanently delete a session; if it was active, fall back to a new one. */
  deleteSession: (id: string) => void
  deletingId: string | null
}

/**
 * Manage chat sessions + the active conversation.
 *
 * @param onSwitch Called whenever the active session changes (new / switch /
 *   delete-fallback) so the caller can reset transient input/error UI.
 */
export function useChatSessions(onSwitch?: () => void): UseChatSessions {
  const queryClient = useQueryClient()

  // Active id: restore from localStorage, else mint a fresh session id. Lazy
  // initializer runs once so a reload reopens the same conversation.
  const [activeSessionId, setActiveSessionId] = useState<string>(
    () => readActiveSession() ?? crypto.randomUUID(),
  )

  // Persist every active-id change so reload restores it.
  useEffect(() => {
    writeActiveSession(activeSessionId)
  }, [activeSessionId])

  const sessionsQuery = useQuery({
    queryKey: ['chat-sessions'],
    queryFn: ({ signal }) => fetchSessions(signal),
    staleTime: 0,
  })

  // Transcript of the active session → seed messages. Keyed by id so switching
  // sessions refetches the right transcript. A new (not-yet-persisted) session
  // 404s → [] (handled in fetchTranscript), so seedMessages is [] not an error.
  const transcriptQuery = useQuery({
    queryKey: ['chat-transcript', activeSessionId],
    queryFn: ({ signal }) => fetchTranscript(activeSessionId, signal),
    staleTime: 0,
    // Keep refetch on focus off — re-seeding mid-conversation would clobber the
    // live useChat state. We only seed on mount / explicit switch.
    refetchOnWindowFocus: false,
  })

  const seedMessages = useMemo<UIMessage[] | undefined>(() => {
    if (transcriptQuery.data === undefined) return undefined
    return reconstructMessages(transcriptQuery.data)
  }, [transcriptQuery.data])

  const deleteMutation = useMutation({
    mutationFn: deleteSessionRequest,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    },
  })

  const newSession = useCallback(() => {
    const id = crypto.randomUUID()
    setActiveSessionId(id)
    onSwitch?.()
  }, [onSwitch])

  const switchSession = useCallback(
    (id: string) => {
      if (id === activeSessionId) {
        onSwitch?.()
        return
      }
      setActiveSessionId(id)
      onSwitch?.()
    },
    [activeSessionId, onSwitch],
  )

  const deleteSession = useCallback(
    (id: string) => {
      deleteMutation.mutate(id)
      // If we deleted the active conversation, fall back to a fresh empty one so
      // the chat surface never points at a now-missing transcript.
      if (id === activeSessionId) {
        const next = crypto.randomUUID()
        setActiveSessionId(next)
        onSwitch?.()
      }
      // Optimistically drop the row so the list reflects the delete immediately;
      // the invalidate on settle reconciles with the server.
      queryClient.setQueryData<ChatSessionSummary[]>(['chat-sessions'], (prev) =>
        prev ? prev.filter((s) => s.session_id !== id) : prev,
      )
    },
    [activeSessionId, deleteMutation, onSwitch, queryClient],
  )

  // Only real conversations belong in the list. A 0-turn session is an empty
  // shell — a transcript that got a session_start but never a user message (an
  // abandoned/transient session, or seeded test data) — never something the user
  // started on purpose. Hiding them keeps the drawer about actual chats; a fresh
  // session appears the moment it has its first turn.
  const sessions = useMemo(
    () => (sessionsQuery.data ?? []).filter((s) => s.turn_count > 0),
    [sessionsQuery.data],
  )

  return {
    sessions,
    sessionsLoading: sessionsQuery.isLoading,
    sessionsError: sessionsQuery.isError,
    activeSessionId,
    seedMessages,
    seedLoading: transcriptQuery.isLoading,
    newSession,
    switchSession,
    deleteSession,
    deletingId: deleteMutation.isPending ? (deleteMutation.variables ?? null) : null,
  }
}
