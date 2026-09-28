// ──────────────────────────────────────────────────────────────
// MessageBubble — .msg : one transcript entry (user bubble, or the
// assistant's text / reasoning / tool-call parts).
// ──────────────────────────────────────────────────────────────

import { useState } from 'react'
import type { UIMessage, UIMessagePart, UIDataTypes, UITools, DynamicToolUIPart } from 'ai'
import { isTextUIPart, isToolUIPart, isReasoningUIPart } from 'ai'
import { ToolCard } from '../../../components/ToolCard'
import type { ToolResult } from '../../../components/ToolCard'
import { MarkdownLite } from '../../../components/MarkdownLite'
import { useI18n } from '../../../i18n'

export function MessageBubble({ message }: { message: UIMessage }): React.ReactElement {
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
