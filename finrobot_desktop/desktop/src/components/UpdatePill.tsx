// Title-bar update pill. Sits in the TitleBar right cluster and only renders
// when there is something to show:
//   • available  → "UPDATE READY"     — click downloads + installs + relaunches
//                  (version + notes live in the hover tooltip, so the pill stays crisp)
//   • downloading → "Updating NN%"    — live progress, non-interactive
//   • installing/ready → "Installing…"
//   • error (failed install) → "Update failed — retry" — click retries
// Idle / silent-checking render nothing, so the bar stays clean.

import { useUpdaterStore } from '../stores/updaterStore'
import { useI18n } from '../i18n'

export function UpdatePill(): React.ReactElement | null {
  const { t } = useI18n()
  const phase = useUpdaterStore((s) => s.phase)
  const version = useUpdaterStore((s) => s.version)
  const notes = useUpdaterStore((s) => s.notes)
  const progress = useUpdaterStore((s) => s.progress)
  const install = useUpdaterStore((s) => s.installAndRelaunch)

  if (phase === 'idle' || phase === 'checking') return null

  const pct = Math.round(progress * 100)

  if (phase === 'available') {
    // Crisp text-only label; the exact version + release notes stay reachable in
    // the hover tooltip, so analysts can still trace which build without clutter.
    return (
      <button
        type="button"
        className="tb-update-pill is-available"
        title={notes ?? t('update.pill.available', { version: version ?? '' })}
        onClick={() => void install()}
      >
        {t('update.pill.ready')}
      </button>
    )
  }

  if (phase === 'downloading') {
    return (
      <span className="tb-update-pill is-busy" aria-live="polite">
        <Spinner />
        {t('update.pill.downloading')} {pct}%
      </span>
    )
  }

  if (phase === 'installing' || phase === 'ready') {
    return (
      <span className="tb-update-pill is-busy" aria-live="polite">
        <Spinner />
        {t('update.pill.installing')}
      </span>
    )
  }

  // phase === 'error' (a failed install — user-initiated, so make retry visible)
  return (
    <button type="button" className="tb-update-pill is-error" onClick={() => void install()}>
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
        <path
          d="M10 6a4 4 0 1 1-1.2-2.85M10 1.8v2.2H7.8"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {t('update.pill.retry')}
    </button>
  )
}

function Spinner(): React.ReactElement {
  return (
    <svg className="tb-update-spinner" width="12" height="12" viewBox="0 0 12 12" aria-hidden>
      <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.4" opacity="0.25" />
      <path d="M6 1.5A4.5 4.5 0 0 1 10.5 6" stroke="currentColor" strokeWidth="1.4" fill="none" />
    </svg>
  )
}
