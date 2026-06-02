// AppShell — simplified shell: Sidebar + main content area + RightChatPanel.
// Explorer, EditorTabs, Breadcrumb, and tab management removed in Desktop V1 cleanup.

import { useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { TitleBar } from './TitleBar'
import { Sidebar } from './Sidebar'
import { RightChatPanel } from './RightChatPanel'
import { CmdKOverlay } from './CmdKOverlay'
import StatusBar from '../components/StatusBar'
import ToastContainer from '../components/Toast'
import { CursorCanvas } from '../components/CursorCanvas'
import { useUiStore } from '../stores/uiStore'
import { registerShortcut, pickDirectory, isTauri, DEFAULT_WORKSPACE_PATH } from '../lib/tauri'

const WELCOME_SHOWN_KEY = 'finrobot-welcome-shown'

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

  // 2026-05-27 perf: pause CSS animations (cosmic-stars × 2 layers,
  // anywhere else gated by body.app-bg) when the Tauri window is hidden
  // or backgrounded. WebKit does NOT auto-pause CSS animations on
  // background WebViews the way browsers do for hidden tabs, so an
  // infinite drift transform keeps the GPU compositor warm even when
  // the user is looking at a different app. Negligible work; large win
  // on laptop fan when the user CMD-tabs away.
  useEffect(() => {
    function apply() {
      const hidden = typeof document !== 'undefined' && document.hidden
      const focused = typeof document !== 'undefined' && document.hasFocus()
      document.body.classList.toggle('app-bg', hidden || !focused)
    }
    apply()
    document.addEventListener('visibilitychange', apply)
    window.addEventListener('focus', apply)
    window.addEventListener('blur', apply)
    return () => {
      document.removeEventListener('visibilitychange', apply)
      window.removeEventListener('focus', apply)
      window.removeEventListener('blur', apply)
    }
  }, [])

  return (
    <div className="app-shell">
      <TitleBar />
      <div className="app-body">
        <Sidebar />
        <main id="main-scroll" className="main-content">
          <Outlet />
        </main>
        <RightChatPanel />
      </div>
      <StatusBar />
      <CmdKOverlay />
      {/* v5: toast portal — mounted at shell level so every page / section
          can pop toasts (pipeline launch / completion / errors). */}
      <ToastContainer />
      {/* Cosmic: backdrop starfield + bezier-spring cursor trail.
          Both lazy-mount via useEffect; safe under SSR / Vitest jsdom. */}
      <div className="cosmic-stars" aria-hidden />
      <div className="cosmic-stars cosmic-stars-fast" aria-hidden />
      <CursorCanvas />
    </div>
  )
}
