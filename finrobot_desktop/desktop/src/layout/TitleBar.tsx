// TitleBar — cosmic cockpit shell (FinRobot.html §5.1).
//
// Reserves 72px on the left for Tauri's native macOS traffic lights (overlay
// titleBarStyle). Layout left→right: traffic lights · FINROBOT brandmark ·
// a centered "HUD instrument cluster" of three icon doors (Research / Coverage
// / Settings) · spacer · UpdatePill (conditional) · AI panel toggle when enabled.
//
// The nav is ICON-FIRST: each door is a recognizable inline-SVG glyph with a
// mono caption beneath it; the active door ignites in cyan with a static neon
// halo + anchor tick (no infinite pulse — the cosmic spec bans >1s decorative
// animation and AppShell pauses animations to keep the GPU cool). Icons are
// language-neutral, so the bar reads the same in zh/en; the caption + title
// carry the localized label. No "Engine Online / LIVE" status pills and no
// avatar — the assistant is on-demand, not a live process, so a liveness claim
// would be dishonest (and the design dropped them too).

import { useNavigate, useLocation } from 'react-router-dom'
import { useUiStore } from '../stores/uiStore'
import { useI18n } from '../i18n'
import { startWindowDrag, isWindows } from '../lib/tauri'
import { UpdatePill } from '../components/UpdatePill'
import { AI_CHAT_ENABLED } from '../config/features'
import { SETTINGS_ALLOWED } from '../config/deployment'
import { BrandAbout } from '../components/BrandAbout'

interface NavDoor {
  /** i18n message id resolved at render time. */
  labelKey: string
  path: string
  /** Path prefixes that should light this door as active. */
  activePaths: string[]
  /** Recognizable inline-SVG glyph (aria-hidden; the caption names it). */
  icon: React.ReactNode
}

// Shared SVG attrs — stroke follows currentColor so the glyph inherits the
// door's idle / hover / active color (tokens only, no per-icon fills).
const ICON_PROPS = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

// Research — a magnifier sweeping a candlestick chart (probe a ticker).
const ResearchIcon = (
  <svg {...ICON_PROPS}>
    <line x1="6" y1="6" x2="6" y2="18" />
    <rect x="4" y="9" width="4" height="6" rx="1" />
    <line x1="11.5" y1="4" x2="11.5" y2="16" />
    <rect x="9.5" y="7" width="4" height="6" rx="1" />
    <circle cx="16.5" cy="13.5" r="3.6" />
    <line x1="19.2" y1="16.2" x2="21.5" y2="18.5" />
  </svg>
)

// Coverage — stacked layers (the library of tracked names).
const CoverageIcon = (
  <svg {...ICON_PROPS}>
    <path d="M12 4 L20 8 L12 12 L4 8 Z" />
    <path d="M4 12 L12 16 L20 12" />
    <path d="M4 16 L12 20 L20 16" />
  </svg>
)

// Settings — the universally-legible cog.
const SettingsIcon = (
  <svg {...ICON_PROPS}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V15z" />
  </svg>
)

// The three top-level product doors (router.tsx: "Research, Coverage, and
// Settings"). Research owns the per-ticker workspace (/stocks/:ticker);
// Settings is standalone.
const DOORS: NavDoor[] = [
  {
    labelKey: 'nav.research',
    path: '/research',
    activePaths: ['/research', '/stocks'],
    icon: ResearchIcon,
  },
  {
    labelKey: 'nav.coverage',
    path: '/coverage',
    activePaths: ['/coverage'],
    icon: CoverageIcon,
  },
  {
    labelKey: 'nav.settings',
    path: '/settings',
    activePaths: ['/settings'],
    icon: SettingsIcon,
  },
]

// Settings configures the whole deployment, so a host that serves this bundle
// to several accounts can withhold that door — see config/deployment.
const VISIBLE_DOORS: NavDoor[] = SETTINGS_ALLOWED
  ? DOORS
  : DOORS.filter((door) => door.path !== '/settings')

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
    <div className="titlebar" onMouseDown={onTitleBarMouseDown} data-testid="titlebar">
      {/* macOS reserves 72px for the native traffic-lights overlay; Windows
          gets a native frame with top-right controls instead, so skip it. */}
      {!isWindows() && <div className="tb-traffic-reserve" aria-hidden />}

      {/* Brandmark — FinRobot wordmark, now the affordance for the About
          popover (version · license · foundation links · copyright). */}
      <BrandAbout />

      {/* HUD instrument cluster — the three product doors, icon-first. */}
      <nav className="tb-cluster" aria-label={locale === 'zh' ? '主导航' : 'Primary'}>
        {VISIBLE_DOORS.map((door) => {
          const active = isActive(door)
          const label = t(door.labelKey)
          return (
            <button
              key={door.path}
              type="button"
              className={`tb-glyph${active ? ' active' : ''}`}
              aria-current={active ? 'page' : undefined}
              title={label}
              onClick={() => navigate(door.path)}
            >
              {door.icon}
              <span className="tb-kicker">{label}</span>
            </button>
          )
        })}
      </nav>

      {/* Right rail — conditional update pill + AI panel toggle. */}
      <div className="tb-rail">
        <UpdatePill />
        {AI_CHAT_ENABLED ? (
          <button
            className={`tb-ai${aiPanelOpen ? ' active' : ''}`}
            type="button"
            aria-label={t('shell.titlebar.aiAssistant')}
            title={t('shell.titlebar.aiAssistant')}
            onClick={toggleAiPanel}
          >
            <span className="tb-ai-dot" aria-hidden />
            AI
          </button>
        ) : null}
      </div>
    </div>
  )
}
