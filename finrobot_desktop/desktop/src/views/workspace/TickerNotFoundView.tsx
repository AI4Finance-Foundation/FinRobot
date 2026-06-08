// Full-page error view for 422 (ticker truly does not exist in yfinance).
// Strict: no escape hatch — escape hatch would just send the user to the
// blank-cards UI we're explicitly avoiding.

import React from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '../../i18n'
import { WorkspaceBackBar } from './WorkspaceBackBar'

interface Props {
  ticker: string
}

export function TickerNotFoundView({ ticker }: Props): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      data-testid="ticker-not-found"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <WorkspaceBackBar ticker={ticker} />

      <div
        style={{
          marginTop: 80,
          textAlign: 'center',
          maxWidth: 520,
          alignSelf: 'center',
          padding: '0 32px',
        }}
      >
        {/* Title — Audiowide 48px, letter-spacing 4px per §3 */}
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 48,
            letterSpacing: '4px',
            color: 'var(--text-primary)',
            marginBottom: 20,
            textShadow: '0 0 24px color-mix(in srgb, var(--danger) 25%, transparent)',
          }}
        >
          {t('ticker.notFound.title', { ticker })}
        </div>

        {/* Description — Inter 14px body copy per §3 */}
        <p
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 14,
            color: 'var(--text-secondary)',
            lineHeight: 1.7,
            marginBottom: 36,
          }}
        >
          {t('ticker.notFound.description')}
        </p>

        {/* CTA — .btn-shimmer (§6.3 shimmer button), Audiowide 13px + letter-spacing 2px */}
        <Link
          to="/research"
          className="btn-shimmer"
          style={{
            display: 'inline-block',
            padding: '10px 28px',
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            letterSpacing: '2px',
            textDecoration: 'none',
            marginBottom: 48,
            color: 'var(--text-primary)',
            borderRadius: 'var(--radius-md)',
          }}
        >
          {t('ticker.notFound.backButton')}
        </Link>

        {/* Troubleshooting hints — JetBrains Mono 11.5px, --bg-card card per §6.1 */}
        <div
          style={{
            textAlign: 'left',
            background: 'var(--bg-card)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-lg)',
            padding: '18px 22px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-muted)',
            lineHeight: 1.9,
          }}
        >
          <p style={{ margin: 0 }}>· {t('ticker.notFound.hint1')}</p>
          <p style={{ margin: 0 }}>· {t('ticker.notFound.hint2')}</p>
          <p style={{ margin: 0 }}>· {t('ticker.notFound.hint3')}</p>
          <p style={{ margin: 0 }}>· {t('ticker.notFound.hint4')}</p>
        </div>
      </div>
    </div>
  )
}
