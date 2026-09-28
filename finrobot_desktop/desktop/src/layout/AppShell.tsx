// AppShell — cosmic cockpit shell: TitleBar (with top nav) + main content area
// + RightChatPanel. The left 64px icon Sidebar was retired when its nav moved
// up into the TitleBar (FinRobot.html cockpit shell); Explorer, EditorTabs,
// Breadcrumb, and tab management were removed earlier in Desktop V1 cleanup.

import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { TitleBar } from './TitleBar'
import { RightChatPanel } from './RightChatPanel'
import { ErrorBoundary } from '../components/ErrorBoundary'
import ToastContainer from '../components/Toast'
import { MandatoryUpdateGate } from '../components/MandatoryUpdateGate'
import { AiOnboardingGate } from '../components/AiOnboardingGate'
import { BootSplash } from '../components/BootSplash'
import { AppFooter } from '../components/AppFooter'
import { useHealth } from '../hooks/useHealth'
import { useUiStore } from '../stores/uiStore'
import { useUpdaterStore } from '../stores/updaterStore'
import { pickDirectory, isTauri, DEFAULT_WORKSPACE_PATH } from '../lib/tauri'
import { AI_CHAT_ENABLED } from '../config/features'

const WELCOME_SHOWN_KEY = 'finrobot-welcome-shown'

export function AppShell(): React.ReactElement {
  const workspacePath = useUiStore((s) => s.workspacePath)
  const setWorkspacePath = useUiStore((s) => s.setWorkspacePath)
  const location = useLocation()

  // Sidecar boot gate: while the backend has never answered this session (and
  // the startup grace window is still open), render the BootSplash INSTEAD of
  // the routed page — pages then mount fresh against a live backend instead of
  // erroring against a booting one. See useHealth for the 'starting' contract.
  const { data: health } = useHealth()
  const booting = health?.level === 'starting'

  // The Research homepage is the luminous cockpit: paint the cockpit glow at
  // the SHELL level (behind the title bar too, so it frosts into it rather
  // than reading as a black frame). Other routes keep the dark base.
  const onHome = location.pathname === '/' || location.pathname.startsWith('/research')

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

  // Silent auto-update check (Tauri only). The updater is a POLL, not a push,
  // so we check shortly after launch AND every 2h — a long-running session then
  // still surfaces the TitleBar pill within a couple hours, no restart needed.
  // A found update shows the pill; up-to-date / errors stay silent here (see
  // updaterStore.check, which no-ops while a check or install is in flight).
  useEffect(() => {
    if (!isTauri()) return
    const check = () => void useUpdaterStore.getState().check()
    const initial = setTimeout(check, 4000)
    const interval = setInterval(check, 2 * 60 * 60 * 1000)
    return () => {
      clearTimeout(initial)
      clearInterval(interval)
    }
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
    <div className={`app-shell${onHome ? ' cockpit-bg cockpit-shell' : ''}`}>
      <TitleBar />
      <div className="app-body">
        <main id="main-scroll" className="main-content">
          {booting ? (
            <BootSplash />
          ) : (
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          )}
        </main>
        {AI_CHAT_ENABLED && !booting ? <RightChatPanel /> : null}
      </div>
      <AppFooter />
      {/* v5: toast portal — mounted at shell level so every page / section
          can pop toasts (pipeline launch / completion / errors). */}
      <ToastContainer />
      {/* Cosmic: backdrop starfield (two parallax layers, CSS-only). */}
      <div className="cosmic-stars" aria-hidden />
      <div className="cosmic-stars cosmic-stars-fast" aria-hidden />
      {/* Mandatory-update gate — full-screen block when the installed version is
          below the published floor. Renders null unless mandatory. */}
      <MandatoryUpdateGate />
      {/* First-run AI onboarding — dismissible overlay shown once when no LLM
          model is configured yet. Renders null once a model is set. */}
      <AiOnboardingGate />
    </div>
  )
}
