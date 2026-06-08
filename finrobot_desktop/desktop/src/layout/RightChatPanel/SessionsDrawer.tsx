// SessionsDrawer — manage chat sessions as first-class objects.
//
// Replaces the old read-only HistoryDrawer. Lists every session (global, not
// ticker-filtered), newest-first. Each row:
//   - click the row  → switch to that session and RESUME it (re-seed + keep chatting)
//   - trailing ✕     → inline two-step confirm, then delete
// Top "+ New chat" starts a fresh empty session. The active session is
// highlighted with a static left spine + faint glow (no animation).
//
// Styling is all inline + var(--*) tokens (does not touch App.css, to avoid
// racing a parallel agent editing the stylesheet).

import { useState } from 'react'
import { useI18n } from '../../i18n'
import { IconPlus, IconClose } from '../../lib/icons'
import type { ChatSessionSummary } from '../../hooks/useChatSessions'

interface SessionsDrawerProps {
  sessions: ChatSessionSummary[]
  activeSessionId: string
  loading: boolean
  error: boolean
  deletingId: string | null
  onSwitch: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  onClose: () => void
}

export function SessionsDrawer({
  sessions,
  activeSessionId,
  loading,
  error,
  deletingId,
  onSwitch,
  onNew,
  onDelete,
  onClose,
}: SessionsDrawerProps): React.ReactElement {
  const { locale } = useI18n()
  const zh = locale === 'zh'

  // Which row is in the "confirm delete?" state (one at a time).
  const [confirmId, setConfirmId] = useState<string | null>(null)

  const emptyStyle: React.CSSProperties = {
    padding: '16px 12px',
    fontSize: '11px',
    color: 'var(--text-3)',
    textAlign: 'center',
  }

  return (
    <div
      data-testid="sessions-drawer"
      style={{
        display: 'flex',
        flexDirection: 'column',
        maxHeight: '50%',
        minHeight: 0,
        borderBottom: '1px solid var(--line-bright)',
        background: 'var(--bg-2)',
      }}
    >
      {/* Header */}
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
          {zh ? '会话' : 'Sessions'}
        </span>
        <button
          data-testid="sessions-new-btn"
          className="ai-icon-btn"
          onClick={() => {
            onNew()
            onClose()
          }}
          type="button"
          title={zh ? '新会话' : 'New chat'}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            width: 'auto',
            padding: '0 6px',
          }}
        >
          <IconPlus size={12} />
          <span style={{ fontSize: '11px' }}>{zh ? '新会话' : 'New chat'}</span>
        </button>
        <button
          data-testid="sessions-close-btn"
          className="ai-icon-btn"
          onClick={onClose}
          type="button"
          title={zh ? '关闭' : 'Close'}
        >
          <IconClose size={13} />
        </button>
      </div>

      {/* Body */}
      <div style={{ overflowY: 'auto', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {loading ? (
          <div style={emptyStyle}>{zh ? '加载中…' : 'Loading…'}</div>
        ) : error ? (
          <div style={emptyStyle}>{zh ? '无法加载会话。' : 'Could not load sessions.'}</div>
        ) : sessions.length === 0 ? (
          <div data-testid="sessions-empty" style={emptyStyle}>
            {zh
              ? '还没有会话。在右侧开始对话即可创建。'
              : 'No sessions yet. Start chatting to create one.'}
          </div>
        ) : (
          <ul
            style={{
              listStyle: 'none',
              margin: 0,
              padding: '4px',
              display: 'flex',
              flexDirection: 'column',
              gap: '2px',
            }}
          >
            {sessions.map((s) => (
              <SessionRow
                key={s.session_id}
                session={s}
                active={s.session_id === activeSessionId}
                confirming={confirmId === s.session_id}
                deleting={deletingId === s.session_id}
                locale={locale}
                onSelect={() => {
                  onSwitch(s.session_id)
                  onClose()
                }}
                onAskDelete={() => setConfirmId(s.session_id)}
                onCancelDelete={() => setConfirmId(null)}
                onConfirmDelete={() => {
                  setConfirmId(null)
                  onDelete(s.session_id)
                }}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// SessionRow
// ──────────────────────────────────────────────────────────────

interface SessionRowProps {
  session: ChatSessionSummary
  active: boolean
  confirming: boolean
  deleting: boolean
  locale: string
  onSelect: () => void
  onAskDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
}

function SessionRow({
  session,
  active,
  confirming,
  deleting,
  locale,
  onSelect,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: SessionRowProps): React.ReactElement {
  const zh = locale === 'zh'

  return (
    <li
      data-testid="session-row"
      data-active={active ? 'true' : undefined}
      style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        borderRadius: '4px',
        // Active: static left spine + faint accent glow (no animation).
        borderLeft: active ? '2px solid var(--accent)' : '2px solid transparent',
        background: active ? 'color-mix(in srgb, var(--accent) 10%, transparent)' : 'transparent',
        boxShadow: active ? '0 0 8px color-mix(in srgb, var(--accent) 18%, transparent)' : 'none',
        opacity: deleting ? 0.5 : 1,
      }}
    >
      {/* Row body — click to switch / resume */}
      <button
        onClick={onSelect}
        type="button"
        disabled={deleting}
        style={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
          textAlign: 'left',
          padding: '7px 8px',
          background: 'transparent',
          border: 'none',
          borderRadius: '4px',
          cursor: deleting ? 'default' : 'pointer',
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
          {session.title}
        </span>
        <span
          style={{
            fontSize: '10px',
            color: 'var(--text-3)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {session.ticker ? `${session.ticker} · ` : ''}
          {zh
            ? `${session.turn_count} 轮`
            : `${session.turn_count} ${session.turn_count === 1 ? 'turn' : 'turns'}`}
          {' · '}
          {formatRelative(session.last_active_at, locale)}
        </span>
      </button>

      {/* Delete affordance — inline two-step confirm (no browser confirm()) */}
      {confirming ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            paddingRight: '6px',
            flexShrink: 0,
          }}
        >
          <button
            data-testid="session-confirm-delete"
            onClick={onConfirmDelete}
            type="button"
            style={{
              fontSize: '10px',
              padding: '2px 7px',
              borderRadius: '3px',
              border: '1px solid color-mix(in srgb, var(--danger) 40%, transparent)',
              background: 'color-mix(in srgb, var(--danger) 15%, transparent)',
              color: 'var(--danger)',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            {zh ? '删除' : 'Delete'}
          </button>
          <button
            data-testid="session-cancel-delete"
            onClick={onCancelDelete}
            type="button"
            style={{
              fontSize: '10px',
              padding: '2px 7px',
              borderRadius: '3px',
              border: '1px solid var(--line-bright)',
              background: 'var(--bg-3)',
              color: 'var(--text-2)',
              cursor: 'pointer',
            }}
          >
            {zh ? '取消' : 'Cancel'}
          </button>
        </div>
      ) : (
        <button
          data-testid="session-delete-btn"
          onClick={onAskDelete}
          type="button"
          disabled={deleting}
          title={zh ? '删除会话' : 'Delete session'}
          className="ai-icon-btn"
          style={{ flexShrink: 0, marginRight: '4px', color: 'var(--text-3)' }}
        >
          <IconClose size={12} />
        </button>
      )}
    </li>
  )
}

// ──────────────────────────────────────────────────────────────
// Relative time — "5m" / "3h" / "Jun 6", localized.
// ──────────────────────────────────────────────────────────────

function formatRelative(iso: string, locale: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const zh = locale === 'zh'
  const diffMs = Date.now() - d.getTime()
  const min = Math.floor(diffMs / 60_000)
  if (min < 1) return zh ? '刚刚' : 'just now'
  if (min < 60) return zh ? `${min} 分钟前` : `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return zh ? `${hr} 小时前` : `${hr}h ago`
  const days = Math.floor(hr / 24)
  if (days < 7) return zh ? `${days} 天前` : `${days}d ago`
  return d.toLocaleDateString(zh ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric' })
}
