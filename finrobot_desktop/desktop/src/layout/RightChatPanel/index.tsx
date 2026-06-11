// RightChatPanel — cosmic Stage A AI chat surface.
//
// Owns the outer aside, expand/collapse state, and width resize. The body
// is always AiChatTab (per-ticker conversational AI), which renders the
// single panel header (logo, model badge, history, new-session, close).
//
// AppShell imports this as `RightChatPanel`; existing tests importing
// `./RightChatPanel` resolve via this file thanks to directory
// resolution. Old prop shape (`expanded` / `onToggle`) is preserved so
// legacy tests keep working.

import { useCallback, useRef } from 'react'
import { useUiStore } from '../../stores/uiStore'
import { useI18n } from '../../i18n'
import { AiChatTab } from './AiChatTab'

interface RightChatPanelProps {
  /** Tests inject this; AppShell passes nothing. */
  expanded?: boolean
  onToggle?: () => void
}

export function RightChatPanel({
  expanded: expandedProp,
  onToggle: onToggleProp,
}: RightChatPanelProps = {}): React.ReactElement {
  const { t } = useI18n()
  const storeOpen = useUiStore((s) => s.aiPanelOpen)
  const storeWidth = useUiStore((s) => s.aiPanelWidth)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)
  const setAiPanelWidth = useUiStore((s) => s.setAiPanelWidth)

  const isExpanded = expandedProp !== undefined ? expandedProp : storeOpen
  const handleToggle = onToggleProp ?? toggleAiPanel

  const panelRef = useRef<HTMLElement>(null)
  const resizing = useRef(false)
  const resizeStartX = useRef(0)
  const resizeStartW = useRef(0)
  const onResizeMouseDown = useCallback(
    (e: React.MouseEvent) => {
      resizing.current = true
      resizeStartX.current = e.clientX
      resizeStartW.current = storeWidth
      const onMove = (ev: MouseEvent) => {
        if (!resizing.current) return
        const delta = resizeStartX.current - ev.clientX
        setAiPanelWidth(resizeStartW.current + delta)
      }
      const onUp = () => {
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

  if (expandedProp !== undefined) {
    if (expandedProp === false) {
      return <AiChatTab expanded={expandedProp} onToggle={onToggleProp} />
    }
    return (
      <aside
        data-testid="right-chat-panel"
        className="ai-panel open"
        style={{
          width: 360,
          borderLeft: '1px solid var(--border)',
          backgroundColor: 'var(--surface)',
        }}
      >
        <AiChatTab expanded={expandedProp} onToggle={onToggleProp} />
      </aside>
    )
  }

  const panelStyle: React.CSSProperties =
    expandedProp !== undefined
      ? { width: 360, borderLeft: '1px solid var(--border)', backgroundColor: 'var(--surface)' }
      : isExpanded
        ? { width: storeWidth }
        : {}

  const panelClass = ['ai-panel', expandedProp !== undefined || isExpanded ? 'open' : '']
    .filter(Boolean)
    .join(' ')

  return (
    <aside ref={panelRef} data-testid="right-chat-panel" className={panelClass} style={panelStyle}>
      {/* Collapsed-state expand button (only when uiStore controlled) */}
      {expandedProp === undefined && !isExpanded && (
        <button
          data-testid="expand-btn"
          className="ai-panel-expand-btn"
          onClick={handleToggle}
          title={t('chatpanel.expand.open')}
          type="button"
        >
          <span className="expand-icon">◈</span>
        </button>
      )}

      {/* Resize handle (uiStore + expanded) */}
      {expandedProp === undefined && isExpanded && (
        <div className="aipanel-resize-handle" onMouseDown={onResizeMouseDown} />
      )}

      {isExpanded && <AiChatTab />}
    </aside>
  )
}
