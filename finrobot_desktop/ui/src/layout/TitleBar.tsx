import { IconSearch, IconCommand, IconSparkle } from '../lib/icons'
import { useUiStore } from '../stores/uiStore'
import { useAppStore } from '../stores/appStore'

export function TitleBar(): React.ReactElement {
  const aiPanelOpen = useUiStore((s) => s.aiPanelOpen)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)
  const toggleCmdPalette = useAppStore((s) => s.toggleCmdPalette)

  return (
    <div className="titlebar">
      <div className="traffic-lights">
        <div className="light close" />
        <div className="light min" />
        <div className="light max" />
      </div>

      <div className="titlebar-title">
        <span className="name">FinAgent</span>
        <span className="sep">·</span>
        <span>workspace</span>
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
