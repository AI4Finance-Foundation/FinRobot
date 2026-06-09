// AiChatTab — chat body of the right panel (cosmic Stage A split).
//
// Was: the entire RightChatPanel (outer aside + expand/collapse + chat).
// Now: chat content only; the aside + expand + tab toggle live in
// RightChatPanel/index.tsx. This file owns the per-ticker chat session,
// the model picker header, ContextBar, message list, and the input area.

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { UIMessage, UIMessagePart, UIDataTypes, UITools, DynamicToolUIPart } from 'ai'
import { isTextUIPart, isToolUIPart, isReasoningUIPart } from 'ai'
import { useToastStore } from '../../stores/toastStore'
import { useUiStore } from '../../stores/uiStore'
import { ToolCard } from '../../components/ToolCard'
import type { ToolResult } from '../../components/ToolCard'
import { MarkdownLite } from '../../components/MarkdownLite'
import { useI18n, useUiPrefs } from '../../i18n'
import { BASE_URL, api } from '../../api/client'
import { fetchBackendStream } from '../../api/fetch'
import { IconClock, IconPlus, IconClose } from '../../lib/icons'
import { ContextBar } from '../AIPanel/ContextBar'
import { useChatSessions } from '../../hooks/useChatSessions'
import { SessionsDrawer } from './SessionsDrawer'
import { CoverageTriageStrip } from './CoverageTriageStrip'

// ──────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────

const MAX_INPUT_LENGTH = 20_000

// True only for a genuine LLM context-window overflow, matched on the specific
// phrases providers actually emit — NOT the bare substrings "context"/"token".
// A 422 from /chat echoes the request body (which carries our `context_bundle`),
// and auth failures mention the "capability token"; matching bare "context" or
// "token" mislabeled those protocol/auth errors as "Conversation too long"
// (a one-line message that triggered four 422 retries, all misreported).
const CONTEXT_OVERFLOW_RE =
  /context[_ ]length|maximum context|context window|prompt is too long|reduce the length/i
function isContextOverflowError(message: string): boolean {
  return CONTEXT_OVERFLOW_RE.test(message)
}

// ──────────────────────────────────────────────────────────────
// Context bundle — the structured context the ContextBar shows is sent to
// /chat on every turn so the model actually has the report/selection the user
// thinks it does (BUG-20260602-038). Derived live (not memoised) inside the
// transport `body` thunk so each send captures the current route + store.
// ──────────────────────────────────────────────────────────────

interface ChatContextBundle {
  route: string
  ticker: string | null
  artifact_id: string | null
  pinned: Array<{ kind: string; id: string; label: string }>
  selected_text?: string
}

