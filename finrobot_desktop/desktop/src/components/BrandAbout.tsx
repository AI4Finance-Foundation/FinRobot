// Brand wordmark + About popover. The FinRobot wordmark in the TitleBar is the
// affordance (the macOS / desktop "About" convention): clicking it opens a
// cosmic popover with version · license, the foundation site, a GitHub star
// link, and the copyright / 501(c)(3) attribution. Costs zero layout space and
// is one click away on every screen — so the wordmark is no longer purely
// decorative (it carries a chevron + hover state to signal it's interactive).

import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n'
import { openExternal } from '../lib/tauri'
import { currentAppVersion } from '../lib/updater'
import { EXTERNAL_LINKS, SITE_LABEL } from '../config/links'
import appIcon from '../assets/app-icon.png'

/** ↗ external-link glyph (inline SVG per the cosmic spec). */
const ArrowUpRight = (): React.ReactElement => (
  <svg
    className="brand-about-arrow"
    viewBox="0 0 24 24"
    width="12"
    height="12"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.8}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden
  >
    <line x1="7" y1="17" x2="17" y2="7" />
    <polyline points="8 7 17 7 17 16" />
  </svg>
)

export function BrandAbout(): React.ReactElement {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [version, setVersion] = useState<string | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  // App version is async + Tauri-only (null in the dev browser); load once.
  useEffect(() => {
    void currentAppVersion().then(setVersion)
  }, [])

  // Dismiss on outside click / Escape while the popover is open.
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent): void {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="tb-brand-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`tb-brand${open ? ' open' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t('shell.about.aria')}
        onClick={() => setOpen((v) => !v)}
      >
        <img className="tb-brand-mark" src={appIcon} alt="" aria-hidden />
        <span className="tb-wordmark">
          Fin<b>Robot</b>
        </span>
        <svg
          className="tb-brand-chevron"
          viewBox="0 0 24 24"
          width="11"
          height="11"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open ? (
        <div
          className="brand-about"
          role="dialog"
          aria-label={t('shell.about.aria')}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="brand-about-head">
            <span className="brand-about-name">
              Fin<b>Robot</b>
            </span>
            <span className="brand-about-meta">{version ? `v${version} · ` : ''}Apache-2.0</span>
          </div>

          <div className="brand-about-links">
            <button
              type="button"
              className="brand-about-link"
              onClick={() => void openExternal(EXTERNAL_LINKS.site)}
            >
              <span>{SITE_LABEL}</span>
              <ArrowUpRight />
            </button>
            <button
              type="button"
              className="brand-about-link"
              onClick={() => void openExternal(EXTERNAL_LINKS.github)}
            >
              <span className="brand-about-star">★ {t('shell.about.starGithub')}</span>
              <ArrowUpRight />
            </button>
          </div>

          <div className="brand-about-foot">
            <span>{t('shell.footer.copyright')}</span>
            <span className="brand-about-charity">{t('shell.about.charity')}</span>
          </div>
        </div>
      ) : null}
    </div>
  )
}
