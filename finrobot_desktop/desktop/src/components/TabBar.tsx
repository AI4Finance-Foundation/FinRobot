import { useAppStore, type ActiveTab } from '../stores/appStore'

const TABS: { key: ActiveTab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'financials', label: 'Financials' },
  { key: 'valuation', label: 'Valuation' },
  { key: 'peers', label: 'Peers' },
  { key: 'compare', label: 'Compare' },
]

export default function TabBar() {
  const activeTab = useAppStore((s) => s.activeTab)
  const setActiveTab = useAppStore((s) => s.setActiveTab)

  return (
    <div className="tab-bar">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          className={`tab-btn${activeTab === tab.key ? ' active' : ''}`}
          onClick={() => setActiveTab(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