/** Pull the artifactId out of a /stocks/:ticker/runs/:artifactId path. */
function artifactIdFromPath(pathname: string): string | null {
  const m = /^\/stocks\/[^/]+\/runs\/([^/?#]+)/.exec(pathname)
  return m ? m[1] : null
}

// ──────────────────────────────────────────────────────────────
// Model badge — the chat runs on the SINGLE model configured in Settings
// (settings.model_name, e.g. "anthropic:claude-sonnet-4-6"). The badge is
// read-only and MUST reflect that real value. The label is derived from the
// provider registry returned by /api/settings (single source of truth — no
// hardcoded map that drifts), as "<provider label> · <model id>". An unknown
// provider falls back to the bare model id so the badge stays honest.
function modelLabel(
  modelName: string | undefined,
  providers: { id: string; label: string }[] | undefined,
): string {
  if (!modelName) return '…'
  const [providerId, ...rest] = modelName.split(':')
  const modelId = rest.join(':')
  const provider = providers?.find((p) => p.id === providerId)
  if (provider) return modelId ? `${provider.label} · ${modelId}` : provider.label
  return modelId || modelName
}

// ──────────────────────────────────────────────────────────────
// AiChatTab — chat body, no aside wrapper.
//
// Props are inherited from the legacy RightChatPanel API so existing
// tests that injected `expanded` / `onToggle` keep working through the
// shim in RightChatPanel/index.tsx.
// ──────────────────────────────────────────────────────────────

interface AiChatTabProps {
  /** When provided by tests/legacy callers, overrides uiStore.aiPanelOpen. */
  expanded?: boolean
  /** When provided by tests/legacy callers, called instead of uiStore.toggleAiPanel. */
  onToggle?: () => void
}

export function AiChatTab({
  expanded: expandedProp,
  onToggle: onToggleProp,
}: AiChatTabProps = {}): React.ReactElement {
  const { ticker } = useParams<{ ticker?: string }>()
  const addToast = useToastStore((s) => s.addToast)
  const { t } = useI18n()
  const queryClient = useQueryClient()

  // ── uiStore bindings ────────────────────────────────────────
  const storeOpen = useUiStore((s) => s.aiPanelOpen)
  const storeWidth = useUiStore((s) => s.aiPanelWidth)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)
  const setAiPanelWidth = useUiStore((s) => s.setAiPanelWidth)
  const pendingChatPrompt = useUiStore((s) => s.pendingChatPrompt)
  const consumePendingPrompt = useUiStore((s) => s.consumePendingChatPrompt)

  // Prop-override: if caller supplies expanded/onToggle, use those.
  // Otherwise fall through to uiStore.
  const isExpanded = expandedProp !== undefined ? expandedProp : storeOpen
  const handleToggle = onToggleProp !== undefined ? onToggleProp : toggleAiPanel

  const [inputText, setInputText] = useState('')

  // Sessions drawer — list / switch / delete past conversations.
  const [sessionsOpen, setSessionsOpen] = useState(false)

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

  // Track unread for collapsed state
  const [unreadCount, setUnreadCount] = useState(0)
  const lastSeenMessageCountRef = useRef(0)

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
  // current route, open report artifact id, focused ticker, pinned items,
  // selected text (BUG-20260602-038). A static object would freeze these at
  // transport-construction time and the model would never see route/selection
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
          const store = useUiStore.getState()
          const pinned = store.contextBundle.pinned.map((p) => ({
            kind: p.kind,
            id: p.id,
            label: p.label,
          }))
          const selected = store.contextBundle.selected_text?.trim() || undefined
          const context_bundle: ChatContextBundle = {
            route: pathname,
            ticker: ticker ?? null,
            artifact_id: artifactIdFromPath(pathname),
            pinned,
            ...(selected ? { selected_text: selected } : {}),
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
  // server-side. The workspace AIZone / dashboard / studied-tickers queries
  // (staleTime: Infinity on the immutable timeline) would otherwise keep
  // serving their pre-run snapshot, leaving the AI-made artifact an island
  // the UI never reflects. Mirror StockWorkspace's completion invalidation
  // exactly (key-prefix match covers every limit/window variant):
  //   useV5ArtifactTimeline:      ['v5-artifacts-timeline', ticker]
  //   useStudiedTickers:          ['studied-tickers', limit]
  //   useDashboardHitRate:        ['dashboard', 'hit-rate', window]
  //   useDashboardRecentResearch: ['dashboard', 'recent-research', limit]
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
        void queryClient.invalidateQueries({ queryKey: ['studied-tickers'] })
        void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      }
    }
  }, [messages, ticker, queryClient])

  // NOTE: sessions are deliberately decoupled from ticker — navigating to
  // another stock no longer switches or destroys the conversation. The live
  // per-turn ticker still reaches the backend via the transport context_bundle
  // (see `body` thunk above); only session *identity* is independent now.

  // Track unread when panel is collapsed
  useEffect(() => {
    if (!isExpanded) {
      const assistantCount = messages.filter((m) => m.role === 'assistant').length
      if (assistantCount > lastSeenMessageCountRef.current) {
        setUnreadCount(assistantCount - lastSeenMessageCountRef.current)
      }
    } else {
      lastSeenMessageCountRef.current = messages.filter((m) => m.role === 'assistant').length
      setUnreadCount(0)
    }
  }, [messages, isExpanded])

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

  // ── Resize handle ───────────────────────────────────────────
  const panelRef = useRef<HTMLElement>(null)
  const resizing = useRef(false)
  const resizeStartX = useRef(0)
  const resizeStartW = useRef(0)

  const onResizeMouseDown = useCallback(
    (e: React.MouseEvent) => {
      resizing.current = true
      resizeStartX.current = e.clientX
      resizeStartW.current = storeWidth

      const onMove = (ev: MouseEvent): void => {
        if (!resizing.current) return
        // Handle is on left edge: drag left = wider, drag right = narrower
        const delta = resizeStartX.current - ev.clientX
        setAiPanelWidth(resizeStartW.current + delta)
      }
      const onUp = (): void => {
        resizing.current = false
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
      }
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
      e.preventDefault()
    },
    [storeWidth, setAiPanelWidth],
  )

  // ── Handle expand toggle for collapsed state ─────────────────
  const handleExpandToggle = useCallback(() => {
    handleToggle()
    setUnreadCount(0)
    lastSeenMessageCountRef.current = messages.filter((m) => m.role === 'assistant').length
  }, [handleToggle, messages])

  // ── Collapsed: legacy/test path (prop injected) ───────────────
  // Tests that inject expanded={false} still expect an IconColumn; the
  // uiStore path renders nothing here because the splitter (index.tsx)
  // owns the aside + the expand button.
  if (expandedProp === false) {
    return (
      <IconColumn
        onToggle={() => {
          handleToggle()
          setUnreadCount(0)
          lastSeenMessageCountRef.current = messages.filter((m) => m.role === 'assistant').length
        }}
        unreadCount={unreadCount}
        onNewSession={newSession}
      />
    )
  }

  // Reference held variables (read by tests / future floating-summary):
  void panelRef
  void onResizeMouseDown
  void handleExpandToggle

  return (
    <div
      data-testid="right-chat-panel-chat"
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        flex: 1,
      }}
    >
      <AiPanelHeader
        modelLabel={modelLabel(configuredModel, settings?.providers)}
        onToggle={handleToggle}
        onNewSession={newSession}
        onOpenHistory={() => setSessionsOpen(true)}
        ticker={ticker}
        thinking={isLoading}
      />

      {sessionsOpen && (
        <SessionsDrawer
          sessions={sessions}
          activeSessionId={activeSessionId}
          loading={sessionsLoading}
          error={sessionsError}
          deletingId={deletingId}
          onSwitch={switchSession}
          onNew={newSession}
          onDelete={deleteSession}
          onClose={() => setSessionsOpen(false)}
        />
      )}

      <ContextBar />

      <CoverageTriageStrip defaultCollapsed={messages.length > 0} />

      <MessageList
        messages={messages}
        isLoading={isLoading}
        status={status}
        restoring={seedLoading}
      />

      <AiInputArea
        value={inputText}
        onChange={setInputText}
        onSubmit={handleSubmit}
        isLoading={isLoading}
        onStop={stop}
        onReload={handleReload}
        error={error}
        hasMessages={messages.length > 0}
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// AiPanelHeader — .ai-header
// ──────────────────────────────────────────────────────────────

