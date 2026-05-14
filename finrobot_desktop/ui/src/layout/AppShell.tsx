// AppShell — Phase 5: Tauri integration (frameless, global shortcut, workspace dialog).

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
import { useUiStore, selectActiveTab } from '../stores/uiStore'
import { registerShortcut, pickDirectory, isTauri, DEFAULT_WORKSPACE_PATH } from '../lib/tauri'

// Views / pages
import Dashboard from '../views/Dashboard'
import { PipelinePage } from '../views/PipelinePage'
import { ReportPage } from '../views/ReportPage'
import { MonitorPage } from '../views/MonitorPage'
import { DataSourcesPage } from '../views/DataSourcesPage'
import { WatchlistPage } from '../views/WatchlistPage'
import { SettingsPage } from '../pages/SettingsPage'
import AboutView from '../views/AboutView'

// TopBar and LeftNav are intentionally NOT imported here.
// They remain on disk for Phase 6 cleanup.

const WELCOME_SHOWN_KEY = 'finagent-welcome-shown'

export function AppShell(): React.ReactElement {
  const activeTab = useUiStore(selectActiveTab)
  const openTab = useUiStore((s) => s.openTab)
  const setActivityBarSelection = useUiStore((s) => s.setActivityBarSelection)
  const workspacePath = useUiStore((s) => s.workspacePath)
  const setWorkspacePath = useUiStore((s) => s.setWorkspacePath)

  // ⌘L / Ctrl+L → toggle AI panel (T4.5, upgraded to async global shortcut in T5.3)
  useEffect(() => {
    let cleanup: (() => void) | null = null
    registerShortcut({ key: 'l', mod: true }, () => {
      useUiStore.getState().toggleAiPanel()
    }).then((c) => {
      cleanup = c
    })
    return () => cleanup?.()
  }, [])

  // T5.6 — First-launch workspace picker.
  // Only triggers in Tauri env when workspace is still the default and the user
  // hasn't already dismissed the prompt. Uses native dialog; no Welcome page.
  useEffect(() => {
    if (!isTauri()) return
    if (workspacePath !== DEFAULT_WORKSPACE_PATH) return
    if (localStorage.getItem(WELCOME_SHOWN_KEY)) return

    // Mark shown immediately so re-renders don't re-trigger.
    localStorage.setItem(WELCOME_SHOWN_KEY, 'true')

    pickDirectory().then((dir) => {
      if (dir) {
        setWorkspacePath(dir)
      }
      // User cancelled → keep default; don't re-prompt until localStorage is cleared.
    })
  // Only run once on mount; workspacePath/setWorkspacePath refs are stable.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
      content = <AboutView />
      break
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

        <RightChatPanel />
      </div>

      <StatusBar />
      <CmdKOverlay />
    </div>
  )
}
