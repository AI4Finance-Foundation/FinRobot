// ──────────────────────────────────────────────────────────────
// AiInputArea — .ai-input-wrap (Phase 4 rewrite)
// ──────────────────────────────────────────────────────────────

import { useEffect, useRef } from 'react'
import { useI18n } from '../../../i18n'
import { MAX_INPUT_LENGTH, isContextOverflowError } from './constants'

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

export function AiInputArea({
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
