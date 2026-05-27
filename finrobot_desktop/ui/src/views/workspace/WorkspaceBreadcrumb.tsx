// Shared breadcrumb header for workspace pages (TickerHero / TickerNotFoundView /
// ServiceDownView). Extracted from TickerHero's internal Breadcrumb so the
// error views can render the same identity strip without duplicating logic.

import { Link } from 'react-router-dom'
import { useI18n } from '../../i18n'

interface Props {
  ticker: string
}

export function WorkspaceBreadcrumb({ ticker }: Props): React.ReactElement {
  const { t } = useI18n()
  const linkStyle: React.CSSProperties = { color: 'inherit', textDecoration: 'none' }
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        fontFamily: 'var(--font-mono)',
        fontSize: 10.5,
        color: 'var(--text-muted)',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
      }}
    >
      <Link to="/stocks" style={linkStyle}>
        FINAGENT
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <Link to="/stocks" style={linkStyle}>
        {t('nav.stocks')}
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <span style={{ color: 'var(--accent-cyan)' }}>{ticker}</span>
    </div>
  )
}
