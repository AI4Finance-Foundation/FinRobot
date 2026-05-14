// AppShell — Phase 3: full Tab-kind → Page routing.
// Phase 4 will wire: RightChatPanel context, PipelinePage runner modal.
// Do NOT import RightChatPanel changes here — handled in Phase 4.

import { useEffect } from 'react'
import { Outlet, useParams, useLocation, useNavigate } from 'react-router-dom'
import { TitleBar } from './TitleBar'
import { ActivityBar } from './ActivityBar'
import { Explorer } from './Explorer'
import { EditorTabs } from './EditorTabs'
import { Breadcrumb } from './Breadcrumb'
import { RightChatPanel } from './RightChatPanel'
import { CmdKOverlay } from './CmdKOverlay'
import StatusBar from '../components/StatusBar'
import { useUiPrefs } from '../i18n'
import { useUiStore, selectActiveTab } from '../stores/uiStore'

// Views / pages
import Dashboard from '../views/Dashboard'
import { PipelinePage } from '../views/PipelinePage'
import { ReportPage } from '../views/ReportPage'
import { MonitorPage } from '../views/MonitorPage'
import { DataSourcesPage } from '../views/DataSourcesPage'
import { WatchlistPage } from '../views/WatchlistPage'
import { SettingsPage } from '../pages/SettingsPage'

// TopBar and LeftNav are intentionally NOT imported here.
// They remain on disk for Phase 6 cleanup.

export function AppShell(): React.ReactElement {
  const chatExpanded = useUiPrefs((s) => s.chatExpanded)
  const toggleChat = useUiPrefs((s) => s.toggleChat)
  const activeTab = useUiStore(selectActiveTab)
  const openTab = useUiStore((s) => s.openTab)
  const setActivityBarSelection = useUiStore((s) => s.setActivityBarSelection)

  // ── URL → Tab sync ──────────────────────────────────────────
  // Deep-link: /stocks/:ticker → watchlist Tab
  // /library        → reports activity
  // /settings       → settings Tab

  const { ticker } = useParams<{ ticker?: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    const path = location.pathname

    if (path.startsWith('/settings')) {
      openTab({ id: 'settings', kind: 'settings', title: '设置' })
    } else if (path.startsWith('/library')) {
      setActivityBarSelection('reports')
    } else if (ticker) {
      // /stocks/:ticker → open a watchlist tab for that ticker
      const tabId = `watchlist:${ticker.toUpperCase()}`
      openTab({
        id: tabId,
        kind: 'watchlist',
        title: ticker.toUpperCase(),
        payload: { ticker: ticker.toUpperCase() },
      })
    }
  // Only run on location/ticker change; openTab and setActivityBarSelection are stable
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, ticker])

  // ── Tab kind → content ──────────────────────────────────────

  const kind = activeTab?.kind ?? 'dashboard'
  let content: React.ReactNode

  switch (kind) {
    case 'dashboard':
      content = <Dashboard />
      break
    case 'pipeline':
      content = (
        <PipelinePage
          pipelineId={(activeTab?.payload?.pipelineId as string | undefined) ?? ''}
        />
      )
      break
    case 'report':
      content = (
        <ReportPage
          reportId={(activeTab?.payload?.reportId as string | undefined) ?? ''}
        />
      )
      break
    case 'monitor':
      content = <MonitorPage />
      break
    case 'datasources':
      content = <DataSourcesPage />
      break
    case 'watchlist':
      content = (
        <WatchlistPage
          ticker={activeTab?.payload?.ticker as string | undefined}
        />
      )
      break
    case 'settings':
      content = <SettingsPage />
      break
    case 'about':
    default:
      content = <Outlet />
      break
  }

  return (
    <div className="app-shell">
      <TitleBar />

      <div className="app-body">
        <ActivityBar />
        <Explorer />

        <main className="editor">
          <EditorTabs />
          <Breadcrumb />
          <div className="editor-content">
            {content}
          </div>
        </main>

        <RightChatPanel expanded={chatExpanded} onToggle={toggleChat} />
      </div>

      <StatusBar />
      <CmdKOverlay />
    </div>
  )
}
