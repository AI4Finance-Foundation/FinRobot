// TitleBar — terminal-style: traffic lights + center label + theme/AI toggles.

import { useUiStore } from '../stores/uiStore'
import { IconSparkle } from '../lib/icons'

// Simple inline sun/moon icons — no extra dependency needed.
function IconSun({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  )
}

function IconMoon({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

export function TitleBar(): React.ReactElement {
  const theme = useUiStore((s) => s.theme)
  const toggleTheme = useUiStore((s) => s.toggleTheme)
  const aiPanelOpen = useUiStore((s) => s.aiPanelOpen)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)

  return (
    <div className="titlebar" data-tauri-drag-region data-testid="titlebar">
      {/* Reserve space for Tauri's native macOS traffic lights (Overlay titleBarStyle) */}
      <div style={{ width: 72, flexShrink: 0 }} />

      {/* Center label */}
      <div className="titlebar-title" data-tauri-drag-region>
        FINAGENT
      </div>

      {/* Right action buttons */}
      <div className="titlebar-actions">
        <button
          className="tb-btn"
          title={theme === 'dark' ? '切换为浅色模式' : '切换为深色模式'}
          onClick={toggleTheme}
        >
          {theme === 'dark' ? <IconSun size={14} /> : <IconMoon size={14} />}
        </button>
        <button
          className={`tb-btn${aiPanelOpen ? ' active' : ''}`}
          title="AI 助手"
          onClick={toggleAiPanel}
        >
          <IconSparkle size={14} />
        </button>
      </div>
    </div>
  )
}
