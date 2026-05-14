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

// TopBar and LeftNav are intentionally NOT imported here.
// They remain on disk for Phase 6 cleanup.

export function AppShell(): React.ReactElement {
  const chatExpanded = useUiPrefs((s) => s.chatExpanded)
  const toggleChat = useUiPrefs((s) => s.toggleChat)

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
            {/* Phase 2 will replace Outlet with Dashboard when activeTab === 'dashboard'.
                Phase 3 will route by activeTab. For now Outlet renders the router pages. */}
            <Outlet />
          </div>
        </main>

        <RightChatPanel expanded={chatExpanded} onToggle={toggleChat} />
      </div>

      <StatusBar />
      <CmdKOverlay />
    </div>
  )
}
