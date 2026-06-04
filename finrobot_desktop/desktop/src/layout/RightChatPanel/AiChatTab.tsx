// AiChatTab — chat body of the right panel (cosmic Stage A split).
//
// Was: the entire RightChatPanel (outer aside + expand/collapse + chat).
// Now: chat content only; the aside + expand + tab toggle live in
// RightChatPanel/index.tsx. This file owns the per-ticker chat session,
// the model picker header, ContextBar, message list, suggestion chips,
// and the input area.

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useLocation } from 'react-router-dom'
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
import { fetchWithTimeout } from '../../api/fetch'
import { IconClock } from '../../lib/icons'
import { ContextBar } from '../AIPanel/ContextBar'

// ──────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────

const MAX_INPUT_LENGTH = 20_000

// ──────────────────────────────────────────────────────────────
// Context-aware suggestion chips per route
// ──────────────────────────────────────────────────────────────

// Suggestion chips per route. Patterns are tested in order; first match
// wins. The artifact-detail surface gets its own report-aware chips so the
// AI panel suggests questions about *this* report rather than the workspace
// generic ones.
// Chips carry i18n keys; the literal prompt text is resolved per-locale in
// the component (routeChips useMemo) so switching language re-renders them.
//
// HONESTY RULE (BUG-20260602-046): a chip may only suggest a workflow the lead
// agent can actually perform. Chips are *prompt shortcuts*, not typed actions —
// clicking one only fills the input box. So we keep chips whose intent the
// agent can satisfy with its registered tools (run_dcf_valuation /
// run_comps_analysis / run_equity_research → dcf / peers / catalysts) or with a
// plain answer (apiStatus, general landing questions). We REMOVED chips that
// implied a dedicated tool the agent does NOT have:
//   - report "diff"          (no artifact-diff tool registered on /chat)
//   - ticker "Monte Carlo"   (no monte-carlo tool on /chat)
//   - ticker "10-K Q&A"      (RAG Q&A exists in qa.py but is NOT a /chat tool)
//   - settings "coverage"    (no coverage-introspection tool)
// so the UI never promises a workflow that silently degrades to "let the model
// guess".
const ROUTE_CHIP_PATTERNS: Array<{ test: (path: string) => boolean; chipKeys: string[] }> = [
  // /stocks/:ticker/runs/:artifactId — 13-chapter report detail
  {
    test: (p) => /^\/stocks\/[^/]+\/runs\//.test(p),
    chipKeys: [
      'chatpanel.chip.report.dcf',
      'chatpanel.chip.report.peers',
      'chatpanel.chip.report.catalysts',
    ],
  },
  // /stocks/:ticker — ticker workspace
  {
    test: (p) => /^\/stocks\/[^/]+$/.test(p),
    chipKeys: ['chatpanel.chip.ticker.dcf', 'chatpanel.chip.ticker.peers'],
  },
  // /stocks landing
  {
    test: (p) => p === '/stocks',
    chipKeys: [
      'chatpanel.chip.landing.search',
      'chatpanel.chip.landing.methods',
      'chatpanel.chip.landing.howto',
    ],
  },
  // /settings
  {
    test: (p) => p.startsWith('/settings'),
    chipKeys: ['chatpanel.chip.settings.apiStatus'],
  },
]

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

  // Per-ticker session map so switching ticker preserves prior conversations.
  const sessionMapRef = useRef<Map<string, string>>(new Map())
  const sessionKey = ticker ?? '__explore__'
  const getOrCreateSession = useCallback((key: string): string => {
    const map = sessionMapRef.current
    let id = map.get(key)
    if (!id) {
      id = crypto.randomUUID()
      map.set(key, id)
    }
    return id
  }, [])

  const [sessionId, setSessionId] = useState<string>(() => getOrCreateSession(sessionKey))
  const [inputText, setInputText] = useState('')

  // History drawer (BUG-20260602-045): past sessions are written to disk but
  // had no UI to reopen them. This drawer lists them via /api/chat/sessions.
  const [historyOpen, setHistoryOpen] = useState(false)

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
          return {
            ticker: ticker ?? null,
            model: configuredModel ?? 'unknown',
            locale: useUiPrefs.getState().locale,
            context_bundle,
          }
        },
      }),
    [ticker, configuredModel],
  )

  const { messages, status, error, sendMessage, stop, regenerate, clearError } = useChat({
    id: sessionId,
    transport,
    onError(err) {
      const msg = err.message ?? ''
      if (msg.includes('context') || msg.includes('token')) {
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

  // Ticker change → switch session.
  useEffect(() => {
    setSessionId(getOrCreateSession(sessionKey))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionKey])

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

  const startNewSession = useCallback(() => {
    const id = crypto.randomUUID()
    sessionMapRef.current.set(sessionKey, id)
    setSessionId(id)
    setInputText('')
  }, [sessionKey])

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

  // ── Route-aware chips ────────────────────────────────────────
  const location = useLocation()
  const routeChips = useMemo((): string[] => {
    const match = ROUTE_CHIP_PATTERNS.find((p) => p.test(location.pathname))
    return match ? match.chipKeys.map((k) => t(k)) : []
  }, [location.pathname, t])

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
        onNewSession={startNewSession}
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
      style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}
    >
      <AiPanelHeader
        modelLabel={modelLabel(configuredModel, settings?.providers)}
        onToggle={handleToggle}
        onNewSession={startNewSession}
        onOpenHistory={() => setHistoryOpen(true)}
        ticker={ticker}
      />

      {historyOpen && <HistoryDrawer ticker={ticker} onClose={() => setHistoryOpen(false)} />}

      <ContextBar />

      <MessageList
        messages={messages}
        isLoading={isLoading}
        ticker={ticker}
        onExample={setInputText}
      />

      {routeChips.length > 0 && <SuggestionChips chips={routeChips} onSelect={setInputText} />}

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
// HistoryDrawer — past chat sessions (BUG-20260602-045)
//
// Chat transcripts are side-logged to disk by /chat but had no read path. This
// drawer lists them via GET /api/chat/sessions (filtered to the current ticker
// when one is focused) and renders a selected session's transcript read-only
// via GET /api/chat/sessions/{id}. Modest by design: list + view, no editing.
// ──────────────────────────────────────────────────────────────

interface SessionSummary {
  session_id: string
  title: string
  created_at: string
  last_active_at: string
  turn_count: number
  model: string
  user_id: string
  ticker: string | null
}

interface TranscriptEvent {
  timestamp: string
  session_id: string
  event: string
  data: Record<string, unknown>
}

async function fetchSessions(ticker: string | undefined): Promise<SessionSummary[]> {
  const qs = ticker ? `?ticker=${encodeURIComponent(ticker)}` : ''
  const res = await fetchWithTimeout(`${BASE_URL}/api/chat/sessions${qs}`)
  if (!res.ok) throw new Error(`sessions ${res.status}`)
  const body = (await res.json()) as { sessions: SessionSummary[] }
  return body.sessions
}

async function fetchTranscript(sessionId: string): Promise<TranscriptEvent[]> {
  const res = await fetchWithTimeout(
    `${BASE_URL}/api/chat/sessions/${encodeURIComponent(sessionId)}`,
  )
  if (!res.ok) throw new Error(`transcript ${res.status}`)
  const body = (await res.json()) as { events: TranscriptEvent[] }
  return body.events
}

function HistoryDrawer({
  ticker,
  onClose,
}: {
  ticker: string | undefined
  onClose: () => void
}): React.ReactElement {
  const { locale } = useI18n()
  const zh = locale === 'zh'
  const [selected, setSelected] = useState<string | null>(null)

  const {
    data: sessions,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['chat-sessions', ticker ?? null],
    queryFn: () => fetchSessions(ticker),
    staleTime: 0,
  })

  const { data: transcript } = useQuery({
    queryKey: ['chat-transcript', selected],
    queryFn: () => fetchTranscript(selected as string),
    enabled: selected != null,
  })

  const emptyStyle: React.CSSProperties = {
    padding: '16px 12px',
    fontSize: '11px',
    color: 'var(--text-3)',
    textAlign: 'center',
  }

  return (
    <div
      data-testid="history-drawer"
      style={{
        display: 'flex',
        flexDirection: 'column',
        maxHeight: '50%',
        minHeight: 0,
        borderBottom: '1px solid var(--line-bright)',
        background: 'var(--bg-2)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '6px 10px',
          borderBottom: '1px solid var(--line)',
        }}
      >
        <span
          style={{
            flex: 1,
            fontSize: '11px',
            fontWeight: 600,
            color: 'var(--text-2)',
            letterSpacing: '0.04em',
          }}
        >
          {selected ? (zh ? '查看会话' : 'Viewing session') : zh ? '历史会话' : 'Chat history'}
        </span>
        {selected && (
          <button
            className="ai-icon-btn"
            onClick={() => setSelected(null)}
            type="button"
            title={zh ? '返回列表' : 'Back to list'}
          >
            ←
          </button>
        )}
        <button
          data-testid="history-close-btn"
          className="ai-icon-btn"
          onClick={onClose}
          type="button"
          title={zh ? '关闭' : 'Close'}
        >
          ×
        </button>
      </div>

      <div style={{ overflowY: 'auto', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {selected ? (
          <HistoryTranscript events={transcript ?? []} locale={locale} />
        ) : isLoading ? (
          <div style={emptyStyle}>{zh ? '加载中…' : 'Loading…'}</div>
        ) : isError ? (
          <div style={emptyStyle}>{zh ? '无法加载历史会话。' : 'Could not load chat history.'}</div>
        ) : !sessions || sessions.length === 0 ? (
          <div data-testid="history-empty" style={emptyStyle}>
            {zh
              ? '还没有历史会话。在右侧开始对话后会出现在这里。'
              : 'No past sessions yet. Conversations you have here will show up in this list.'}
          </div>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: '4px' }}>
            {sessions.map((s) => (
              <li key={s.session_id}>
                <button
                  onClick={() => setSelected(s.session_id)}
                  type="button"
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '2px',
                    width: '100%',
                    textAlign: 'left',
                    padding: '7px 8px',
                    background: 'transparent',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    color: 'var(--text-1)',
                  }}
                >
                  <span
                    style={{
                      fontSize: '12px',
                      color: 'var(--text-1)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {s.title}
                  </span>
                  <span
                    style={{
                      fontSize: '10px',
                      color: 'var(--text-3)',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    {s.ticker ? `${s.ticker} · ` : ''}
                    {zh
                      ? `${s.turn_count} 轮对话`
                      : `${s.turn_count} ${s.turn_count === 1 ? 'turn' : 'turns'}`}
                    {' · '}
                    {formatHistoryDate(s.last_active_at, locale)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function HistoryTranscript({
  events,
  locale,
}: {
  events: TranscriptEvent[]
  locale: string
}): React.ReactElement {
  const turns = events.filter((e) => e.event === 'user_msg' || e.event === 'assistant_text')
  if (turns.length === 0) {
    return (
      <div
        style={{
          padding: '16px 12px',
          fontSize: '11px',
          color: 'var(--text-3)',
          textAlign: 'center',
        }}
      >
        {locale === 'zh' ? '该会话没有可显示的消息。' : 'No messages in this session.'}
      </div>
    )
  }
  return (
    <div className="ai-messages" style={{ flex: 1 }}>
      {turns.map((e, i) => {
        const isUser = e.event === 'user_msg'
        const text = typeof e.data.text === 'string' ? e.data.text : ''
        return (
          <div key={i} className={`msg ${isUser ? 'user' : 'agent'}`}>
            <div className="msg-head">{isUser ? 'USER' : '● FINROBOT'}</div>
            <div className="msg-body">{isUser ? text : <MarkdownLite text={text} />}</div>
          </div>
        )
      })}
    </div>
  )
}

function formatHistoryDate(iso: string, locale: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ──────────────────────────────────────────────────────────────
// SuggestionChips — context-aware prompt shortcuts
// ──────────────────────────────────────────────────────────────

interface SuggestionChipsProps {
  chips: string[]
  onSelect: (chip: string) => void
}

function SuggestionChips({ chips, onSelect }: SuggestionChipsProps): React.ReactElement {
  return (
    <div className="ai-chips" data-testid="suggestion-chips">
      {chips.map((chip) => (
        <button
          key={chip}
          className="ai-chip"
          onClick={() => onSelect(chip)}
          type="button"
          title={chip}
        >
          {chip}
        </button>
      ))}
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
}

function AiPanelHeader({
  modelLabel,
  onToggle,
  onNewSession,
  onOpenHistory,
  ticker,
}: AiPanelHeaderProps): React.ReactElement {
  const { t, locale } = useI18n()

  return (
    <div className="ai-header" data-testid="panel-header">
      {/* Logo mark */}
      <div className="ai-icon">F</div>
      <div className="ai-title">FinRobot</div>
      {/* ticker or '探索' label — both used by tests */}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '10px',
          color: ticker ? 'var(--accent)' : 'var(--text-3)',
          letterSpacing: '0.05em',
        }}
      >
        {ticker ?? t('chat.title.explore')}
      </span>

      {/* Model badge (read-only — model configured in Settings) */}
      <span
        data-testid="model-selector"
        className="ai-model"
        title={t('chatpanel.model.configuredInSettings')}
        style={{ cursor: 'default' }}
      >
        {modelLabel}
      </span>

      {/* History — past sessions */}
      <button
        data-testid="history-btn"
        onClick={onOpenHistory}
        title={locale === 'zh' ? '历史会话' : 'Chat history'}
        className="ai-icon-btn"
        type="button"
      >
        <IconClock size={13} />
      </button>

      {/* New session */}
      <button
        data-testid="new-session-btn"
        onClick={onNewSession}
        title={t('chat.newSession')}
        className="ai-icon-btn"
        style={{ fontSize: '13px' }}
        type="button"
      >
        +
      </button>

      {/* Close / collapse */}
      <button
        data-testid="collapse-btn"
        onClick={onToggle}
        title={t('chat.collapse')}
        className="ai-icon-btn"
        type="button"
      >
        ×
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
  ticker: string | undefined
  onExample: (prompt: string) => void
}

function MessageList({
  messages,
  isLoading,
  ticker,
  onExample,
}: MessageListProps): React.ReactElement {
  const bottomRef = useRef<HTMLDivElement>(null)
  const { t } = useI18n()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0 && !isLoading) {
    const examples = ticker
      ? [
          t('chat.empty.example.1', { ticker }),
          t('chat.empty.example.2', { ticker }),
          t('chat.empty.example.3', { ticker }),
        ]
      : [
          t('chat.empty.example.generic.1'),
          t('chat.empty.example.generic.2'),
          t('chat.empty.example.generic.3'),
        ]
    return (
      <div
        data-testid="empty-state"
        className="ai-messages"
        style={{ justifyContent: 'center', alignItems: 'center', gap: '12px' }}
      >
        <div style={{ textAlign: 'center', color: 'var(--text-3)' }}>
          <div style={{ fontSize: '20px', marginBottom: '6px' }}>◈</div>
          <div style={{ fontSize: '12px', color: 'var(--text-2)' }}>{t('chat.empty.heading')}</div>
          <div style={{ fontSize: '11px', color: 'var(--text-3)', marginTop: '4px' }}>
            {t('chat.empty.body')}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', width: '100%' }}>
          {examples.map((ex) => (
            <button
              key={ex}
              onClick={() => onExample(ex)}
              style={{
                background: 'var(--bg-2)',
                border: '1px solid var(--line-bright)',
                borderRadius: '4px',
                padding: '7px 10px',
                textAlign: 'left',
                fontSize: '11px',
                color: 'var(--text-2)',
                cursor: 'pointer',
                fontFamily: 'var(--font-ui)',
              }}
              type="button"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div data-testid="message-list" className="ai-messages">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}

      {isLoading && <ThinkingIndicator />}

      <div ref={bottomRef} />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// MessageBubble — .msg
// ──────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: UIMessage }): React.ReactElement {
  const isUser = message.role === 'user'
  // Read the SDK-supplied createdAt instead of new Date() — the latter
  // re-runs on every render so all historical messages would show "now".
  // The ai SDK v1 UIMessage type stopped surfacing `createdAt` at the
  // root and moved per-message extras into the typed `metadata` slot.
  // useChat() doesn't parameterise metadata, so the field is reachable
  // only via a narrowed read. Old messages persisted before any sender
  // populated this will be undefined; formatMessageTime drops them
  // rather than fabricating "now".
  const createdAt = (message as UIMessage & { createdAt?: string | Date | undefined }).createdAt
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
      const o = rawOutput as { summary?: string; artifact_id?: string; ticker?: string }
      result = {
        summary: o.summary ?? '',
        artifact_id: o.artifact_id,
        ticker: o.ticker,
      }
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

function ThinkingIndicator(): React.ReactElement {
  return (
    <div data-testid="thinking-indicator" className="msg agent">
      <div className="msg-head">● FINROBOT</div>
      <div className="msg-body" style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
        <span
          style={{
            display: 'inline-block',
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: 'var(--accent)',
            animation: 'blink 1s 0ms infinite',
          }}
        />
        <span
          style={{
            display: 'inline-block',
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: 'var(--accent)',
            animation: 'blink 1s 150ms infinite',
          }}
        />
        <span
          style={{
            display: 'inline-block',
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: 'var(--accent)',
            animation: 'blink 1s 300ms infinite',
          }}
        />
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
            {error.message.includes('context') || error.message.includes('token')
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
          <div className="spacer" />

          {/* 发送 / 停止 */}
          {isLoading ? (
            <button
              data-testid="stop-btn"
              onClick={onStop}
              style={{
                padding: '5px 11px',
                borderRadius: '4px',
                background: 'color-mix(in srgb, var(--danger) 15%, transparent)',
                border: '1px solid color-mix(in srgb, var(--danger) 30%, transparent)',
                color: 'var(--danger)',
                fontSize: '10px',
                fontFamily: 'var(--font-mono)',
                cursor: 'pointer',
                fontWeight: 700,
                letterSpacing: '0.05em',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
              }}
              type="button"
            >
              ■ {t('chat.stop')}
            </button>
          ) : (
            <button
              data-testid="send-btn"
              onClick={onSubmit}
              disabled={isEmpty || isOverLimit}
              className="send"
              style={{
                opacity: isEmpty || isOverLimit ? 0.45 : 1,
                cursor: isEmpty || isOverLimit ? 'not-allowed' : 'pointer',
              }}
              type="button"
              title={t('chatpanel.send.title')}
            >
              {t('chat.send')}
              <span className="kbd">↵</span>
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
