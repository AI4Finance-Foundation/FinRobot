import { useUiStore } from '../stores/uiStore'
import type { Tab } from '../stores/uiStore'

// Icon map: minimal inline SVGs matching prototype tab icons.
function TabIcon({ kind }: { kind: Tab['kind'] }): React.ReactElement {
  switch (kind) {
    case 'dashboard':
      return (
        <svg className="ic ic-svg" viewBox="0 0 24 24" width={12} height={12}>
          <rect x="3" y="3" width="18" height="18" rx="2" />
        </svg>
      )
    case 'report':
      return (
        <svg className="ic ic-svg" viewBox="0 0 24 24" width={12} height={12}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        </svg>
      )
    case 'pipeline':
    case 'monitor':
      return (
        <svg className="ic ic-svg" viewBox="0 0 24 24" width={12} height={12}>
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
      )
    default:
      return (
        <svg className="ic ic-svg" viewBox="0 0 24 24" width={12} height={12}>
          <rect x="3" y="3" width="18" height="18" rx="2" />
        </svg>
      )
  }
}

export function EditorTabs(): React.ReactElement {
  const openTabs = useUiStore((s) => s.openTabs)
  const activeTabId = useUiStore((s) => s.activeTabId)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const closeTab = useUiStore((s) => s.closeTab)

  return (
    <div className="tabs" data-testid="editor-tabs">
      {openTabs.map((tab) => {
        const isActive = tab.id === activeTabId
        return (
          <div
            key={tab.id}
            className={`tab${isActive ? ' active' : ''}${tab.dirty ? ' dirty' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <TabIcon kind={tab.kind} />
            <span>{tab.title}</span>
            {/* dashboard tab has no close button — closeTab always reverts to dashboard anyway */}
            {tab.id !== 'dashboard' && (
              <span
                className="close"
                onClick={(e) => {
                  e.stopPropagation()
                  closeTab(tab.id)
                }}
              >
                {tab.dirty ? '●' : '×'}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
