import { useNavigate, useLocation } from 'react-router-dom'
import {
  IconHome,
  IconTrendingUp,
  IconFileText,
  IconSettings,
} from '../lib/icons'

interface ActBtnProps {
  icon: React.ReactElement
  label: string
  path?: string
  active?: boolean
  onClick?: () => void
}

function ActBtn({ icon, label, path, active, onClick }: ActBtnProps): React.ReactElement {
  const navigate = useNavigate()

  function handleClick() {
    if (onClick) {
      onClick()
    } else if (path) {
      navigate(path)
    }
  }

  return (
    <button
      className={`act-btn${active ? ' active' : ''}`}
      title={label}
      onClick={handleClick}
    >
      {icon}
    </button>
  )
}

export function ActivityBar(): React.ReactElement {
  const location = useLocation()
  const isActive = (prefix: string) => location.pathname.startsWith(prefix)

  return (
    <div className="activity-bar" data-testid="activitybar">
      <ActBtn
        icon={<IconHome size={18} />}
        label="Dashboard"
        path="/dashboard"
        active={isActive('/dashboard')}
      />
      <ActBtn
        icon={<IconTrendingUp size={18} />}
        label="Stocks"
        path="/stocks"
        active={isActive('/stocks')}
      />
      <ActBtn
        icon={<IconFileText size={18} />}
        label="Library"
        path="/library"
        active={isActive('/library')}
      />
      <ActBtn
        icon={<IconSettings size={18} />}
        label="Settings"
        path="/settings"
        active={isActive('/settings')}
      />

      <div className="spacer" />
    </div>
  )
}
