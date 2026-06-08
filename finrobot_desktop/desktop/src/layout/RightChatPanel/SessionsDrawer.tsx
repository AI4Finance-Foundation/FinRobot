// SessionsDrawer — manage chat sessions as first-class objects.
//
// Renders as a SLIDE-OVER overlay (.ai-drawer, absolute inset:0 over the chat
// body) instead of an in-flow block — opening history no longer squeezes the
// conversation, the coverage strip, or the input. It is conditionally mounted
// by AiChatTab (so it leaves the DOM when closed); on mount it slides in.
//
// Lists every session (global, not ticker-filtered), newest-first. Each card:
//   - click the card  → switch to that session and RESUME it (re-seed + keep chatting)
//   - trailing ✕      → inline two-step confirm, then delete
// Top "New conversation" starts a fresh empty session. The active session is
// highlighted with a static left spine + faint glow (no animation).

import { useState } from 'react'
import { useI18n } from '../../i18n'
import { IconPlus, IconClose, IconClock } from '../../lib/icons'
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

  return (
    <div className="ai-drawer" data-testid="sessions-drawer">
      {/* Header */}
      <div className="ai-drawer-hd">
        <IconClock size={15} />
        <div className="t">{zh ? '会话' : 'Conversations'}</div>
        <div className="grow" />
        <button
          data-testid="sessions-close-btn"
          className="ai-icon-btn"
          onClick={onClose}
          type="button"
          title={zh ? '关闭' : 'Close'}
        >
          <IconClose size={15} />
        </button>
      </div>

      {/* New conversation */}
      <button
        data-testid="sessions-new-btn"
        className="ai-drawer-new"
        onClick={() => {
          onNew()
          onClose()
        }}
        type="button"
      >
        <IconPlus size={14} />
        {zh ? '新建会话' : 'New conversation'}
      </button>

      {/* List */}
      <div className="ai-drawer-list">
        {loading ? (
          <div className="ai-drawer-state">
            <div className="st-s">{zh ? '加载中…' : 'Loading…'}</div>
          </div>
        ) : error ? (
          <div className="ai-drawer-state">
            <div className="st-s">{zh ? '无法加载会话。' : 'Could not load conversations.'}</div>
          </div>
        ) : sessions.length === 0 ? (
          <div data-testid="sessions-empty" className="ai-drawer-state">
            <div className="st-s">
              {zh
                ? '还没有会话。在右侧开始对话即可创建。'
                : 'No conversations yet. Start chatting to create one.'}
            </div>
          </div>
        ) : (
          sessions.map((s) => (
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
          ))
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

  const className = ['ai-sess', active ? 'active' : '', deleting ? 'removing' : '']
    .filter(Boolean)
    .join(' ')

  return (
    <div
      data-testid="session-row"
      data-active={active ? 'true' : undefined}
      className={className}
      role="button"
      tabIndex={0}
      onClick={() => {
        if (!deleting) onSelect()
      }}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && !deleting) {
          e.preventDefault()
          onSelect()
        }
      }}
    >
      <div className="st">{session.title}</div>
      <div className="meta">
        {session.ticker && (
          <>
            <span className="tk">{session.ticker}</span>
            <span className="sep">·</span>
          </>
        )}
        <span>
          {zh
            ? `${session.turn_count} 轮`
            : `${session.turn_count} ${session.turn_count === 1 ? 'turn' : 'turns'}`}
        </span>
        <span className="sep">·</span>
        <span>{formatRelative(session.last_active_at, locale)}</span>
      </div>

      {/* Delete affordance — inline two-step confirm (no browser confirm()).
          stopPropagation so it never triggers the row's select/switch. */}
      <div className="ai-sess-del" onClick={(e) => e.stopPropagation()}>
        {confirming ? (
          <div className="ai-sess-confirm">
            <button
              data-testid="session-confirm-delete"
              className="del"
              onClick={onConfirmDelete}
              type="button"
            >
              {zh ? '删除' : 'Delete'}
            </button>
            <button data-testid="session-cancel-delete" onClick={onCancelDelete} type="button">
              {zh ? '取消' : 'Cancel'}
            </button>
          </div>
        ) : (
          <button
            data-testid="session-delete-btn"
            className="x"
            onClick={onAskDelete}
            disabled={deleting}
            title={zh ? '删除会话' : 'Delete conversation'}
            type="button"
          >
            <IconClose size={13} />
          </button>
        )}
      </div>
    </div>
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
