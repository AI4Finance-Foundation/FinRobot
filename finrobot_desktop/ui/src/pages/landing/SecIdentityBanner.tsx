// Landing-level nudge: when SEC EDGAR identity is unconfigured / left at
// the placeholder default, half of the report depth (10-K sections, XBRL
// financial facts, Form 4 / 13F / DEF 14A ownership data) is unavailable.
// We show a dismissible banner so the user can either fix it or
// acknowledge the limitation and keep working.

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../../api/client'
import { useI18n } from '../../i18n'
import { isValidSecIdentity } from '../../views/SettingsView'

const DISMISS_KEY = 'finrobot-sec-banner-dismissed-at'
/** Re-prompt after 30 days even if dismissed — long enough to be unannoying,
 * short enough that long-term users eventually configure it. */
const REPROMPT_AFTER_MS = 30 * 24 * 60 * 60 * 1000

export function SecIdentityBanner(): React.ReactElement | null {
  const { t } = useI18n()
  const [hidden, setHidden] = useState<boolean>(() => isDismissedRecently())

  // Re-check dismiss state on mount (defensive — page-internal nav doesn't
  // remount, but mounting the banner across sessions should pick up changes).
  useEffect(() => {
    setHidden(isDismissedRecently())
  }, [])

  const { data } = useQuery({
    queryKey: ['settings', 'sec_user_agent'],
    queryFn: async () => {
      const { data: resp, error } = await api.GET('/api/settings')
      if (error || !resp) return null
      return resp.sec_user_agent ?? null
    },
    staleTime: 5 * 60 * 1000,
  })

  if (hidden) return null
  // We can't tell yet whether identity is configured — wait for the query.
  if (data === undefined) return null
  if (isValidSecIdentity(data)) return null

  const handleDismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()))
    } catch {
      /* localStorage unavailable — accept the next-page re-show */
    }
    setHidden(true)
  }

  return (
    <div
      data-testid="sec-identity-banner"
      style={{
        position: 'relative',
        zIndex: 2,
        background:
          'linear-gradient(135deg, rgba(217, 119, 6, 0.10), rgba(217, 119, 6, 0.04))',
        border: '1px solid rgba(217, 119, 6, 0.32)',
        borderRadius: 'var(--radius-md)',
        padding: '14px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
      }}
    >
      <span
        aria-hidden
        style={{
          fontSize: 18,
          color: 'var(--warning)',
        }}
      >
        ⚠
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            letterSpacing: '1.5px',
            color: 'var(--warning)',
            marginBottom: 4,
          }}
        >
          {t('landing.secBanner.title')}
        </div>
        <p
          style={{
            fontSize: 12,
            color: 'var(--text-secondary)',
            lineHeight: 1.55,
            margin: 0,
          }}
        >
          {t('landing.secBanner.body')}
        </p>
      </div>
      <Link
        to="/settings"
        style={{
          padding: '8px 16px',
          background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
          color: 'var(--text-primary)',
          borderRadius: 'var(--radius-md)',
          fontFamily: 'var(--font-display)',
          fontSize: 11,
          letterSpacing: '1.5px',
          textDecoration: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        {t('landing.secBanner.cta')}
      </Link>
      <button
        onClick={handleDismiss}
        title={t('landing.secBanner.dismissTooltip')}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--text-muted)',
          fontSize: 18,
          cursor: 'pointer',
          padding: '4px 8px',
          lineHeight: 1,
        }}
        aria-label={t('landing.secBanner.dismissAria')}
      >
        ×
      </button>
    </div>
  )
}

function isDismissedRecently(): boolean {
  try {
    const v = localStorage.getItem(DISMISS_KEY)
    if (!v) return false
    const n = Number(v)
    if (!Number.isFinite(n)) return false
    return Date.now() - n < REPROMPT_AFTER_MS
  } catch {
    return false
  }
}
