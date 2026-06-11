// ──────────────────────────────────────────────────────────────
// IconColumn (collapsed state) — legacy/test path rendered when AiChatTab is
// given `expanded={false}` by a test or legacy caller.
// ──────────────────────────────────────────────────────────────

import { useState } from 'react'
import { useI18n } from '../../../i18n'

interface IconColumnProps {
  onToggle: () => void
  unreadCount: number
  onNewSession: () => void
}

export function IconColumn({
  onToggle,
  unreadCount,
  onNewSession,
}: IconColumnProps): React.ReactElement {
  const [showMenu, setShowMenu] = useState(false)
  const { t } = useI18n()

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
        </div>
      )}
    </aside>
  )
}
