import {
  IconDashboard,
  IconPipeline,
  IconFileText,
  IconActivity,
  IconDatabase,
  IconStar,
  IconGitHub,
  IconSettings,
} from '../lib/icons'
import { useUiStore } from '../stores/uiStore'
import type { ActivityKey } from '../stores/uiStore'
import { openExternal } from '../lib/tauri'

interface ActBtnProps {
  icon: React.ReactElement
  label: string
  actKey?: ActivityKey
  badge?: string
  onClick?: () => void
  active?: boolean
}

function ActBtn({ icon, label, actKey, badge, onClick, active }: ActBtnProps): React.ReactElement {
  const selection = useUiStore((s) => s.activityBarSelection)
  const setActivityBarSelection = useUiStore((s) => s.setActivityBarSelection)

  const isActive = active ?? (actKey !== undefined && selection === actKey)

  function handleClick() {
    if (onClick) {
      onClick()
    } else if (actKey) {
      setActivityBarSelection(actKey)
    }
  }

  return (
    <button
      className={`act-btn${isActive ? ' active' : ''}`}
      title={label}
      onClick={handleClick}
    >
      {icon}
      {badge && <span className="badge">{badge}</span>}
    </button>
  )
}

export function ActivityBar(): React.ReactElement {
  async function handleGitHub() {
    await openExternal('https://github.com/finagent/finagent')
  }

  return (
    <div className="activity-bar">
      <ActBtn icon={<IconDashboard size={18} />} label="工作台" actKey="dashboard" />
      <ActBtn icon={<IconPipeline size={18} />} label="Pipeline 库" actKey="pipelines" />
      <ActBtn icon={<IconFileText size={18} />} label="报告库" actKey="reports" />
      <ActBtn
        icon={<IconActivity size={18} />}
        label="任务监控"
        actKey="monitor"
        badge="3"
      />
      <ActBtn icon={<IconDatabase size={18} />} label="数据源" actKey="datasources" />
      <ActBtn icon={<IconStar size={18} />} label="自选股" actKey="watchlist" />

      <div className="spacer" />

      <ActBtn
        icon={<IconGitHub size={18} />}
        label="GitHub"
        onClick={handleGitHub}
      />
      <ActBtn icon={<IconSettings size={18} />} label="设置" actKey="settings" />
    </div>
  )
}
