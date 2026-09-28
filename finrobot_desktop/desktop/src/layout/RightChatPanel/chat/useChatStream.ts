// useChatStream — the chat state machine behind AiChatTab: session-bound
// useChat transport, transcript seeding, artifact invalidation, input state,
// submit/retry, and the pending-prompt hand-off. AiChatTab renders; this hook
// owns every effect that drives the conversation.

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { DynamicToolUIPart } from 'ai'
import { isToolUIPart } from 'ai'
import { useToastStore } from '../../../stores/toastStore'
import { useUiStore } from '../../../stores/uiStore'
import { useI18n, useUiPrefs } from '../../../i18n'
import { BASE_URL, api } from '../../../api/client'
import { fetchBackendStream } from '../../../api/fetch'
import { useChatSessions } from '../../../hooks/useChatSessions'
import { MAX_INPUT_LENGTH, isContextOverflowError } from './constants'

// ──────────────────────────────────────────────────────────────
// Context bundle — the structured context the ContextBar shows is sent to
// /chat on every turn so the model actually has the report/route the user
// thinks it does (BUG-20260602-038). Derived live (not memoised) inside the
// transport `body` thunk so each send captures the current route.
// ──────────────────────────────────────────────────────────────

interface ChatContextBundle {
  route: string
  ticker: string | null
  artifact_id: string | null
}

