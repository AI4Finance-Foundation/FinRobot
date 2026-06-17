// ─── Provider dropdown (cosmic-styled, not a native <select>) ────────────────

import { useState, useEffect, useRef } from 'react'
import { useI18n } from '../../i18n'

export interface ProviderOption {
  id: string
  label: string
  is_builtin: boolean
}

export function ProviderDropdown({
  options,
  value,
  onSelect,
  onAddCustom,
  placeholder,
}: {
  options: ProviderOption[]
  value: string
  onSelect: (id: string) => void
  onAddCustom: () => void
  /** Shown (muted) in the trigger when nothing is selected yet — a fresh install
   * has no provider chosen, so the bare trigger would otherwise read as blank. */
  placeholder?: string
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  const selected = options.find((o) => o.id === value)
  return (
    <div className="settings-dd" ref={ref}>
      <button
        type="button"
        className="settings-dd-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span style={selected ? undefined : { color: 'var(--text-muted)' }}>
          {selected?.label ?? (value || placeholder)}
        </span>
        <svg
          className={`settings-dd-caret${open ? ' is-open' : ''}`}
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden
        >
          <path
            d="M3 4.5 6 7.5 9 4.5"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open && (
        <ul className="settings-dd-menu" role="listbox">
          {options.map((o) => (
            <li
              key={o.id}
              role="option"
              aria-selected={o.id === value}
              className={`settings-dd-item${o.id === value ? ' is-selected' : ''}`}
              onClick={() => {
                onSelect(o.id)
                setOpen(false)
              }}
            >
              <span className="settings-dd-item-label">{o.label}</span>
              {!o.is_builtin && (
                <span className="settings-dd-tag">{t('settings.provider.customTag')}</span>
              )}
              {o.id === value && (
                <svg
                  className="settings-dd-check"
                  width="13"
                  height="13"
                  viewBox="0 0 16 16"
                  fill="none"
                  aria-hidden
                >
                  <path
                    d="M3 8.5 6.5 12 13 4"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </li>
          ))}
          <li
            className="settings-dd-add"
            onClick={() => {
              onAddCustom()
              setOpen(false)
            }}
          >
            <span>＋</span>
            <span>{t('settings.customProvider.addEntry')}</span>
          </li>
        </ul>
      )}
    </div>
  )
}
