// TitleBar — cosmic cockpit shell (FinRobot.html §5.1).
//
// Reserves 72px on the left for Tauri's native macOS traffic lights (overlay
// titleBarStyle). Layout left→right: traffic lights · FINROBOT brandmark ·
// the three product doors (Research / Coverage / Settings) as a top nav ·
// spacer · AI panel toggle. The old left Sidebar moved its nav up here, so
// there is no 64px icon rail any more. No "Engine Online / Data Feed · LIVE"
// status pills and no avatar — the assistant is on-demand, not a live process,
// so a liveness claim would be dishonest (and the design dropped them too).

import { useNavigate, useLocation } from 'react-router-dom'
import { useUiStore } from '../stores/uiStore'
import { useI18n } from '../i18n'
import { startWindowDrag } from '../lib/tauri'
import { UpdatePill } from '../components/UpdatePill'

interface NavDoor {
  /** i18n message id resolved at render time. */
  labelKey: string
  path: string
  /** Path prefixes that should light this door as active. */
  activePaths: string[]
}

// The three top-level product doors (router.tsx: "Research, Coverage, and
// Settings"). Research owns the per-ticker workspace (/stocks/:ticker);
// Coverage owns the compare view; Settings is standalone.
const DOORS: NavDoor[] = [
  { labelKey: 'nav.research', path: '/research', activePaths: ['/research', '/stocks'] },
  { labelKey: 'nav.coverage', path: '/coverage', activePaths: ['/coverage', '/compare'] },
  { labelKey: 'nav.settings', path: '/settings', activePaths: ['/settings'] },
]

export function TitleBar(): React.ReactElement {
  const aiPanelOpen = useUiStore((s) => s.aiPanelOpen)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)
  const { t, locale } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()

  function isActive(door: NavDoor): boolean {
    return door.activePaths.some((p) => location.pathname.startsWith(p))
  }

  // Whole-bar window drag. Tauri v2's data-tauri-drag-region only works with
  // decorations:false; we keep native traffic lights (decorations:true +
  // titleBarStyle Overlay), so drag goes through startDragging() on mousedown.
  // Interactive controls (buttons) are skipped so clicks still register.
  const onTitleBarMouseDown = (e: React.MouseEvent<HTMLDivElement>): void => {
    if (e.button !== 0) return
    if ((e.target as HTMLElement).closest('button, a, input, [role="button"]')) return
    startWindowDrag(e.detail === 2)
  }

  return (
    <div
      className="titlebar"
      onMouseDown={onTitleBarMouseDown}
      data-testid="titlebar"
      style={{
        position: 'relative',
        height: 44,
        padding: '0 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        // Translucent on every route — the titlebar frosts into the cosmic
        // backdrop (homepage cockpit or content-page shell glow) so there's no
        // solid dark bar / seam at the top.
        background: 'var(--cockpit-bar-bg)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderBottom: '1px solid var(--border-faint)',
        zIndex: 80,
      }}
    >
      {/* macOS traffic lights overlay reservation */}
      <div style={{ width: 72, flexShrink: 0 }} />

      {/* Brandmark (FinRobot.html `.brand`) — conic-gradient mark + FinRobot
          wordmark (Robot in cyan) + OPEN RESEARCH tag. Purely decorative: no
          click/interaction (the logo is just the logo). ⌘K still opens the
          command palette via its own shortcut. */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          color: 'var(--text-primary)',
          flexShrink: 0,
        }}
      >
        <span className="tb-brand-mark" aria-hidden />
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontWeight: 600,
            fontSize: 15,
            letterSpacing: '0.04em',
          }}
        >
          Fin<b style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>Robot</b>
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 9.5,
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: 'var(--text-muted)',
            border: '1px solid var(--border-soft)',
            borderRadius: 4,
            padding: '2px 6px',
          }}
        >
          OPEN RESEARCH
        </span>
      </div>

      {/* Top nav — the three product doors. */}
      <nav className="tb-nav" aria-label={locale === 'zh' ? '主导航' : 'Primary'}>
        {DOORS.map((door) => {
          const active = isActive(door)
          return (
            <button
              key={door.path}
              type="button"
              className={`tb-nav-link${active ? ' active' : ''}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => navigate(door.path)}
            >
              <span className="tb-nav-dot" aria-hidden />
              {t(door.labelKey)}
            </button>
          )
        })}
      </nav>

      <div style={{ flex: 1 }} />

      {/* Update pill — renders only when an update is available / installing. */}
      <UpdatePill />

      {/* AI panel toggle */}
      <button
        className={`tb-btn${aiPanelOpen ? ' active' : ''}`}
        type="button"
        aria-label={t('shell.titlebar.aiAssistant')}
        title={t('shell.titlebar.aiAssistant')}
        onClick={toggleAiPanel}
        style={{
          width: 40,
          height: 32,
          display: 'grid',
          placeItems: 'center',
          border: `1px solid ${aiPanelOpen ? 'var(--border-glow)' : 'var(--border-soft)'}`,
          borderRadius: 8,
          background: aiPanelOpen ? 'var(--primary-soft)' : 'transparent',
          color: aiPanelOpen ? 'var(--primary)' : 'var(--text-secondary)',
          cursor: 'pointer',
          transition: 'all 0.2s',
          boxShadow: aiPanelOpen ? 'var(--glow-blue)' : 'none',
          fontFamily: 'var(--font-display)',
          fontSize: 11,
          letterSpacing: '1px',
          flexShrink: 0,
        }}
      >
        AI
      </button>
    </div>
  )
}
