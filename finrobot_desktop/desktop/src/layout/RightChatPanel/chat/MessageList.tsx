// ──────────────────────────────────────────────────────────────
// MessageList — .ai-messages : transcript scroll area, with the restoring /
// empty welcome states and the live status indicator at the tail.
// ──────────────────────────────────────────────────────────────

import { useEffect, useRef } from 'react'
import type { UIMessage } from 'ai'
import { useI18n } from '../../../i18n'
import { MessageBubble } from './MessageBubble'
import { StatusIndicator, type ChatStatus } from './StatusIndicator'

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

export function MessageList({
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
