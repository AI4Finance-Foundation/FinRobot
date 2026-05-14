// Breadcrumb — Phase 3: bound to active Tab from uiStore.
// Middle segments are clickable → setActivityBarSelection.
// Last segment is non-interactive.

import { useUiStore, selectActiveTab } from '../stores/uiStore'
import type { TabKind, ActivityKey } from '../stores/uiStore'

// Map tab kind to its parent ActivityKey for navigation
const KIND_TO_ACTIVITY: Record<TabKind, ActivityKey | null> = {
  dashboard:   null,
  pipeline:    'pipelines',
  report:      'reports',
  monitor:     'monitor',
  datasources: 'datasources',
  watchlist:   'watchlist',
  settings:    'settings',
  about:       null,
}

// Human-readable segment labels for the middle tier
const MIDDLE_LABEL: Partial<Record<TabKind, string>> = {
  pipeline:    'Pipelines',
  report:      '报告',
  monitor:     '任务监控',
  datasources: '数据源',
  watchlist:   '自选股',
  settings:    '设置',
  about:       '关于',
}

interface ClickableSegProps {
  label: string
  onClick: () => void
}

function ClickableSeg({ label, onClick }: ClickableSegProps) {
  return (
    <span
      className="seg"
      onClick={onClick}
      style={{ cursor: 'pointer' }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
    >
      {label}
    </span>
  )
}

export function Breadcrumb(): React.ReactElement {
  const activeTab = useUiStore(selectActiveTab)
  const setActivityBarSelection = useUiStore((s) => s.setActivityBarSelection)

  const kind = activeTab?.kind ?? 'dashboard'
  const title = activeTab?.title ?? '工作台首页'
  const activityKey = KIND_TO_ACTIVITY[kind]
  const middleLabel = MIDDLE_LABEL[kind]

  // Build segments
  const segments: React.ReactNode[] = [
    <span key="root" className="seg">FinAgent</span>,
    <span key="sep1" className="sep">›</span>,
    <span key="ws" className="seg">workspace</span>,
  ]

  if (kind === 'dashboard') {
    segments.push(<span key="sep2" className="sep">›</span>)
    segments.push(<span key="leaf" className="seg">工作台首页</span>)
  } else if (middleLabel !== undefined && activityKey !== null) {
    segments.push(<span key="sep2" className="sep">›</span>)
    segments.push(
      <ClickableSeg
        key="middle"
        label={middleLabel}
        onClick={() => setActivityBarSelection(activityKey)}
      />,
    )
    // Single-page kinds (monitor, datasources) don't need a leaf segment
    if (kind !== 'monitor' && kind !== 'datasources') {
      segments.push(<span key="sep3" className="sep">›</span>)
      segments.push(<span key="leaf" className="seg">{title}</span>)
    }
  } else if (middleLabel !== undefined) {
    // about / other with no activityKey
    segments.push(<span key="sep2" className="sep">›</span>)
    segments.push(<span key="leaf" className="seg">{title}</span>)
  }

  return (
    <div className="breadcrumb">
      {segments}
    </div>
  )
}
