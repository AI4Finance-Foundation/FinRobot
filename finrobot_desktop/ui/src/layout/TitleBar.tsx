// TitleBar — Phase 5: data-tauri-drag-region + workspace picker + traffic-light fix.

import { IconSearch, IconCommand, IconSparkle } from '../lib/icons'
import { useUiStore } from '../stores/uiStore'
import { useAppStore } from '../stores/appStore'
import { pickDirectory } from '../lib/tauri'

export function TitleBar(): React.ReactElement {
  const aiPanelOpen = useUiStore((s) => s.aiPanelOpen)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)
  const toggleCmdPalette = useAppStore((s) => s.toggleCmdPalette)
  const workspacePath = useUiStore((s) => s.workspacePath)
  const setWorkspacePath = useUiStore((s) => s.setWorkspacePath)

  // Derive display label from full path: show last path segment or "workspace".
  const wsLabel = (() => {
    if (!workspacePath || workspacePath === '~/finagent') return 'workspace'
    // Handle both / and \ separators.
    const parts = workspacePath.replace(/\\/g, '/').split('/')
    return parts[parts.length - 1] || 'workspace'
  })()

  async function handlePickWorkspace() {
    const dir = await pickDirectory()
    if (dir) {
      setWorkspacePath(dir)
    }
  }

  return (
    // data-tauri-drag-region on outer container lets the user drag the window
    // by clicking anywhere in the titlebar that isn't an interactive element.
    <div className="titlebar" data-tauri-drag-region>
      {/* Traffic-light visual placeholder.
          pointer-events: none lets the real macOS Overlay traffic-light buttons
          (injected by Tauri at trafficLightPosition x:14 y:13) receive clicks. */}
      <div className="traffic-lights" style={{ pointerEvents: 'none' }}>
        <div className="light close" />
        <div className="light min" />
        <div className="light max" />
      </div>

      {/* Central title — also a drag region; workspace segment is clickable. */}
      <div className="titlebar-title" data-tauri-drag-region>
        <span className="name">FinAgent</span>
        <span className="sep">·</span>
        <span
          className="titlebar-workspace"
          title="点击更改 workspace 目录"
          onClick={handlePickWorkspace}
          // Stop drag-region propagation so the click registers correctly.
          data-tauri-drag-region="false"
        >
          {wsLabel}
        </span>
        <span className="sep">·</span>
        <span>v0.4.1</span>
      </div>

      <div className="titlebar-actions">
        <button
          className="tb-btn"
          title="搜索 ⌘P"
          onClick={toggleCmdPalette}
        >
          <IconSearch size={16} />
        </button>
        <button
          className="tb-btn"
          title="命令面板 ⌘⇧P"
          onClick={toggleCmdPalette}
        >
          <IconCommand size={16} />
        </button>
        <button
          className={`tb-btn${aiPanelOpen ? ' active' : ''}`}
          title="呼出/收起 AI 助手 ⌘L"
          onClick={toggleAiPanel}
        >
          <IconSparkle size={16} />
        </button>
      </div>
    </div>
  )
}
