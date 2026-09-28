// Shared primitive controls for the Settings panels: inline icon glyphs, the
// show/hide secret input, and the toggle-switch row.

import { useState } from 'react'
import { useI18n } from '../../i18n'

// ─── Small inline icons (cosmic spec: simple glyphs as inline SVG) ────────────

export function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d={d}
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
export const ICON_MODEL = 'M8 1.5 14 5v6l-6 3.5L2 11V5l6-3.5ZM8 8 14 5M8 8v6.5M8 8 2 5'
export const ICON_DATA =
  'M2.5 4c0-1.1 2.5-2 5.5-2s5.5.9 5.5 2-2.5 2-5.5 2-5.5-.9-5.5-2Zm0 0v8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2V4'
export const ICON_UPDATE = 'M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5V5H11'

// ─── Password input with show/hide toggle ────────────────────────────────────

export function SecretInput({
  value,
  onChange,
  placeholder,
  invalid,
  ariaLabel,
  disabled,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  invalid?: boolean
  ariaLabel?: string
  disabled?: boolean
}) {
  const { t } = useI18n()
  const [revealed, setRevealed] = useState(false)
  return (
    <div className="settings-input-wrap">
      <input
        className={`settings-input has-trailing${invalid ? ' is-invalid' : ''}`}
        type={revealed ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        aria-label={ariaLabel}
        disabled={disabled}
      />
      <button
        type="button"
        className="settings-eye"
        aria-label={revealed ? t('settings.key.hide') : t('settings.key.show')}
        title={revealed ? t('settings.key.hide') : t('settings.key.show')}
        onClick={() => setRevealed((r) => !r)}
        disabled={disabled}
      >
        {revealed ? (
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path
              d="M2 8s2.4-4 6-4 6 4 6 4-2.4 4-6 4-6-4-6-4Z"
              stroke="currentColor"
              strokeWidth="1.3"
            />
            <circle cx="8" cy="8" r="1.8" stroke="currentColor" strokeWidth="1.3" />
          </svg>
        ) : (
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path
              d="M2 8s2.4-4 6-4 6 4 6 4-2.4 4-6 4-6-4-6-4Z"
              stroke="currentColor"
              strokeWidth="1.3"
            />
            <path d="m3 3 10 10" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
        )}
      </button>
    </div>
  )
}

// ─── Toggle-switch row ────────────────────────────────────────────────────────

export function ToggleRow({
  label,
  desc,
  enabled,
  onToggle,
}: {
  label: string
  desc: string
  enabled: boolean
  onToggle: () => void
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '14px 0',
        borderTop: '1px solid var(--border-soft)',
      }}
    >
      <div style={{ paddingRight: 24 }}>
        <div style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.5 }}>
          {desc}
        </div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={label}
        onClick={onToggle}
        style={{
          position: 'relative',
          width: 44,
          height: 24,
          flexShrink: 0,
          borderRadius: 12,
          border: '1px solid var(--border-soft)',
          background: enabled ? 'var(--primary-soft)' : 'var(--bg-card)',
          cursor: 'pointer',
          transition: 'all 0.2s',
          padding: 0,
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 2,
            left: enabled ? 22 : 2,
            width: 18,
            height: 18,
            borderRadius: '50%',
            background: enabled ? 'var(--primary)' : 'var(--text-muted)',
            boxShadow: enabled ? 'var(--glow-blue)' : 'none',
            transition: 'all 0.2s',
          }}
        />
      </button>
    </div>
  )
}
