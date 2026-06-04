// Sidebar — cosmic 64px slim icon-only nav (spec §5.2).
//
// Vertical icon strip: top = primary nav, divider, bottom = settings.
// Active state shows a 3px blue glowing left rail (spec §5.2).

import { useMemo, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { IconDashboard, IconSearch, IconSettings } from '../lib/icons'
import { useRunStreamStore } from '../stores/runStreamStore'
import { useI18n } from '../i18n'

interface NavItem {
  /** i18n key resolved at render time via useI18n. */
  labelKey: string
  path: string
  activePaths?: string[]
  Icon: typeof IconDashboard
}

// Research is the search-first homepage and owns the per-ticker workspace.
// Coverage is the archive/management desk for studied tickers.
const TOP_NAV: NavItem[] = [
  {
    labelKey: 'nav.research',
    path: '/research',
    activePaths: ['/research', '/stocks'],
    Icon: IconSearch,
  },
  {
    labelKey: 'nav.coverage',
    path: '/coverage',
    activePaths: ['/coverage', '/compare'],
    Icon: IconDashboard,
  },
]

const BOTTOM_NAV: NavItem[] = [{ labelKey: 'nav.settings', path: '/settings', Icon: IconSettings }]

const SIDEBAR_W = 64
const ICON_BOX = 44

export function Sidebar(): React.ReactElement {
  const navigate = useNavigate()
  const location = useLocation()

  // Run badge: pulses on /stocks icon when something is running.
  const activeRuns = useRunStreamStore((s) => s.runs)
  const runningTickers = useMemo(
    () =>
      Object.values(activeRuns)
        .filter((r) => r.status === 'running')
        .map((r) => r.ticker),
    [activeRuns],
  )

  function isActive(item: NavItem): boolean {
    const paths = item.activePaths ?? [item.path]
    return paths.some((path) => location.pathname.startsWith(path))
  }

  function handleClick(path: string): void {
    navigate(path)
  }

  return (
    <aside
      className="sidebar"
      data-testid="sidebar"
      style={{
        width: SIDEBAR_W,
        minWidth: SIDEBAR_W,
        height: '100%',
        background: 'var(--sidebar-bg)',
        borderRight: '1px solid var(--border-faint)',
        display: 'flex',
        flexDirection: 'column',
        padding: '16px 0',
        gap: 8,
        flexShrink: 0,
        zIndex: 5,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center' }}>
        {TOP_NAV.map((item) => (
          <SideIcon
            key={item.path}
            item={item}
            active={isActive(item)}
            onClick={() => handleClick(item.path)}
            badge={item.path === '/research' ? runningTickers.length : 0}
          />
        ))}
      </div>

      <div style={{ flex: 1 }} />

      {/* Divider above settings */}
      <div
        style={{
          width: 32,
          height: 1,
          background: 'var(--border-soft)',
          margin: '0 auto 8px',
        }}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center' }}>
        {BOTTOM_NAV.map((item) => (
          <SideIcon
            key={item.path}
            item={item}
            active={isActive(item)}
            onClick={() => handleClick(item.path)}
            badge={0}
          />
        ))}
      </div>
    </aside>
  )
}

interface SideIconProps {
  item: NavItem
  active: boolean
  badge: number
  onClick: (event: React.MouseEvent) => void
}

function SideIcon({ item, active, badge, onClick }: SideIconProps): React.ReactElement {
  const { Icon, labelKey } = item
  const { t, locale } = useI18n()
  const label = t(labelKey)
  const runningLabel = t('shell.sidebar.runningCount', { count: badge })
  // Flyout reveals the nav name on hover/focus. The slim 64px icon-only rail
  // (spec §5.2) otherwise leans on the native `title`, which has a ~1s OS delay
  // and never fires on keyboard focus — leaving the primary nav undiscoverable
  // (BUG-20260602-018). This in-component label appears instantly and on focus,
  // so every destination is self-describing while keeping the icon-only look.
  const [revealed, setRevealed] = useState(false)
  const flyoutText =
    badge > 0
      ? `${label} · ${runningLabel}`
      : `${label}${active ? (locale === 'zh' ? ' · 当前页' : ' · current') : ''}`

  return (
    <button
      type="button"
      onClick={(e) => onClick(e)}
      aria-label={label}
      aria-current={active ? 'page' : undefined}
      title={badge > 0 ? `${label} · ${runningLabel}` : label}
      style={{
        position: 'relative',
        width: ICON_BOX,
        height: ICON_BOX,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: active ? 'var(--primary-soft)' : 'transparent',
        color: active ? 'var(--primary)' : 'var(--text-secondary)',
        border: 'none',
        borderRadius: 'var(--radius-md)',
        cursor: 'pointer',
        transition: 'background 0.15s, color 0.15s',
      }}
      onMouseEnter={(e) => {
        setRevealed(true)
        if (!active) {
          e.currentTarget.style.background = 'var(--secondary-hover)'
          e.currentTarget.style.color = 'var(--text-primary)'
        }
      }}
      onMouseLeave={(e) => {
        setRevealed(false)
        if (!active) {
          e.currentTarget.style.background = 'transparent'
          e.currentTarget.style.color = 'var(--text-secondary)'
        }
      }}
      onFocus={() => setRevealed(true)}
      onBlur={() => setRevealed(false)}
    >
      {/* Glowing active rail (spec §5.2: 3px blue) */}
      {active && (
        <span
          aria-hidden
          style={{
            position: 'absolute',
            left: -10,
            top: 8,
            bottom: 8,
            width: 3,
            borderRadius: 2,
            background: 'var(--primary)',
            boxShadow: 'var(--glow-blue)',
          }}
        />
      )}
      <Icon size={18} />
      {badge > 0 && (
        <span
          aria-label={runningLabel}
          style={{
            position: 'absolute',
            top: 4,
            right: 4,
            minWidth: 16,
            height: 16,
            padding: '0 4px',
            borderRadius: 8,
            background: 'var(--primary)',
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-mono)',
            fontSize: 9,
            fontWeight: 700,
            lineHeight: '16px',
            textAlign: 'center',
            boxShadow: 'var(--glow-blue)',
          }}
        >
          {badge}
        </span>
      )}
      {/* Fast hover/focus flyout label (BUG-20260602-018): names the destination
          instantly, including a keyboard-focus path the native title lacks. */}
      {revealed && (
        <span
          role="tooltip"
          style={{
            position: 'absolute',
            left: ICON_BOX + 6,
            top: '50%',
            transform: 'translateY(-50%)',
            whiteSpace: 'nowrap',
            padding: '4px 8px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-soft)',
            color: 'var(--text-primary)',
            fontSize: 11,
            fontWeight: 500,
            lineHeight: 1.2,
            boxShadow: 'var(--shadow-md)',
            pointerEvents: 'none',
            zIndex: 20,
          }}
        >
          {flyoutText}
        </span>
      )}
    </button>
  )
}