interface AiPanelHeaderProps {
  modelLabel: string
  onToggle: () => void
  onNewSession: () => void
  onOpenHistory: () => void
  ticker: string | undefined
  /** Streaming — gives the presence orb its (spec-legal, ≤1.6s) live pulse. */
  thinking: boolean
}

function AiPanelHeader({
  modelLabel,
  onToggle,
  onNewSession,
  onOpenHistory,
  ticker,
  thinking,
}: AiPanelHeaderProps): React.ReactElement {
  const { t, locale } = useI18n()

  return (
    <div className="ai-header" data-testid="panel-header">
      {/* Presence orb — living AI brand mark (static glow; pulses only while
          streaming). Replaces the old flat "F" tile. */}
      <div className={`ai-presence${thinking ? ' thinking' : ''}`} aria-hidden="true">
        <span className="halo" />
        <span className="core" />
      </div>
      <div className="ai-title">
        Fin<b>Robot</b>
      </div>

      {/* Ticker / Explore context tag — text kept verbatim (asserted by tests). */}
      <span className="ai-ctx-tag">
        <span
          className="dot"
          style={{
            background: ticker ? 'var(--aip-accent)' : 'var(--text-dim)',
            boxShadow: ticker ? '0 0 7px var(--aip-accent)' : 'none',
          }}
        />
        {ticker ?? t('chat.title.explore')}
      </span>

      {/* Model badge (read-only — model configured in Settings) */}
      <span
        data-testid="model-selector"
        className="ai-model"
        title={t('chatpanel.model.configuredInSettings')}
      >
        {modelLabel}
      </span>

      {/* Sessions — list / switch / delete past conversations */}
      <button
        data-testid="history-btn"
        onClick={onOpenHistory}
        title={locale === 'zh' ? '会话' : 'Sessions'}
        className="ai-icon-btn"
        type="button"
      >
        <IconClock size={15} />
      </button>

      {/* New session */}
      <button
        data-testid="new-session-btn"
        onClick={onNewSession}
        title={t('chat.newSession')}
        className="ai-icon-btn"
        type="button"
      >
        <IconPlus size={15} />
      </button>

      {/* Close / collapse */}
      <button
        data-testid="collapse-btn"
        onClick={onToggle}
        title={t('chat.collapse')}
        className="ai-icon-btn"
        type="button"
      >
        <IconClose size={15} />
      </button>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// MessageList
// ──────────────────────────────────────────────────────────────

interface MessageListProps {
  messages: UIMessage[]
  isLoading: boolean
  /** The raw useChat status — drives the real-state phase of the status line
   * ('submitted' = TTFT wait → Requesting; 'streaming' = phase derived from the
   * last assistant message's parts). */
  status: ChatStatus
  /** True while a switched/reloaded session's transcript is being restored —
   * suppresses the empty-state so it doesn't flash "start chatting" mid-resume. */
  restoring: boolean
}

function MessageList({
  messages,
  isLoading,
  status,
  restoring,
}: MessageListProps): React.ReactElement {
  const bottomRef = useRef<HTMLDivElement>(null)
  const { t } = useI18n()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0 && restoring) {
    return (
      <div
        data-testid="message-list-restoring"
        className="ai-messages"
        style={{ justifyContent: 'center', alignItems: 'center' }}
      >
        <div style={{ fontSize: '11px', color: 'var(--text-3)' }}>{t('common.loading')}</div>
      </div>
    )
  }

  if (messages.length === 0 && !isLoading) {
    // Clean welcome — a single calm focal point: just the greeting + the
    // coverage strip, no stacked example list.
    return (
      <div
        data-testid="empty-state"
        className="ai-messages"
        style={{ justifyContent: 'center', alignItems: 'center', gap: '14px', textAlign: 'center' }}
      >
        <div className="ai-presence" aria-hidden="true" style={{ width: 40, height: 40 }}>
          <span className="halo" />
          <span className="core" />
        </div>
        <div>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 600,
              fontSize: '17px',
              color: 'var(--text-primary)',
            }}
          >
            {t('chat.empty.heading')}
          </div>
          <div
            style={{
              fontSize: '12.5px',
              color: 'var(--text-secondary)',
              marginTop: '6px',
              lineHeight: 1.6,
              maxWidth: 300,
            }}
          >
            {t('chat.empty.body')}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div data-testid="message-list" className="ai-messages">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}

      {isLoading && <StatusIndicator status={status} messages={messages} />}

      <div ref={bottomRef} />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// MessageBubble — .msg
// ──────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: UIMessage }): React.ReactElement {
  const isUser = message.role === 'user'
  // Read the replay-supplied timestamp instead of new Date() — the latter
  // re-runs on every render so all historical messages would show "now".
  // The timestamp lives in the Vercel AI SDK's typed `metadata` slot, NOT a
  // root field: a root extra is echoed back by DefaultChatTransport on the
  // next send and rejected by the backend's strict UIMessage schema (422 on
  // every follow-up in a resumed session — see transcriptReplay.ts).
  // useChat() doesn't parameterise metadata, so the field is reachable only
  // via a narrowed read. Live-stream messages carry no metadata; their time
  // is undefined and formatMessageTime drops it rather than fabricating "now".
  const createdAt = (message as UIMessage & { metadata?: { createdAt?: string | Date } }).metadata
    ?.createdAt
  const timeStr = formatMessageTime(createdAt)

  return (
    <div data-testid={`message-${message.role}`} className={`msg ${isUser ? 'user' : 'agent'}`}>
      <div className="msg-head">
        {isUser
          ? timeStr
            ? `USER · ${timeStr}`
            : 'USER'
          : timeStr
            ? `● FINROBOT · ${timeStr}`
            : '● FINROBOT'}
      </div>
      {isUser ? <UserBubble message={message} /> : <AssistantContent message={message} />}
    </div>
  )
}

