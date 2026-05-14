// RightChatPanel — Phase 4 rewrite.
//
// Visual: amber theme, 420px, aligned 1:1 to finagent.html prototype.
// State:  useUiStore (aiPanelOpen / aiPanelWidth / mode / currentModel /
//         contextBundle) replaces useUiPrefs.chatExpanded.
//
// Props:  expanded / onToggle are kept for backward-compatibility with
//         existing tests. AppShell passes no props (0-arg call); tests
//         still inject them and they still work — see "prop override"
//         logic below.

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { UIMessage, UIMessagePart, UIDataTypes, UITools, DynamicToolUIPart } from 'ai'
import { isTextUIPart, isToolUIPart, isReasoningUIPart } from 'ai'
import { useToastStore } from '../stores/toastStore'
import { useUiStore } from '../stores/uiStore'
import type { AgentMode } from '../stores/uiStore'
import { ToolCard } from '../components/ToolCard'
import type { ToolResult } from '../components/ToolCard'
import { MarkdownLite } from '../components/MarkdownLite'
import { useI18n } from '../i18n'
import { ContextBar } from './AIPanel/ContextBar'
import { PIPELINES } from '../lib/pipelines'
import {
  IconPaperclip,
  IconTool,
  IconClock,
} from '../lib/icons'

// ──────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────

const MAX_INPUT_LENGTH = 20_000

// MODELS — aligned to prototype.  Legacy values 'deepseek' / 'anthropic' / 'openai'
// are preserved as aliases so existing tests and persisted uiStore values keep
// working.  AppShell-level UI shows the "human" label; value is sent to backend.
const MODELS = [
  { value: 'deepseek',          label: 'DeepSeek Chat' },
  { value: 'qwen-max',          label: 'Qwen Max' },
  { value: 'anthropic',         label: 'Claude Sonnet' },
  { value: 'gpt-4o',            label: 'GPT-4o' },
] as const

type ModelValue = (typeof MODELS)[number]['value']

// ──────────────────────────────────────────────────────────────
// RightChatPanel props (kept for test backward-compatibility)
// ──────────────────────────────────────────────────────────────

interface RightChatPanelProps {
  /** When provided by tests/legacy callers, overrides uiStore.aiPanelOpen. */
  expanded?: boolean
  /** When provided by tests/legacy callers, called instead of uiStore.toggleAiPanel. */
  onToggle?: () => void
}

// ──────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────

