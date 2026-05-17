import { useEffect, useCallback } from 'react'

interface Shortcut {
  keys: string[]
  label: string
}

interface ShortcutGroup {
  title: string
  shortcuts: Shortcut[]
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: 'General',
    shortcuts: [
      { keys: ['⌘', 'K'], label: 'Command Palette' },
      { keys: ['⌘', '/'], label: 'Shortcut Reference' },
      { keys: ['⌘', ','], label: 'Settings' },
      { keys: ['Esc'], label: 'Close Overlay' },
    ],
  },
  {
    title: 'Navigation',
    shortcuts: [
      { keys: ['⌘', '1'], label: 'Workspace' },
      { keys: ['⌘', '2'], label: 'History' },
      { keys: ['↑', '↓'], label: 'Navigate List' },
      { keys: ['Enter'], label: 'Select Item' },
    ],
  },
  {
    title: 'Pipeline',
    shortcuts: [
      { keys: ['1-5'], label: 'Switch Pipeline' },
      { keys: ['⌘', 'R'], label: 'Run Pipeline' },
      { keys: ['⌘', 'E'], label: 'Export Report' },
      { keys: ['⌘', 'D'], label: 'Load Demo Ticker' },
    ],
  },
]

interface Props {
  open: boolean
  onClose: () => void
}

export default function ShortcutSheet({ open, onClose }: Props) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    },
    [onClose]
  )

  useEffect(() => {
    if (!open) return
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, handleKeyDown])

  if (!open) return null

  return (
    <div className="shortcut-overlay" onClick={onClose}>
      <div
        className="shortcut-sheet animate-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="shortcut-sheet-header">
          <h2 className="shortcut-sheet-title">Keyboard Shortcuts</h2>
          <kbd className="shortcut-dismiss">Esc</kbd>
        </div>

        <div className="shortcut-grid">
          {SHORTCUT_GROUPS.map((group) => (
            <div key={group.title} className="shortcut-group">
              <h3 className="shortcut-group-title">{group.title}</h3>
              <div className="shortcut-list">
                {group.shortcuts.map((s) => (
                  <div key={s.label} className="shortcut-row">
                    <span className="shortcut-keys">
                      {s.keys.map((k, i) => (
                        <kbd key={i} className="shortcut-key">
                          {k}
                        </kbd>
                      ))}
                    </span>
                    <span className="shortcut-label">{s.label}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="shortcut-sheet-footer">
          <span>按 <kbd className="shortcut-key-inline">⌘</kbd><kbd className="shortcut-key-inline">/</kbd> 打开/关闭</span>
        </div>
      </div>
    </div>
  )
}