/** Pull the artifactId out of a /stocks/:ticker/runs/:artifactId path. */
function artifactIdFromPath(pathname: string): string | null {
  const m = /^\/stocks\/[^/]+\/runs\/([^/?#]+)/.exec(pathname)
  return m ? m[1] : null
}

export function useChatStream(ticker: string | undefined) {
  const addToast = useToastStore((s) => s.addToast)
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const pendingChatPrompt = useUiStore((s) => s.pendingChatPrompt)
  const consumePendingPrompt = useUiStore((s) => s.consumePendingChatPrompt)

  const [inputText, setInputText] = useState('')

  // Chat sessions as first-class objects: persistent, switchable, resumable,
  // deletable, and DECOUPLED from ticker (navigating to another stock no longer
  // switches the conversation). The active session id drives `useChat`; its
  // transcript is re-seeded so a switched/reloaded session can keep chatting.
  // onSwitch clears transient input so a fresh/switched session starts clean.
  const {
    sessions,
    sessionsLoading,
    sessionsError,
    activeSessionId,
    seedMessages,
    seedLoading,
    newSession,
    switchSession,
    deleteSession,
    deletingId,
  } = useChatSessions(useCallback(() => setInputText(''), []))

  // The configured lead model (settings.model_name) — shared ['settings']
  // query, deduped with SettingsView. Drives the read-only
  // badge AND the transcript model hint, so the log records the model that
  // actually answered rather than a stale prototype default.
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/settings')
      if (error || !data) throw new Error('settings unavailable')
      return data
    },
  })
  const configuredModel = settings?.model_name

  // Transport — recreated when ticker/model changes. Absolute URL is
  // required in Tauri prod builds (asset loads from `file://` so a
  // relative `/chat` resolves to a non-existent file scheme path and the
  // entire AI panel falls silent). Dev keeps `''` so Vite proxies it.
  //
  // `body` is a THUNK (resolved per-send by the AI SDK) so every turn carries
  // the LIVE UI locale (BUG-20260602-048) and the LIVE ContextBar bundle —
  // current route, open report artifact id, focused ticker
  // (BUG-20260602-038). A static object would freeze these at
  // transport-construction time and the model would never see route
  // changes within a session.
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `${BASE_URL}/chat`,
        // Authenticate the LLM stream with the capability token (no timeout —
        // the chat SSE runs 30-60s). Without this /chat 401s under enforced auth.
        fetch: fetchBackendStream,
        body: () => {
          const { pathname } = window.location
          const context_bundle: ChatContextBundle = {
            route: pathname,
            ticker: ticker ?? null,
            artifact_id: artifactIdFromPath(pathname),
          }
          // No `model` field: the backend records the model from its own
          // authoritative settings (= what the user picked, = what the agent
          // runs), so a client echo here is dead weight that only raced the
          // /api/settings fetch and stamped "unknown" into the transcript.
          return {
            ticker: ticker ?? null,
            locale: useUiPrefs.getState().locale,
            context_bundle,
          }
        },
      }),
    [ticker],
  )

  const { messages, status, error, sendMessage, stop, regenerate, clearError, setMessages } =
    useChat({
      // Per-session Chat instance: changing the id rebinds useChat to that
      // conversation. The transcript-derived seed is re-applied via the effect
      // below (the transcript resolves async after the id flips).
      id: activeSessionId,
      messages: seedMessages ?? [],
      transport,
      onError(err) {
        const msg = err.message ?? ''
        if (isContextOverflowError(msg)) {
          addToast({ type: 'error', title: t('chat.error.context') })
        } else if (msg.includes('503') || msg.includes('Service Unavailable')) {
          addToast({ type: 'error', title: t('chat.error.unavailable') })
        } else {
          addToast({
            type: 'error',
            title: t('chat.error.generic'),
            description: msg || undefined,
          })
        }
      },
    })

  const isLoading = status === 'submitted' || status === 'streaming'

  // ── Seed the chat from the active session's transcript ───────────────────
  // useChat recreates its Chat when `id` flips, but the transcript that seeds it
  // resolves asynchronously *after* the flip — so the initial `messages` is
  // empty for one render. Re-apply the rebuilt messages once they arrive, ONCE
  // per session (a ref guard), and never mid-stream (would clobber live tokens).
  // This covers switch (resume), reload (restored active id), and new (empty
  // transcript → seeds an empty conversation).
  const seededSessionRef = useRef<string | null>(null)
  useEffect(() => {
    if (seedMessages === undefined) return // transcript still loading
    if (isLoading) return // never overwrite an in-flight stream
    if (seededSessionRef.current === activeSessionId) return // already seeded
    seededSessionRef.current = activeSessionId
    setMessages(seedMessages)
  }, [activeSessionId, seedMessages, isLoading, setMessages])

  // ── AI-generated artifact → invalidate the same read models the REST run
  // path refreshes ─────────────────────────────────────────────────────────
  // When an AI panel tool (DCF / comps / equity_research / …) finishes and
  // its output carries an artifact_id, a new immutable artifact now exists
  // server-side. The workspace AIZone timeline query (staleTime: Infinity on
  // the immutable timeline) would otherwise keep serving its pre-run
  // snapshot, leaving the AI-made artifact an island the UI never reflects.
  // Mirror StockWorkspace's completion invalidation exactly (key-prefix match
  // covers every limit variant):
  //   useV5ArtifactTimeline:      ['v5-artifacts-timeline', ticker]
  // Guard: each artifact_id is invalidated once (a Set ref), so the effect
  // re-running on every streamed token / render doesn't re-fire.
  const invalidatedArtifactsRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    for (const message of messages) {
      if (message.role !== 'assistant') continue
      for (const part of message.parts) {
        if (!isToolUIPart(part)) continue
        const anyPart = part as DynamicToolUIPart
        if (anyPart.state !== 'output-available') continue
        const output = anyPart.output
        if (!output || typeof output !== 'object') continue
        const { artifact_id, ticker: outTicker } = output as {
          artifact_id?: string
          ticker?: string
        }
        if (!artifact_id) continue
        if (invalidatedArtifactsRef.current.has(artifact_id)) continue
        invalidatedArtifactsRef.current.add(artifact_id)

        const symbol = (outTicker ?? ticker ?? '').toUpperCase()
        if (symbol) {
          void queryClient.invalidateQueries({ queryKey: ['v5-artifacts-timeline', symbol] })
        }
      }
    }
  }, [messages, ticker, queryClient])

  // NOTE: sessions are deliberately decoupled from ticker — navigating to
  // another stock no longer switches or destroys the conversation. The live
  // per-turn ticker still reaches the backend via the transport context_bundle
  // (see `body` thunk above); only session *identity* is independent now.

  // ── Submit handler ──────────────────────────────────────────
  const handleSubmit = useCallback(() => {
    const text = inputText.trim()
    if (!text) return
    if (text.length > MAX_INPUT_LENGTH) return
    if (isLoading) return

    clearError()
    sendMessage({ text })
    setInputText('')
  }, [inputText, isLoading, sendMessage, clearError])

  const handleReload = useCallback(() => {
    clearError()
    regenerate()
  }, [clearError, regenerate])

  // ── Pending prompt from Dashboard hero (or anywhere) ─────────
  // Fills the input box; auto-sends if the caller requested it.
  useEffect(() => {
    if (!pendingChatPrompt) return
    const { text, autoSend } = pendingChatPrompt
    setInputText(text)
    consumePendingPrompt()
    if (autoSend && !isLoading) {
      clearError()
      sendMessage({ text })
      setInputText('')
    }
  }, [pendingChatPrompt, consumePendingPrompt, isLoading, sendMessage, clearError])

  return {
    inputText,
    setInputText,
    sessions,
    sessionsLoading,
    sessionsError,
    activeSessionId,
    seedLoading,
    newSession,
    switchSession,
    deleteSession,
    deletingId,
    settings,
    configuredModel,
    messages,
    status,
    error,
    isLoading,
    stop,
    handleSubmit,
    handleReload,
  }
}