export function RightChatPanel({
  expanded: expandedProp,
  onToggle: onToggleProp,
}: RightChatPanelProps = {}): React.ReactElement {
  const { ticker } = useParams<{ ticker?: string }>()
  const addToast = useToastStore((s) => s.addToast)
  const { t } = useI18n()

  // ── uiStore bindings ────────────────────────────────────────
  const storeOpen       = useUiStore((s) => s.aiPanelOpen)
  const storeWidth      = useUiStore((s) => s.aiPanelWidth)
  const storeMode       = useUiStore((s) => s.mode)
  const storeModel      = useUiStore((s) => s.currentModel)
  const toggleAiPanel   = useUiStore((s) => s.toggleAiPanel)
  const setAiPanelWidth = useUiStore((s) => s.setAiPanelWidth)
  const setStoreMode    = useUiStore((s) => s.setMode)
  const setStoreModel   = useUiStore((s) => s.setCurrentModel)
  const openTab         = useUiStore((s) => s.openTab)

  // Prop-override: if caller supplies expanded/onToggle, use those.
  // Otherwise fall through to uiStore.
  const isExpanded  = expandedProp !== undefined ? expandedProp  : storeOpen
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

  const [sessionId, setSessionId] = useState<string>(() =>
    getOrCreateSession(sessionKey),
  )
  const [inputText, setInputText] = useState('')
  const [toolActive, setToolActive] = useState(true)
  const [thinkActive, setThinkActive] = useState(false)

  // Track unread for collapsed state
  const [unreadCount, setUnreadCount] = useState(0)
  const lastSeenMessageCountRef = useRef(0)

  // local model state for test/legacy compat when expanded prop is injected
  const [localModel, setLocalModel] = useState<ModelValue>('anthropic')

  // When caller provides expanded prop (legacy / test mode), use local model.
  // When controlled by uiStore, use storeModel.
  const modelValue: ModelValue =
    expandedProp !== undefined
      ? localModel
      : MODELS.some((m) => m.value === storeModel)
        ? (storeModel as ModelValue)
        : 'deepseek'

  const handleModelChange = (m: ModelValue): void => {
    if (expandedProp !== undefined) {
      setLocalModel(m)
    } else {
      setStoreModel(m)
    }
  }

  // Transport — recreated when ticker/model changes
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: '/chat',
        body: { ticker: ticker ?? null, model: modelValue },
      }),
    [ticker, modelValue],
  )

  const { messages, status, error, sendMessage, stop, regenerate, clearError } =
    useChat({
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
      lastSeenMessageCountRef.current = messages.filter(
        (m) => m.role === 'assistant',
      ).length
      setUnreadCount(0)
    }
  }, [messages, isExpanded])

  // ── Submit handler ──────────────────────────────────────────
  const handleSubmit = useCallback(() => {
    const text = inputText.trim()
    if (!text) return
    if (text.length > MAX_INPUT_LENGTH) return
    if (isLoading) return

    // MODE B: parse PL-XXX and/or ticker → open pipeline tab
    if (storeMode === 'B') {
      // Try to match PL-XXX optionally followed by a ticker
      const plMatch = text.match(/\b(PL-\d{3})\b/i)
      const tickerMatch = text.match(/\b([A-Z]{1,5})\b/)
      if (plMatch) {
        const plId = plMatch[1].toUpperCase()
        const pipeline = PIPELINES.find((p) => p.id === plId)
        if (pipeline) {
          const tabTicker = tickerMatch ? tickerMatch[1] : ticker
          openTab({
            id: `pipeline:${plId}`,
            kind: 'pipeline',
            title: `${pipeline.name}${tabTicker ? ` · ${tabTicker}` : ''}`,
            payload: { pipelineId: plId, ticker: tabTicker },
          })
          setInputText('')
          return
        }
      }
      // No valid PL-XXX → toast
      addToast({
        type: 'error',
        title: '请输入 PL-XXX 或 ticker',
        description: '示例: "PL-001 AAPL" 或 "PL-002"',
      })
      return
    }

    // MODE A: normal sendMessage
    clearError()
    sendMessage({ text })
    setInputText('')
  }, [inputText, isLoading, storeMode, sendMessage, clearError, openTab, ticker, addToast])

  const handleReload = useCallback(() => {
    clearError()
    regenerate()
  }, [clearError, regenerate])

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

  // ── Collapsed view ──────────────────────────────────────────
  if (!isExpanded) {
    return (
      <IconColumn
        onToggle={() => {
          handleToggle()
          setUnreadCount(0)
          lastSeenMessageCountRef.current = messages.filter(
            (m) => m.role === 'assistant',
          ).length
        }}
        unreadCount={unreadCount}
        onNewSession={startNewSession}
      />
    )
  }

  const panelStyle: React.CSSProperties = expandedProp !== undefined
    // legacy/test mode: don't override width with store value
    ? { width: '360px', borderLeft: '1px solid var(--border)', backgroundColor: 'var(--surface)' }
    : { width: `${storeWidth}px` }

  return (
    <aside
      ref={panelRef}
      data-testid="right-chat-panel"
      className="ai-panel open"
      style={panelStyle}
    >
      {/* Resize handle — only when controlled by uiStore */}
      {expandedProp === undefined && (
        <div className="aipanel-resize-handle" onMouseDown={onResizeMouseDown} />
      )}

      <AiPanelHeader
        modelValue={modelValue}
        onModelChange={handleModelChange}
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

      <AiInputArea
        value={inputText}
        onChange={setInputText}
        onSubmit={handleSubmit}
        isLoading={isLoading}
        onStop={stop}
        onReload={handleReload}
        error={error}
        hasMessages={messages.length > 0}
        mode={storeMode}
        onModeToggle={() => setStoreMode(storeMode === 'A' ? 'B' : 'A')}
        toolActive={toolActive}
        onToolToggle={() => setToolActive((v) => !v)}
        thinkActive={thinkActive}
        onThinkToggle={() => setThinkActive((v) => !v)}
      />
    </aside>
  )
}