function formatMessageTime(createdAt: Date | string | undefined): string {
  if (!createdAt) return ''
  const d = createdAt instanceof Date ? createdAt : new Date(createdAt)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function UserBubble({ message }: { message: UIMessage }): React.ReactElement {
  const text = message.parts
    .filter((p) => isTextUIPart(p))
    .map((p) => (p.type === 'text' ? p.text : ''))
    .join('')

  return <div className="msg-body">{text}</div>
}

// ──────────────────────────────────────────────────────────────
// ToolCardFromPart
// ──────────────────────────────────────────────────────────────

function ToolCardFromPart({
  part,
  fallbackId,
}: {
  part: UIMessagePart<UIDataTypes, UITools>
  fallbackId: string
}): React.ReactElement {
  const anyPart = part as DynamicToolUIPart

  const toolName = anyPart.toolName ?? part.type.replace(/^tool-/, '')
  const toolCallId = anyPart.toolCallId ?? fallbackId
  const state = anyPart.state

  const args =
    anyPart.input && typeof anyPart.input === 'object'
      ? (anyPart.input as Record<string, unknown>)
      : {}

  let cardState: 'pending' | 'running' | 'complete' | 'error' = 'pending'
  let result: ToolResult | undefined
  let errorText: string | undefined

  if (state === 'input-streaming' || state === 'input-available') {
    cardState = 'running'
  } else if (state === 'output-available' || state === 'approval-responded') {
    cardState = 'complete'
    const rawOutput = anyPart.output
    if (rawOutput && typeof rawOutput === 'object') {
      // Mode B pipeline tools return {summary, artifact_id, ticker}.
      const o = rawOutput as { summary?: string; artifact_id?: string; ticker?: string }
      result = {
        summary: o.summary ?? '',
        artifact_id: o.artifact_id,
        ticker: o.ticker,
      }
    } else if (typeof rawOutput === 'string' && rawOutput.trim()) {
      // Mode A quick-query tools (query_financial_data / activate_skill) return
      // a plain string — that string IS the answer, so surface it as the summary
      // instead of leaving the card body empty.
      result = { summary: rawOutput }
    }
  } else if (state === 'output-error') {
    cardState = 'error'
    errorText = anyPart.errorText
  }

  return (
    <div className="trace">
      <ToolCard
        toolCallId={toolCallId}
        toolName={toolName}
        args={args}
        result={result}
        errorText={errorText}
        state={cardState}
      />
    </div>
  )
}

function AssistantContent({ message }: { message: UIMessage }): React.ReactElement {
  return (
    <div className="msg-body">
      {message.parts.map((part, idx) => {
        if (isTextUIPart(part)) {
          return (
            <div key={idx} data-testid="text-part">
              <MarkdownLite text={part.text} />
            </div>
          )
        }

        if (isReasoningUIPart(part)) {
          return <ReasoningCollapsible key={idx} text={part.text ?? ''} />
        }

        if (isToolUIPart(part)) {
          return (
            <ToolCardFromPart
              key={idx}
              part={part as UIMessagePart<UIDataTypes, UITools>}
              fallbackId={String(idx)}
            />
          )
        }

        return null
      })}
    </div>
  )
}

function ReasoningCollapsible({ text }: { text: string }): React.ReactElement {
  const [open, setOpen] = useState(false)
  const { t } = useI18n()
  return (
    <div style={{ marginBottom: '4px', fontSize: '11px', color: 'var(--text-3)' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          color: 'var(--text-3)',
          fontSize: '11px',
          display: 'flex',
          alignItems: 'center',
          gap: '4px',
        }}
        type="button"
      >
        {open ? '▾' : '▸'} {t('chat.reasoning')}
      </button>
      {open && (
        <div
          style={{
            marginTop: '4px',
            padding: '6px 10px',
            background: 'var(--bg-3)',
            borderRadius: '4px',
            whiteSpace: 'pre-wrap',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
          }}
        >
          {text}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// StatusIndicator — REAL streaming status (replaces the old fake 3-dot
// blinker). Aligned to how Claude Code drives its waiting indicator: a phase
// derived from actual stream state, a real elapsed-seconds counter, and a
// stall detector (no new content for >3s with no tool running ⇒ honest red
// "is it stuck?" signal). No random verb words, no token counts, no shimmer.
//
//   submitted                         → Requesting…   (TTFT — nothing back yet)
//   streaming + tool running          → Running {tool}…
//   streaming + reasoning, no text    → Thinking…
//   streaming + text present          → Responding…   (the text itself shows;
//                                                       the line stays subtle)
//   streaming, nothing yet            → Thinking…
// ──────────────────────────────────────────────────────────────

type ChatStatus = 'submitted' | 'streaming' | 'ready' | 'error'

const STALL_MS = 3000

type Phase =
  | { kind: 'requesting' }
  | { kind: 'thinking' }
  | { kind: 'responding' }
  | { kind: 'tool'; toolName: string }

/** Derive the live phase from the raw status + the last assistant message's
 * parts. Pure so it can be unit-tested without timers. */
function derivePhase(status: ChatStatus, messages: UIMessage[]): Phase {
  if (status === 'submitted') return { kind: 'requesting' }

  // status === 'streaming' (the indicator only renders while isLoading)
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const parts = lastAssistant?.parts ?? []

  // A tool whose output hasn't landed yet is the most concrete in-flight signal.
  for (let i = parts.length - 1; i >= 0; i--) {
    const part = parts[i]
    if (!isToolUIPart(part)) continue
    const anyPart = part as DynamicToolUIPart
    if (anyPart.state === 'input-streaming' || anyPart.state === 'input-available') {
      return { kind: 'tool', toolName: anyPart.toolName ?? part.type.replace(/^tool-/, '') }
    }
  }

  const hasText = parts.some((p) => isTextUIPart(p) && p.text.length > 0)
  if (hasText) return { kind: 'responding' }

  const hasReasoning = parts.some((p) => isReasoningUIPart(p) && (p.text ?? '').length > 0)
  if (hasReasoning) return { kind: 'thinking' }

  return { kind: 'thinking' }
}

/** A signature of the last assistant message's content. Grows whenever the
 * model emits more text/reasoning or a tool part changes state — i.e. exactly
 * when "new content arrived". Drives the stall detector's lastContentChange. */
function contentSignature(status: ChatStatus, messages: UIMessage[]): string {
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const parts = lastAssistant?.parts ?? []
  let textLen = 0
  let reasoningLen = 0
  const toolStates: string[] = []
  for (const part of parts) {
    if (isTextUIPart(part)) textLen += part.text.length
    else if (isReasoningUIPart(part)) reasoningLen += (part.text ?? '').length
    else if (isToolUIPart(part)) toolStates.push((part as DynamicToolUIPart).state ?? '')
  }
  return `${status}|${messages.length}|${textLen}|${reasoningLen}|${toolStates.join(',')}`
}

function StatusIndicator({
  status,
  messages,
}: {
  status: ChatStatus
  messages: UIMessage[]
}): React.ReactElement {
  const { t } = useI18n()

  // Turn start = mount (the indicator only mounts while isLoading is true, and
  // unmounts when it flips false, so mount/unmount == the turn boundary and the
  // elapsed counter resets per turn for free).
  const turnStart = useRef(Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    // Tick at 500ms so the stall flips red close to the ~3s threshold (a 1s
    // cadence would only catch it at 4s); the elapsed counter still floors to
    // whole seconds, so the displayed number ticks once per second.
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [])

  const phase = derivePhase(status, messages)

  // Stall detector: track when content last grew; if no growth for >3s AND no
  // tool is in flight, surface the honest red "still waiting" affordance. A
  // running tool legitimately produces no chat content for a while, so it
  // suppresses the stall flag.
  const sig = contentSignature(status, messages)
  const lastContentChange = useRef(Date.now())
  const lastSig = useRef(sig)
  if (lastSig.current !== sig) {
    lastSig.current = sig
    lastContentChange.current = Date.now()
  }
  const toolRunning = phase.kind === 'tool'
  const stalled = !toolRunning && now - lastContentChange.current > STALL_MS

  const elapsed = Math.max(0, Math.floor((now - turnStart.current) / 1000))

  let label: string
  switch (phase.kind) {
    case 'requesting':
      label = t('chat.status.requesting')
      break
    case 'tool':
      label = t('chat.status.running', { tool: phase.toolName })
      break
    case 'responding':
      label = t('chat.status.responding')
      break
    case 'thinking':
    default:
      label = t('chat.thinking')
      break
  }

  return (
    <div data-testid="thinking-indicator" className="msg agent">
      <div className="msg-head">● FINROBOT</div>
      <div
        data-testid="status-line"
        data-phase={phase.kind}
        data-stalled={stalled ? 'true' : 'false'}
        className={`ai-status${stalled ? ' stalled' : ''}`}
      >
        <span className="ai-status-dot" aria-hidden="true" />
        <span className="ai-status-label">{stalled ? t('chat.status.stalled') : label}</span>
        <span className="ai-status-elapsed">{elapsed}s</span>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// AiInputArea — .ai-input-wrap (Phase 4 rewrite)
// ──────────────────────────────────────────────────────────────

interface AiInputAreaProps {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  isLoading: boolean
  onStop: () => void
  onReload: () => void
  error: Error | undefined
  hasMessages: boolean
}

function AiInputArea({
  value,
  onChange,
  onSubmit,
  isLoading,
  onStop,
  onReload,
  error,
  hasMessages,
}: AiInputAreaProps): React.ReactElement {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isOverLimit = value.length > MAX_INPUT_LENGTH
  const isEmpty = value.trim().length === 0
  const { t } = useI18n()

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [value])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key !== 'Enter') return
    // 中文输入法选词时按 Enter 不能触发提交（关键 IME 兼容）
    if (e.nativeEvent.isComposing || e.keyCode === 229) return
    if (e.shiftKey) return // Shift+Enter 换行
    e.preventDefault()
    if (!isEmpty && !isOverLimit && !isLoading) onSubmit()
  }

  return (
    <div data-testid="input-area" className="ai-input-wrap">
      {/* Error banner */}
      {error && !isLoading && (
        <div
          data-testid="error-banner"
          style={{
            marginBottom: '8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '6px 10px',
            background: 'color-mix(in srgb, var(--danger) 10%, transparent)',
            borderRadius: '4px',
            fontSize: '11px',
            color: 'var(--danger)',
          }}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {isContextOverflowError(error.message)
              ? t('chat.error.context')
              : t('chat.error.generic')}
          </span>
          {hasMessages && (
            <button
              data-testid="reload-btn"
              onClick={onReload}
              style={{
                marginLeft: '8px',
                flexShrink: 0,
                padding: '2px 8px',
                fontSize: '11px',
                background: 'var(--bg-3)',
                border: '1px solid var(--line-bright)',
                borderRadius: '3px',
                color: 'var(--text-1)',
                cursor: 'pointer',
              }}
              type="button"
            >
              {t('chat.retry')}
            </button>
          )}
        </div>
      )}

      {/* Input box */}
      <div className="ai-input-box">
        <textarea
          ref={textareaRef}
          data-testid="chat-input"
          className="ai-textarea"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('chat.input.placeholder')}
          rows={2}
          disabled={isLoading}
          aria-label={t('chat.input.placeholder')}
        />

        {isOverLimit && (
          <div
            data-testid="overlength-warning"
            style={{
              padding: '0 12px 6px',
              fontSize: '11px',
              color: 'var(--danger)',
            }}
          >
            {t('chat.overlength', {
              count: value.length.toLocaleString(),
              max: MAX_INPUT_LENGTH.toLocaleString(),
            })}
          </div>
        )}

        <div className="ai-input-bar">
          {/* The placeholder already states Enter-sends / Shift+Enter-newline
              (the app has no other keyboard shortcuts), so the bar stays a
              single clear send affordance. */}
          <div className="spacer" />

          {/* 发送 / 停止 */}
          {isLoading ? (
            <button
              data-testid="stop-btn"
              onClick={onStop}
              className="send stop"
              type="button"
              title={t('chat.stop')}
              aria-label={t('chat.stop')}
            >
              <span
                style={{
                  width: 11,
                  height: 11,
                  background: 'var(--text-on-primary)',
                  borderRadius: 2,
                }}
              />
            </button>
          ) : (
            <button
              data-testid="send-btn"
              onClick={onSubmit}
              disabled={isEmpty || isOverLimit}
              className="send"
              type="button"
              title={t('chatpanel.send.title')}
              aria-label={t('chat.send')}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Character count hint */}
      {value.length > MAX_INPUT_LENGTH * 0.8 && !isOverLimit && (
        <div
          style={{
            marginTop: '4px',
            textAlign: 'right',
            fontSize: '11px',
            color: 'var(--warning)',
          }}
        >
          {value.length.toLocaleString()} / {MAX_INPUT_LENGTH.toLocaleString()}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// IconColumn (collapsed state)
// ──────────────────────────────────────────────────────────────

interface IconColumnProps {
  onToggle: () => void
  unreadCount: number
  onNewSession: () => void
}

function IconColumn({ onToggle, unreadCount, onNewSession }: IconColumnProps): React.ReactElement {
  const [showMenu, setShowMenu] = useState(false)
  const [longPressTimer, setLongPressTimer] = useState<ReturnType<typeof setTimeout> | null>(null)
  const { t } = useI18n()

  const handlePointerDown = (): void => {
    const timer = setTimeout(() => {
      setShowMenu(true)
    }, 600)
    setLongPressTimer(timer)
  }

  const handlePointerUp = (): void => {
    if (longPressTimer) {
      clearTimeout(longPressTimer)
      setLongPressTimer(null)
    }
  }

  // Desktop-friendly: right-click opens the menu; left-click expands the panel.
  const handleContextMenu = (e: React.MouseEvent): void => {
    e.preventDefault()
    setShowMenu(true)
  }

  return (
    <aside data-testid="icon-column" className="ai-icon-column">
      <div style={{ position: 'relative' }}>
        <button
          data-testid="expand-btn"
          onClick={onToggle}
          onContextMenu={handleContextMenu}
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          title={t('chat.expand')}
          className="ai-icon-column-btn"
          type="button"
        >
          <span style={{ fontSize: '14px' }}>◈</span>
        </button>

        {unreadCount > 0 && (
          <span data-testid="unread-badge" className="ai-icon-column-badge">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </div>

      {showMenu && (
        <div
          data-testid="icon-menu"
          className="ai-icon-menu"
          onMouseLeave={() => setShowMenu(false)}
        >
          <button
            className="ai-icon-menu-item"
            onClick={() => {
              onToggle()
              setShowMenu(false)
            }}
            type="button"
          >
            {t('chat.expand')}
          </button>
          <button
            className="ai-icon-menu-item"
            onClick={() => {
              onNewSession()
              setShowMenu(false)
            }}
            type="button"
          >
            {t('chat.newSession')}
          </button>
          <button
            className="ai-icon-menu-item"
            style={{ color: 'var(--text-3)' }}
            onClick={() => setShowMenu(false)}
            type="button"
          >
            {t('common.cancel')}
          </button>
        </div>
      )}
    </aside>
  )
}
