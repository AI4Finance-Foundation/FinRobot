// AiChatTab — chat body of the right panel (cosmic Stage A split).
//
// Was: the entire RightChatPanel (outer aside + expand/collapse + chat).
// Now: chat content only; the aside + expand + tab toggle live in
// RightChatPanel/index.tsx. This file owns the per-ticker chat session,
// the model picker header, ContextBar, message list, suggestion chips,
// and the input area.

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useLocation, useNavigate } from 'react-router-dom'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { UIMessage, UIMessagePart, UIDataTypes, UITools, DynamicToolUIPart } from 'ai'
import { isTextUIPart, isToolUIPart, isReasoningUIPart } from 'ai'
import { useToastStore } from '../../stores/toastStore'
import { useUiStore } from '../../stores/uiStore'
import { ToolCard } from '../../components/ToolCard'
import type { ToolResult } from '../../components/ToolCard'
import { MarkdownLite } from '../../components/MarkdownLite'
import { useI18n } from '../../i18n'
import { BASE_URL } from '../../api/client'
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
const ROUTE_CHIP_PATTERNS: Array<{ test: (path: string) => boolean; chips: string[] }> = [
  // /stocks/:ticker/runs/:artifactId — 12-chapter report detail
  {
    test: (p) => /^\/stocks\/[^/]+\/runs\//.test(p),
    chips: [
      '解释这份研报的 DCF 假设',
      '对比同期竞争对手估值',
      '哪些催化剂最值得跟踪',
      '与上一版有何差异',
    ],
  },
  // /stocks/:ticker — ticker workspace
  {
    test: (p) => /^\/stocks\/[^/]+$/.test(p),
    chips: ['解释 DCF 假设', '对比同业竞争', '蒙特卡洛模拟', '10-K 问答'],
  },
  // /stocks landing
  {
    test: (p) => p === '/stocks',
    chips: ['搜一个新股票', '解释 DCF / LBO / Comps', 'FinAgent 怎么用'],
  },
  // /settings
  {
    test: (p) => p.startsWith('/settings'),
    chips: ['检查 API 状态', '数据覆盖范围'],
  },
]

// ──────────────────────────────────────────────────────────────
// MODELS — aligned to prototype.  Legacy values 'deepseek' / 'anthropic' / 'openai'
// are preserved as aliases so existing tests and persisted uiStore values keep
// working.  AppShell-level UI shows the "human" label; value is sent to backend.
const MODELS = [
  { value: 'deepseek', label: 'DeepSeek Chat' },
  { value: 'qwen-max', label: 'Qwen Max' },
  { value: 'anthropic', label: 'Claude Sonnet' },
  { value: 'gpt-4o', label: 'GPT-4o' },
] as const

type ModelValue = (typeof MODELS)[number]['value']

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

  // ── uiStore bindings ────────────────────────────────────────
  const storeOpen = useUiStore((s) => s.aiPanelOpen)
  const storeWidth = useUiStore((s) => s.aiPanelWidth)
  const storeModel = useUiStore((s) => s.currentModel)
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

  // Track unread for collapsed state
  const [unreadCount, setUnreadCount] = useState(0)
  const lastSeenMessageCountRef = useRef(0)

  const modelValue: ModelValue = MODELS.some((m) => m.value === storeModel)
    ? (storeModel as ModelValue)
    : 'deepseek'

  // Transport — recreated when ticker/model changes. Absolute URL is
  // required in Tauri prod builds (asset loads from `file://` so a
  // relative `/chat` resolves to a non-existent file scheme path and the
  // entire AI panel falls silent). Dev keeps `''` so Vite proxies it.
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `${BASE_URL}/chat`,
        body: { ticker: ticker ?? null, model: modelValue },
      }),
    [ticker, modelValue],
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
    return match ? match.chips : []
  }, [location.pathname])

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
        modelValue={modelValue}
        onToggle={handleToggle}
        onNewSession={startNewSession}
        ticker={ticker}
      />

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
  modelValue: ModelValue
  onToggle: () => void
  onNewSession: () => void
  ticker: string | undefined
}

function AiPanelHeader({
  modelValue,
  onToggle,
  onNewSession,
  ticker,
}: AiPanelHeaderProps): React.ReactElement {
  const { t } = useI18n()

  return (
    <div className="ai-header" data-testid="panel-header">
      {/* Logo mark */}
      <div className="ai-icon">F</div>
      <div className="ai-title">FinAgent</div>
      {/* ticker or '探索' label — both used by tests */}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '10px',
          color: ticker ? 'var(--accent)' : 'var(--text-3)',
          letterSpacing: '0.05em',
        }}
      >
        {ticker ?? '探索'}
      </span>

      {/* Model badge (read-only — model configured in Settings) */}
      <span
        data-testid="model-selector"
        className="ai-model"
        title="模型在 Settings 中配置"
        style={{ cursor: 'default' }}
      >
        {MODELS.find((m) => m.value === modelValue)?.label ?? modelValue}
      </span>

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
            ? `● FINAGENT · ${timeStr}`
            : '● FINAGENT'}
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
      <div className="msg-head">● FINAGENT</div>
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
            background: 'rgba(248,113,113,0.1)',
            borderRadius: '4px',
            fontSize: '11px',
            color: 'var(--red)',
          }}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {error.message.includes('context') || error.message.includes('token')
              ? '对话过长，请开启新对话。'
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
          placeholder="向 FinAgent 提问 · ↵ 发送 · ⇧↵ 换行"
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
              color: 'var(--red)',
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
                background: 'rgba(248,113,113,0.15)',
                border: '1px solid rgba(248,113,113,0.3)',
                color: 'var(--red)',
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
              title="发送 (↵ · Shift+↵ 换行)"
            >
              发送
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
  const navigate = useNavigate()

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
            onClick={() => {
              navigate('/stocks')
              setShowMenu(false)
            }}
            type="button"
          >
            {t('chat.history')}
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
