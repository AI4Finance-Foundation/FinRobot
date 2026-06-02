// Sidebar — cosmic 64px slim icon-only nav (spec §5.2).
//
// Vertical icon strip: top = primary nav, divider, bottom = settings.
// Active state shows a 3px blue glowing left rail (spec §5.2).

import { useMemo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { IconTrendingUp, IconSettings } from '../lib/icons'
import { useRunStreamStore } from '../stores/runStreamStore'
import { useNavMemoryStore } from '../stores/navMemoryStore'
import { useI18n } from '../i18n'

interface NavItem {
  /** i18n key resolved at render time via useI18n. */
  labelKey: string
  path: string
  Icon: typeof IconTrendingUp
}

// The investment-committee debate is reached from inside a research report
// (ReportToolbar → onOpenIcDebate), not a top-level menu — it operates on a
// specific artifact, so a standalone nav item was a context-less dead-end door.
const TOP_NAV: NavItem[] = [{ labelKey: 'nav.stocks', path: '/stocks', Icon: IconTrendingUp }]

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

  const lastStocksPath = useNavMemoryStore((s) => s.lastStocksPath)

  function isActive(path: string): boolean {
    return location.pathname.startsWith(path)
  }

  function handleClick(path: string, event?: React.MouseEvent): void {
    // /stocks click resolution: running ticker > remembered deep path >
    // landing. Hold ⌘/Ctrl to force-skip memory and reach the landing
    // page (escape hatch when the remembered path is stale).
    if (path === '/stocks') {
      const forceLanding = !!event && (event.metaKey || event.ctrlKey)
      if (forceLanding) {
        navigate('/stocks')
        return
      }
      if (runningTickers.length > 0) {
        navigate(`/stocks/${runningTickers[0]}`)
        return
      }
      if (lastStocksPath && lastStocksPath !== location.pathname) {
        navigate(lastStocksPath)
        return
      }
    }
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
            active={isActive(item.path)}
            onClick={(e) => handleClick(item.path, e)}
            badge={item.path === '/stocks' ? runningTickers.length : 0}
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
            active={isActive(item.path)}
            onClick={(e) => handleClick(item.path, e)}
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
  const { t } = useI18n()
  const label = t(labelKey)
  const runningLabel = t('shell.sidebar.runningCount', { count: badge })

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
        if (!active) {
          e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
          e.currentTarget.style.color = 'var(--text-primary)'
        }
      }}
      onMouseLeave={(e) => {
        if (!active) {
          e.currentTarget.style.background = 'transparent'
          e.currentTarget.style.color = 'var(--text-secondary)'
        }
      }}
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
            color: '#fff',
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
    </button>
  )
}
