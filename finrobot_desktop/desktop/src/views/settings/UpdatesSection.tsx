// ─── Updates section ─────────────────────────────────────────────────────────
// Current version + a manual "check for updates" button. The button drives the
// same updaterStore as the silent startup check; a found update surfaces as the
// TitleBar pill (UpdatePill), and this section toasts the outcome.

import { useState, useEffect } from 'react'
import { useToastStore } from '../../stores/toastStore'
import { useI18n } from '../../i18n'
import { useUpdaterStore } from '../../stores/updaterStore'
import { currentAppVersion } from '../../lib/updater'
import { isTauri } from '../../lib/tauri'

export function UpdatesSection(): React.ReactElement {
  const { t } = useI18n()
  const phase = useUpdaterStore((s) => s.phase)
  const check = useUpdaterStore((s) => s.check)
  const addToast = useToastStore((s) => s.addToast)
  const [version, setVersion] = useState<string | null>(null)
  const inApp = isTauri()

  useEffect(() => {
    let alive = true
    void currentAppVersion().then((v) => {
      if (alive) setVersion(v)
    })
    return () => {
      alive = false
    }
  }, [])

  const checking = phase === 'checking'

  // Manual check: the title-bar pill handles the "available" case (and the
  // install), so here we only toast the outcomes the pill can't show on its
  // own — found / already-latest / check failed.
  const runCheck = async () => {
    const result = await check()
    if (result === 'available') {
      addToast({ type: 'info', title: t('update.toast.available') })
    } else if (result === 'uptodate') {
      addToast({ type: 'success', title: t('update.toast.upToDate') })
    } else if (result === 'error') {
      addToast({ type: 'error', title: t('update.toast.checkFailed') })
    }
  }

  return (
    <section className="settings-section" data-section="updates">
      <h2 className="settings-section-title">{t('settings.section.updates')}</h2>
      <p className="settings-section-desc">{t('settings.updates.intro')}</p>

      <div className="settings-field">
        <p className="settings-hint" style={{ fontFamily: 'var(--font-mono)' }}>
          {t('settings.updates.currentVersion', { version: version ?? '—' })}
        </p>
        {inApp ? (
          <div style={{ marginTop: 8 }}>
            <button
              type="button"
              className="btn"
              disabled={checking}
              onClick={() => void runCheck()}
            >
              {checking ? t('settings.updates.checking') : t('settings.updates.checkButton')}
            </button>
          </div>
        ) : (
          <p className="settings-hint is-warn" style={{ marginTop: 8 }}>
            {t('settings.updates.browserOnly')}
          </p>
        )}
      </div>
    </section>
  )
}
