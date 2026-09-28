// Sticky back strip for workspace pages (TickerHero / TickerNotFoundView).
//
// Replaces the old FINROBOT › STOCKS › TSLA breadcrumb. A breadcrumb implies a
// fixed hierarchy the app no longer has (the /stocks landing retired into
// /research), and it scrolled away with the hero. This is a single ← that
// returns to wherever the user came from (useHistoryBack), pinned to the top
// of the scroll viewport so it stays reachable down a long dashboard.

import { useHistoryBack } from '../../hooks/useHistoryBack'
import { useI18n } from '../../i18n'
import { WORKSPACE_FRAME_MAX_WIDTH } from './layout'

interface Props {
  ticker: string
}

export function WorkspaceBackBar({ ticker }: Props): React.ReactElement {
  const { t } = useI18n()
  // Cold-start / deep-link fallback: /research is the search homepage, the
  // natural parent of a single-ticker workspace (TitleBar lights the Research
  // door on /stocks/:ticker).
  const goBack = useHistoryBack('/research')

  return (
    <div
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 40,
        background: 'var(--bg-sticky-88)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        borderBottom: '1px solid var(--border-faint)',
      }}
    >
      <div
        style={{
          maxWidth: WORKSPACE_FRAME_MAX_WIDTH,
          margin: '0 auto',
          padding: '0 32px',
          height: 40,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <button
          type="button"
          data-testid="workspace-back"
          onClick={goBack}
          title={t('nav.back')}
          aria-label={t('nav.back')}
          style={backBtnStyle}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = 'var(--text-primary)'
            e.currentTarget.style.borderColor = 'var(--border-glow)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = 'var(--text-secondary)'
            e.currentTarget.style.borderColor = 'var(--border-soft)'
          }}
        >
          <ArrowLeft />
        </button>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            letterSpacing: '0.08em',
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
          }}
        >
          {ticker}
        </span>
      </div>
    </div>
  )
}

function ArrowLeft(): React.ReactElement {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M15 18L9 12l6-6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

const backBtnStyle: React.CSSProperties = {
  width: 30,
  height: 30,
  display: 'grid',
  placeItems: 'center',
  border: '1px solid var(--border-soft)',
  background: 'transparent',
  borderRadius: 6,
  cursor: 'pointer',
  color: 'var(--text-secondary)',
  transition: 'all 0.18s',
  flexShrink: 0,
}
