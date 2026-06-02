// Column show/hide menu for the Coverage Table — a dropdown of checkboxes over
// COVERAGE_COLUMNS. Hidden columns persist in coverageStore (global view pref),
// so the analyst's chosen layout survives reloads and group switches.

import { useState, useRef, useEffect } from 'react'
import { useI18n } from '../../i18n'
import { COVERAGE_COLUMNS, columnLabel } from './columns'

interface Props {
  hiddenColumns: string[]
  onToggle: (key: string) => void
}

export function ColumnMenu({ hiddenColumns, onToggle }: Props): React.ReactElement {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const shown = COVERAGE_COLUMNS.length - hiddenColumns.length

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-sm)',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          fontSize: 12,
          padding: '6px 10px',
          whiteSpace: 'nowrap',
        }}
      >
        <ColumnsIcon />
        {t('coverage.columns')}
        {hiddenColumns.length > 0 && (
          <span style={{ color: 'var(--text-muted)' }}>
            {shown}/{COVERAGE_COLUMNS.length}
          </span>
        )}
      </button>
      {open && (
        <div
          role="menu"
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            marginTop: 4,
            zIndex: 50,
            minWidth: 160,
            padding: 6,
            background: 'var(--elevated, var(--bg-elevated))',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            boxShadow: '0 6px 20px rgba(0,0,0,0.4)',
          }}
        >
          {COVERAGE_COLUMNS.map((col) => (
            <label
              key={col.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '5px 8px',
                fontSize: 12,
                color: 'var(--text-primary)',
                cursor: 'pointer',
                borderRadius: 'var(--radius-sm)',
              }}
            >
              <input
                type="checkbox"
                checked={!hiddenColumns.includes(col.key)}
                onChange={() => onToggle(col.key)}
              />
              {columnLabel(col, t)}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

function ColumnsIcon(): React.ReactElement {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 16 16"
      role="img"
      aria-hidden
      style={{ flexShrink: 0 }}
    >
      <rect
        x="1.5"
        y="2.5"
        width="3.5"
        height="11"
        rx="0.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
      />
      <rect
        x="6.25"
        y="2.5"
        width="3.5"
        height="11"
        rx="0.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
      />
      <rect
        x="11"
        y="2.5"
        width="3.5"
        height="11"
        rx="0.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
      />
    </svg>
  )
}
