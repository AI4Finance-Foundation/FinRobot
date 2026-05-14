import { Outlet } from 'react-router-dom'
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
import Dashboard from '../views/Dashboard'

// TopBar and LeftNav are intentionally NOT imported here.
// They remain on disk for Phase 6 cleanup.

export function AppShell(): React.ReactElement {
  const chatExpanded = useUiPrefs((s) => s.chatExpanded)
  const toggleChat = useUiPrefs((s) => s.toggleChat)
  const activeTab = useUiStore(selectActiveTab)

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
            {activeTab?.kind === 'dashboard' ? (
              <Dashboard />
            ) : (
              /* Phase 3 will route non-dashboard tabs properly. */
              <Outlet />
            )}
          </div>
        </main>

        <RightChatPanel expanded={chatExpanded} onToggle={toggleChat} />
      </div>

      <StatusBar />
      <CmdKOverlay />
    </div>
  )
}
