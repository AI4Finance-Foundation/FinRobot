import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { UIMessage, UIMessagePart, UIDataTypes, UITools, DynamicToolUIPart } from 'ai'
import { isTextUIPart, isToolUIPart, isReasoningUIPart } from 'ai'
import { useToastStore } from '../stores/toastStore'
import { ToolCard } from '../components/ToolCard'
import type { ToolResult } from '../components/ToolCard'

// ──────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────

const MAX_INPUT_LENGTH = 20_000

const MODELS = [
  { value: 'deepseek', label: 'DeepSeek V3' },
  { value: 'anthropic', label: 'Claude Sonnet' },
  { value: 'openai', label: 'GPT-4o' },
] as const

type ModelValue = (typeof MODELS)[number]['value']

// ──────────────────────────────────────────────────────────────
// RightChatPanel props
// ──────────────────────────────────────────────────────────────

interface RightChatPanelProps {
  expanded: boolean
  onToggle: () => void
}

// ──────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────

export function RightChatPanel({
  expanded,
  onToggle,
}: RightChatPanelProps): React.ReactElement {
  const { ticker } = useParams<{ ticker?: string }>()
  const addToast = useToastStore((s) => s.addToast)

  // Session state
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID())
  const [model, setModel] = useState<ModelValue>('anthropic')
  // Local text input (controlled — not via useChat to support Shift+Enter)
  const [inputText, setInputText] = useState('')
  const prevTickerRef = useRef<string | undefined>(ticker)

  // Track unread for collapsed state
  const [unreadCount, setUnreadCount] = useState(0)
  const lastSeenMessageCountRef = useRef(0)

  // ── Transport (memoised — recreate when sessionId or model changes)
  const transport = new DefaultChatTransport({
    api: '/chat',
    body: {
      ticker: ticker ?? null,
      model,
    },
  })

  const { messages, status, error, sendMessage, stop, regenerate, clearError } =
    useChat({
      id: sessionId,
      transport,
      onError(err) {
        // Classify the error for user-visible messages
        const msg = err.message ?? ''

        if (msg.includes('context') || msg.includes('token')) {
          addToast({
            type: 'error',
            title: '对话过长',
            description: '请开启新对话继续。',
          })
        } else if (msg.includes('503') || msg.includes('Service Unavailable')) {
          addToast({ type: 'error', title: '服务不可用', description: '请稍后重试。' })
        } else {
          addToast({
            type: 'error',
            title: '请求失败',
            description: msg.slice(0, 120) || '未知错误',
          })
        }
      },
    })

  const isLoading = status === 'submitted' || status === 'streaming'

  // ── Ticker change → new session
  useEffect(() => {
    if (ticker === prevTickerRef.current) return
    prevTickerRef.current = ticker

    if (messages.length > 0 && ticker) {
      addToast({
        type: 'info',
        title: `已切到 ${ticker} 新对话`,
        description: '旧对话已在 Library 中保存。',
      })
    }

    setSessionId(crypto.randomUUID())
    setInputText('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  // ── Track unread when panel is collapsed
  useEffect(() => {
    if (!expanded) {
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
  }, [messages, expanded])

  // ── Submit handler
  const handleSubmit = useCallback(() => {
    const text = inputText.trim()
    if (!text) return
    if (text.length > MAX_INPUT_LENGTH) return
    if (isLoading) return

    clearError()
    sendMessage({ text })
    setInputText('')
  }, [inputText, isLoading, sendMessage, clearError])

  // ── Regenerate last assistant message
  const handleReload = useCallback(() => {
    clearError()
    regenerate()
  }, [clearError, regenerate])

  // ── Collapsed view
  if (!expanded) {
    return (
      <IconColumn
        onToggle={() => {
          onToggle()
          setUnreadCount(0)
          lastSeenMessageCountRef.current = messages.filter(
            (m) => m.role === 'assistant',
          ).length
        }}
        unreadCount={unreadCount}
        onNewSession={() => setSessionId(crypto.randomUUID())}
      />
    )
  }

  const sessionTitle = (() => {
    const first = messages.find((m) => m.role === 'user')
    if (!first) return '新对话'
    const firstPart = first.parts.find((p) => isTextUIPart(p))
    if (!firstPart || firstPart.type !== 'text') return '新对话'
    return firstPart.text.slice(0, 30)
  })()

  return (
    <aside
      data-testid="right-chat-panel"
      className="flex h-full flex-col"
      style={{
        width: '320px',
        borderLeft: '1px solid var(--border)',
        backgroundColor: 'var(--surface)',
      }}
    >
      <PanelHeader
        ticker={ticker}
        sessionTitle={sessionTitle}
        model={model}
        onModelChange={(m) => setModel(m)}
        onToggle={onToggle}
        onNewSession={() => {
          setSessionId(crypto.randomUUID())
          setInputText('')
        }}
      />

      <MessageList messages={messages} isLoading={isLoading} />

      <InputArea
        value={inputText}
        onChange={setInputText}
        onSubmit={handleSubmit}
        isLoading={isLoading}
        onStop={stop}
        onReload={handleReload}
        error={error}
        hasMessages={messages.length > 0}
      />
    </aside>
  )
}

// ──────────────────────────────────────────────────────────────
// PanelHeader
// ──────────────────────────────────────────────────────────────

interface PanelHeaderProps {
  ticker: string | undefined
  sessionTitle: string
  model: ModelValue
  onModelChange: (m: ModelValue) => void
  onToggle: () => void
  onNewSession: () => void
}

function PanelHeader({
  ticker,
  sessionTitle,
  model,
  onModelChange,
  onToggle,
  onNewSession,
}: PanelHeaderProps): React.ReactElement {
  return (
    <div
      data-testid="panel-header"
      className="flex shrink-0 items-center gap-2 px-3 py-2"
      style={{
        borderBottom: '1px solid var(--border)',
        minHeight: '44px',
      }}
    >
      {/* Ticker + session title */}
      <div className="min-w-0 flex-1">
        <span
          className="truncate text-xs font-semibold"
          style={{ color: 'var(--text-primary)' }}
        >
          {ticker ? ticker : '探索'}
        </span>
        {sessionTitle !== '新对话' && (
          <span
            className="ml-1 truncate text-xs"
            style={{ color: 'var(--text-muted)' }}
          >
            · {sessionTitle}
          </span>
        )}
      </div>

      {/* Model selector */}
      <select
        data-testid="model-selector"
        value={model}
        onChange={(e) => onModelChange(e.target.value as ModelValue)}
        className="shrink-0 rounded px-1 py-0.5 text-xs"
        style={{
          backgroundColor: 'var(--elevated)',
          border: '1px solid var(--border)',
          color: 'var(--text-secondary)',
        }}
        title="模型选择（下次对话起生效）"
      >
        {MODELS.map((m) => (
          <option key={m.value} value={m.value}>
            {m.label}
          </option>
        ))}
      </select>

      {/* New session button */}
      <button
        data-testid="new-session-btn"
        onClick={onNewSession}
        title="新建对话"
        className="shrink-0 rounded p-1 text-xs transition-colors hover:bg-neutral-700"
        style={{ color: 'var(--text-secondary)' }}
      >
        +
      </button>

      {/* Collapse button */}
      <button
        data-testid="collapse-btn"
        onClick={onToggle}
        title="收起对话"
        className="shrink-0 rounded p-1 text-xs transition-colors hover:bg-neutral-700"
        style={{ color: 'var(--text-secondary)' }}
      >
        ›
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
}

function MessageList({ messages, isLoading }: MessageListProps): React.ReactElement {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0 && !isLoading) {
    return (
      <div
        data-testid="empty-state"
        className="flex flex-1 items-center justify-center"
        style={{ color: 'var(--text-muted)' }}
      >
        <div className="text-center text-xs">
          <div className="mb-1 text-2xl">💬</div>
          <div>问一个关于金融的问题</div>
        </div>
      </div>
    )
  }

  return (
    <div
      data-testid="message-list"
      className="flex-1 overflow-y-auto px-3 py-2"
      style={{ scrollBehavior: 'smooth' }}
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
// MessageBubble
// ──────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: UIMessage }): React.ReactElement {
  const isUser = message.role === 'user'

  return (
    <div
      data-testid={`message-${message.role}`}
      className={`mb-3 flex ${isUser ? 'justify-end' : 'justify-start'}`}
    >
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
    <div
      className="max-w-[85%] rounded-lg px-3 py-2 text-sm"
      style={{
        backgroundColor: 'rgba(96,165,250,0.15)',
        border: '1px solid rgba(96,165,250,0.2)',
        color: 'var(--text-primary)',
      }}
    >
      {text}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// ToolCardFromPart — converts a ToolUIPart | DynamicToolUIPart → <ToolCard>
// ──────────────────────────────────────────────────────────────

function ToolCardFromPart({
  part,
  fallbackId,
}: {
  part: UIMessagePart<UIDataTypes, UITools>
  fallbackId: string
}): React.ReactElement {
  // Both ToolUIPart and DynamicToolUIPart share toolCallId / toolName / state
  // We access via a cast to the widest common shape.
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
    errorText = anyPart.errorText ?? '工具调用失败'
  }

  return (
    <ToolCard
      toolCallId={toolCallId}
      toolName={toolName}
      args={args}
      result={result}
      errorText={errorText}
      state={cardState}
    />
  )
}

function AssistantContent({ message }: { message: UIMessage }): React.ReactElement {
  return (
    <div className="w-full max-w-[95%]">
      {message.parts.map((part, idx) => {
        if (isTextUIPart(part)) {
          // text part — inline streaming
          return (
            <div
              key={idx}
              data-testid="text-part"
              className="mb-1 whitespace-pre-wrap text-sm leading-relaxed"
              style={{ color: 'var(--text-primary)' }}
            >
              {part.text}
            </div>
          )
        }

        if (isReasoningUIPart(part)) {
          // reasoning — collapsible
          return (
            <ReasoningCollapsible key={idx} text={part.text ?? ''} />
          )
        }

        if (isToolUIPart(part)) {
          // isToolUIPart covers both ToolUIPart (static typed) and DynamicToolUIPart
          return (
            <ToolCardFromPart
              key={idx}
              part={part as UIMessagePart<UIDataTypes, UITools>}
              fallbackId={String(idx)}
            />
          )
        }

        // step-start, source-url, file, data — render nothing rather than crash
        return null
      })}
    </div>
  )
}

function ReasoningCollapsible({ text }: { text: string }): React.ReactElement {
  const [open, setOpen] = useState(false)
  return (
    <div className="mb-1 text-xs" style={{ color: 'var(--text-muted)' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 underline-offset-2 hover:underline"
      >
        {open ? '▾' : '▸'} 思考过程
      </button>
      {open && (
        <div
          className="mt-1 rounded px-2 py-1.5 whitespace-pre-wrap"
          style={{ backgroundColor: 'var(--elevated)' }}
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
      className="mb-2 flex items-center gap-1.5 text-xs"
      style={{ color: 'var(--text-muted)' }}
    >
      <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:0ms]" />
      <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:150ms]" />
      <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:300ms]" />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// InputArea
// ──────────────────────────────────────────────────────────────

interface InputAreaProps {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  isLoading: boolean
  onStop: () => void
  onReload: () => void
  error: Error | undefined
  hasMessages: boolean
}

function InputArea({
  value,
  onChange,
  onSubmit,
  isLoading,
  onStop,
  onReload,
  error,
  hasMessages,
}: InputAreaProps): React.ReactElement {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isOverLimit = value.length > MAX_INPUT_LENGTH
  const isEmpty = value.trim().length === 0

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [value])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    // Cmd+Enter (macOS) or Ctrl+Enter (Windows/Linux) → submit
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      if (!isEmpty && !isOverLimit && !isLoading) onSubmit()
      return
    }
    // Shift+Enter → newline (default textarea behaviour — no need to intercept)
  }

  return (
    <div
      data-testid="input-area"
      className="shrink-0 px-3 pb-3 pt-2"
      style={{ borderTop: '1px solid var(--border)' }}
    >
      {/* Error banner */}
      {error && !isLoading && (
        <div
          data-testid="error-banner"
          className="mb-2 flex items-center justify-between rounded px-2 py-1.5 text-xs"
          style={{
            backgroundColor: 'rgba(248,113,113,0.1)',
            color: 'var(--negative)',
          }}
        >
          <span className="truncate">
            {error.message.includes('context') || error.message.includes('token')
              ? '对话过长，请开启新对话。'
              : '请求失败'}
          </span>
          {hasMessages && (
            <button
              data-testid="reload-btn"
              onClick={onReload}
              className="ml-2 shrink-0 rounded px-2 py-0.5 text-xs"
              style={{
                backgroundColor: 'var(--elevated)',
                border: '1px solid var(--border)',
              }}
            >
              重试
            </button>
          )}
        </div>
      )}

      {/* Textarea */}
      <div
        className="relative rounded-md"
        style={{
          border: `1px solid ${isOverLimit ? 'var(--negative)' : 'var(--border)'}`,
          backgroundColor: 'var(--elevated)',
        }}
      >
        <textarea
          ref={textareaRef}
          data-testid="chat-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息或问题... (⌘↵ 发送)"
          rows={2}
          disabled={isLoading}
          className="w-full resize-none rounded-md px-3 py-2 text-sm outline-none"
          style={{
            backgroundColor: 'transparent',
            color: 'var(--text-primary)',
            caretColor: 'var(--info)',
            minHeight: '56px',
          }}
          aria-label="消息输入框"
        />

        {/* Over-limit warning */}
        {isOverLimit && (
          <div
            data-testid="overlength-warning"
            className="px-3 pb-1 text-xs"
            style={{ color: 'var(--negative)' }}
          >
            消息过长（{value.length.toLocaleString()} / {MAX_INPUT_LENGTH.toLocaleString()} 字符）
          </div>
        )}

        {/* Bottom row: send / stop */}
        <div className="flex items-center justify-end gap-2 px-2 pb-2">
          {isLoading ? (
            <button
              data-testid="stop-btn"
              onClick={onStop}
              className="rounded px-3 py-1 text-xs font-medium transition-colors hover:opacity-80"
              style={{
                backgroundColor: 'rgba(248,113,113,0.15)',
                color: 'var(--negative)',
                border: '1px solid rgba(248,113,113,0.3)',
              }}
            >
              ■ 停止
            </button>
          ) : (
            <button
              data-testid="send-btn"
              onClick={onSubmit}
              disabled={isEmpty || isOverLimit}
              className="rounded px-3 py-1 text-xs font-medium transition-opacity"
              style={{
                backgroundColor: isEmpty || isOverLimit ? 'var(--border)' : 'var(--info)',
                color: isEmpty || isOverLimit ? 'var(--text-muted)' : '#fff',
                opacity: isEmpty || isOverLimit ? 0.5 : 1,
                cursor: isEmpty || isOverLimit ? 'not-allowed' : 'pointer',
              }}
            >
              发送
            </button>
          )}
        </div>
      </div>

      {/* Character count hint when approaching limit */}
      {value.length > MAX_INPUT_LENGTH * 0.8 && !isOverLimit && (
        <div
          className="mt-1 text-right text-xs"
          style={{ color: 'var(--warning)' }}
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
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handlePointerDown = (): void => {
    longPressTimer.current = setTimeout(() => {
      setShowMenu(true)
    }, 600)
  }

  const handlePointerUp = (): void => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
  }

  return (
    <aside
      data-testid="icon-column"
      className="relative flex h-full flex-col items-center justify-start pt-3"
      style={{
        width: '56px',
        borderLeft: '1px solid var(--border)',
        backgroundColor: 'var(--surface)',
      }}
    >
      <div className="relative">
        <button
          data-testid="expand-btn"
          onClick={onToggle}
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          title="展开对话"
          className="flex h-9 w-9 items-center justify-center rounded-md text-lg transition-colors hover:bg-neutral-700"
          style={{ color: 'var(--text-secondary)' }}
        >
          💬
        </button>

        {/* Unread badge */}
        {unreadCount > 0 && (
          <span
            data-testid="unread-badge"
            className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold text-white"
            style={{ backgroundColor: 'var(--negative)' }}
          >
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </div>

      {/* Long-press context menu */}
      {showMenu && (
        <div
          data-testid="icon-menu"
          className="absolute left-full top-2 z-50 ml-1 rounded-md shadow-lg"
          style={{
            backgroundColor: 'var(--elevated)',
            border: '1px solid var(--border)',
          }}
        >
          <button
            className="block w-full whitespace-nowrap px-4 py-2 text-left text-xs transition-colors hover:bg-neutral-700"
            style={{ color: 'var(--text-primary)' }}
            onClick={() => {
              onToggle()
              setShowMenu(false)
            }}
          >
            展开对话
          </button>
          <button
            className="block w-full whitespace-nowrap px-4 py-2 text-left text-xs transition-colors hover:bg-neutral-700"
            style={{ color: 'var(--text-primary)' }}
            onClick={() => {
              onNewSession()
              setShowMenu(false)
            }}
          >
            新建对话
          </button>
          <button
            className="block w-full whitespace-nowrap px-4 py-2 text-left text-xs transition-colors hover:bg-neutral-700"
            style={{ color: 'var(--text-primary)' }}
            onClick={() => {
              window.location.href = '/library'
              setShowMenu(false)
            }}
          >
            查看历史
          </button>
          <button
            className="block w-full whitespace-nowrap px-4 py-2 text-left text-xs transition-colors hover:bg-neutral-700"
            style={{ color: 'var(--text-muted)' }}
            onClick={() => setShowMenu(false)}
          >
            取消
          </button>
        </div>
      )}
    </aside>
  )
}