// ──────────────────────────────────────────────────────────────
// AiPanelHeader — .ai-header
// ──────────────────────────────────────────────────────────────

interface AiPanelHeaderProps {
  modelValue: ModelValue
  onModelChange: (m: ModelValue) => void
  onToggle: () => void
  onNewSession: () => void
  ticker: string | undefined
}

function AiPanelHeader({
  modelValue,
  onModelChange,
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
          color: ticker ? 'var(--amber)' : 'var(--text-3)',
          letterSpacing: '0.05em',
        }}
      >
        {ticker ?? '探索'}
      </span>

      {/* Model selector chip */}
      <select
        data-testid="model-selector"
        className="ai-model"
        value={modelValue}
        onChange={(e) => onModelChange(e.target.value as ModelValue)}
        title={t('chat.model.tooltip')}
      >
        {MODELS.map((m) => (
          <option key={m.value} value={m.value}>
            {m.label}
          </option>
        ))}
      </select>

      {/* New session */}
      <button
        data-testid="new-session-btn"
        onClick={onNewSession}
        title={t('chat.newSession')}
        className="ai-close"
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
        className="ai-close"
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
          <div style={{ fontSize: '12px', color: 'var(--text-2)' }}>
            {t('chat.empty.heading')}
          </div>
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
    <div
      data-testid="message-list"
      className="ai-messages"
    >
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
  const now = new Date()
  const timeStr = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

  return (
    <div
      data-testid={`message-${message.role}`}
      className={`msg ${isUser ? 'user' : 'agent'}`}
    >
      <div className="msg-head">
        {isUser ? `USER · ${timeStr}` : `● FINAGENT · ${timeStr}`}
      </div>
      {isUser ? (
        <UserBubble message={message} />
      ) : (
        <AssistantContent message={message} />
      )}
    </div>
  )
}

