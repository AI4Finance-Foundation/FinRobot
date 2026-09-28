// Global brand footer — a faint, borderless attribution strip pinned to the
// bottom of every route (AppShell renders it as the third flex row below
// .app-body, so .main-content scrolls above it and content is never occluded).
//
// Deliberately NOT the old terminal StatusBar that was retired in 2026-06: no
// top border, no status pills, transparent background so the cosmic shell glow
// shows through — just the foundation copyright + a clickable link to the site.
// Excluded from exported reports (those render ReportChapters only, not the
// AppShell); a shared report carries its own disclaimer-chapter attribution.

import { useI18n } from '../i18n'
import { openExternal } from '../lib/tauri'
import { EXTERNAL_LINKS, SITE_LABEL } from '../config/links'

export function AppFooter(): React.ReactElement {
  const { t } = useI18n()
  return (
    <footer className="app-footer" data-testid="app-footer">
      <span className="app-footer-copy">{t('shell.footer.copyright')}</span>
      <span className="app-footer-sep" aria-hidden>
        ·
      </span>
      <button
        type="button"
        className="app-footer-link"
        onClick={() => void openExternal(EXTERNAL_LINKS.site)}
      >
        {SITE_LABEL}
      </button>
    </footer>
  )
}
