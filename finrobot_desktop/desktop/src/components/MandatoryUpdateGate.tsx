// Mandatory-update gate — full-screen, non-dismissible block shown when the
// installed version is below the published min-version floor (updaterStore.
// mandatory). The user cannot use the app until they update: no close, no
// backdrop dismiss. macOS traffic lights still work (native, outside the
// webview), so quitting remains possible. Renders nothing when not mandatory.

import { useUpdaterStore } from '../stores/updaterStore'
import { useI18n } from '../i18n'

export function MandatoryUpdateGate(): React.ReactElement | null {
  const { t } = useI18n()
  const mandatory = useUpdaterStore((s) => s.mandatory)
  const phase = useUpdaterStore((s) => s.phase)
  const version = useUpdaterStore((s) => s.version)
  const progress = useUpdaterStore((s) => s.progress)
  const error = useUpdaterStore((s) => s.error)
  const install = useUpdaterStore((s) => s.installAndRelaunch)

  if (!mandatory) return null

  const busy = phase === 'downloading' || phase === 'installing' || phase === 'ready'
  const pct = Math.round(progress * 100)

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'var(--scrim)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        display: 'grid',
        placeItems: 'center',
        // Above everything: titlebar (80), toasts (~200), update pill.
        zIndex: 9999,
      }}
    >
      <div
        style={{
          width: 440,
          maxWidth: '90vw',
          padding: '28px 30px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden>
            <circle cx="12" cy="12" r="10" stroke="var(--primary)" strokeWidth="1.6" />
            <path
              d="M12 16V11M8 12l4-4 4 4"
              stroke="var(--primary)"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>
            {t('update.gate.title')}
          </div>
        </div>

        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.65 }}>
          {t('update.gate.body', { version: version ?? '' })}
        </div>

        {busy && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div
              style={{
                height: 6,
                borderRadius: 3,
                background: 'var(--bg-card)',
                border: '1px solid var(--border-soft)',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: phase === 'downloading' ? `${pct}%` : '100%',
                  background: 'var(--primary)',
                  boxShadow: 'var(--glow-blue)',
                  borderRadius: 3,
                  transition: 'width 0.2s ease',
                }}
              />
            </div>
            <div
              style={{
                fontSize: 11.5,
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
              }}
            >
              {phase === 'downloading'
                ? `${t('update.pill.downloading')} ${pct}%`
                : t('update.pill.installing')}
            </div>
          </div>
        )}

        {phase === 'error' && error && (
          <div
            style={{
              padding: '10px 12px',
              background: 'var(--negative-bg)',
              border: '1px solid var(--negative)',
              borderRadius: 'var(--r-md, 8px)',
              fontSize: 11.5,
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-primary)',
              wordBreak: 'break-word',
            }}
          >
            {error}
          </div>
        )}

        {!busy && (
          <button
            type="button"
            className="btn"
            onClick={() => void install()}
            style={{
              alignSelf: 'flex-end',
              background: 'var(--primary)',
              borderColor: 'var(--primary)',
              color: 'var(--text-on-primary)',
              fontWeight: 600,
            }}
          >
            {phase === 'error' ? t('update.pill.retry') : t('update.gate.button')}
          </button>
        )}
      </div>
    </div>
  )
}