function UserBubble({ message }: { message: UIMessage }): React.ReactElement {
  const text = message.parts
    .filter((p) => isTextUIPart(p))
    .map((p) => (p.type === 'text' ? p.text : ''))
    .join('')

  return (
    <div className="msg-body">
      {text}
    </div>
  )
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
  } else if (
    state === 'output-available' ||
    state === 'approval-responded'
  ) {
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
            <div
              key={idx}
              data-testid="text-part"
            >
              <MarkdownLite text={part.text} />
            </div>
          )
        }

        if (isReasoningUIPart(part)) {
          return (
            <ReasoningCollapsible key={idx} text={part.text ?? ''} />
          )
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
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--text-3)', fontSize: '11px',
          display: 'flex', alignItems: 'center', gap: '4px',
        }}
        type="button"
      >
        {open ? '▾' : '▸'} {t('chat.reasoning')}
      </button>
      {open && (
        <div
          style={{
            marginTop: '4px', padding: '6px 10px',
            background: 'var(--bg-3)', borderRadius: '4px',
            whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)',
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
    <div
      data-testid="thinking-indicator"
      className="msg agent"
    >
      <div className="msg-head">● FINAGENT</div>
      <div className="msg-body" style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
        <span
          style={{
            display: 'inline-block', width: '6px', height: '6px',
            borderRadius: '50%', background: 'var(--amber)',
            animation: 'blink 1s 0ms infinite',
          }}
        />
        <span
          style={{
            display: 'inline-block', width: '6px', height: '6px',
            borderRadius: '50%', background: 'var(--amber)',
            animation: 'blink 1s 150ms infinite',
          }}
        />
        <span
          style={{
            display: 'inline-block', width: '6px', height: '6px',
            borderRadius: '50%', background: 'var(--amber)',
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
  mode: AgentMode
  onModeToggle: () => void
  toolActive: boolean
  onToolToggle: () => void
  thinkActive: boolean
  onThinkToggle: () => void
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
  mode,
  onModeToggle,
  toolActive,
  onToolToggle,
  thinkActive,
  onThinkToggle,
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
    if (e.key === 'Enter' && e.shiftKey) return
    // ⌘↵ or Enter → submit
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      if (!isEmpty && !isOverLimit && !isLoading) onSubmit()
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      if (!isEmpty && !isOverLimit && !isLoading) onSubmit()
    }
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
                marginLeft: '8px', flexShrink: 0,
                padding: '2px 8px', fontSize: '11px',
                background: 'var(--bg-3)',
                border: '1px solid var(--line-bright)',
                borderRadius: '3px', color: 'var(--text-1)',
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
          placeholder="向 FinAgent 提问 · 输入 @ 引用文件 / 输入 / 选择 Pipeline"
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
          {/* 附件 (Phase 5 TODO) */}
          <button
            className="input-btn"
            title="附加文件 (@)"
            type="button"
            onClick={() => {/* Phase 5 */}}
          >
            <IconPaperclip size={13} />
          </button>

          {/* 工具开关 */}
          <button
            className={`input-btn${toolActive ? ' active' : ''}`}
            title="工具开关"
            type="button"
            onClick={onToolToggle}
          >
            <IconTool size={13} />
          </button>

          {/* 深度思考 */}
          <button
            className={`input-btn${thinkActive ? ' active' : ''}`}
            title="深度思考"
            type="button"
            onClick={onThinkToggle}
          >
            <IconClock size={13} />
          </button>

          {/* 模式切换 chip */}
          <button
            className={`input-mode${mode === 'B' ? ' mode-b' : ''}`}
            title="切换模式"
            onClick={onModeToggle}
            type="button"
          >
            模式 · <span className="em">{mode}</span>
          </button>

          <div className="spacer" />

          {/* 发送 / 停止 */}
          {isLoading ? (
            <button
              data-testid="stop-btn"
              onClick={onStop}
              style={{
                padding: '5px 11px', borderRadius: '4px',
                background: 'rgba(248,113,113,0.15)',
                border: '1px solid rgba(248,113,113,0.3)',
                color: 'var(--red)', fontSize: '10px',
                fontFamily: 'var(--font-mono)', cursor: 'pointer',
                fontWeight: 700, letterSpacing: '0.05em',
                display: 'flex', alignItems: 'center', gap: '5px',
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
              className={`send${mode === 'B' ? ' mode-b' : ''}`}
              style={{
                opacity: isEmpty || isOverLimit ? 0.45 : 1,
                cursor: isEmpty || isOverLimit ? 'not-allowed' : 'pointer',
              }}
              type="button"
            >
              {mode === 'B' ? '执行' : '运行'}
              <span className="kbd">⌘↵</span>
            </button>
          )}
        </div>
      </div>

      {/* Character count hint */}
      {value.length > MAX_INPUT_LENGTH * 0.8 && !isOverLimit && (
        <div
          style={{
            marginTop: '4px', textAlign: 'right',
            fontSize: '11px', color: 'var(--warning)',
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

function IconColumn({
  onToggle,
  unreadCount,
  onNewSession,
}: IconColumnProps): React.ReactElement {
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
    <aside
      data-testid="icon-column"
      className="ai-icon-column"
    >
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
          <span
            data-testid="unread-badge"
            className="ai-icon-column-badge"
          >
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
              window.location.href = '/library'
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
