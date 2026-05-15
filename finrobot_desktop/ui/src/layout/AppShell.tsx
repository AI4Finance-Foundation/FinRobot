// AppShell — simplified shell: Sidebar + main content area + RightChatPanel.
// Explorer, EditorTabs, Breadcrumb, and tab management removed in Desktop V1 cleanup.

import { useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { TitleBar } from './TitleBar'
import { Sidebar } from './Sidebar'
import { RightChatPanel } from './RightChatPanel'
import { CmdKOverlay } from './CmdKOverlay'
import StatusBar from '../components/StatusBar'
import { useUiStore } from '../stores/uiStore'
import { registerShortcut, pickDirectory, isTauri, DEFAULT_WORKSPACE_PATH } from '../lib/tauri'

const WELCOME_SHOWN_KEY = 'finagent-welcome-shown'

export function AppShell(): React.ReactElement {
  const workspacePath = useUiStore((s) => s.workspacePath)
  const setWorkspacePath = useUiStore((s) => s.setWorkspacePath)

  // Cmd+L / Ctrl+L → toggle AI panel
  useEffect(() => {
    let cleanup: (() => void) | null = null
    registerShortcut({ key: 'l', mod: true }, () => {
      useUiStore.getState().toggleAiPanel()
    }).then((c) => {
      cleanup = c
    })
    return () => cleanup?.()
  }, [])

  // First-launch workspace picker (Tauri only).
  useEffect(() => {
    if (!isTauri()) return
    if (workspacePath !== DEFAULT_WORKSPACE_PATH) return
    if (localStorage.getItem(WELCOME_SHOWN_KEY)) return

    localStorage.setItem(WELCOME_SHOWN_KEY, 'true')

    pickDirectory().then((dir) => {
      if (dir) {
        setWorkspacePath(dir)
      }
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="app-shell">
      <TitleBar />
      <div className="app-body">
        <Sidebar />
        <main className="main-content">
          <Outlet />
        </main>
        <RightChatPanel />
      </div>
      <StatusBar />
      <CmdKOverlay />
    </div>
  )
}
