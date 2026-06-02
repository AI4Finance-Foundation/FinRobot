// CoverageGroupMenu — group-management affordance next to the group <select>.
// Renaming the active group only grows/relabels; deleting it removes the whole
// coverage group. Both are destructive enough to live behind an explicit menu
// (not bare buttons in the command bar). Rename uses an inline modal field;
// delete asks for confirmation since it drops every member at once.

import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'

interface Props {
  groupName: string
  busy?: boolean
  onRename: (name: string) => void
  onDelete: () => void
}

export function CoverageGroupMenu({
  groupName,
  busy = false,
  onRename,
  onDelete,
}: Props): React.ReactElement {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<null | 'rename' | 'delete'>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  // Close the popover on outside-click / Escape (the modals handle their own).
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent): void {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
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
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        aria-label={t('coverage.menu.manage')}
        aria-haspopup="menu"
        aria-expanded={open}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 34,
          height: 34,
          background: 'var(--bg-card)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--text-secondary)',
          cursor: busy ? 'not-allowed' : 'pointer',
          opacity: busy ? 0.5 : 1,
        }}
      >
        <DotsIcon />
      </button>

      {open && (
        <div
          role="menu"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: 0,
            minWidth: 160,
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            boxShadow: '0 12px 32px rgba(0,0,0,0.4)',
            padding: 4,
            zIndex: 50,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <MenuItem
            label={t('coverage.menu.rename')}
            onClick={() => {
              setOpen(false)
              setMode('rename')
            }}
          />
          <MenuItem
            label={t('coverage.menu.delete')}
            danger
            onClick={() => {
              setOpen(false)
              setMode('delete')
            }}
          />
        </div>
      )}

      {mode === 'rename' && (
        <RenameModal
          initial={groupName}
          onCancel={() => setMode(null)}
          onConfirm={(name) => {
            setMode(null)
            onRename(name)
          }}
        />
      )}
      {mode === 'delete' && (
        <ConfirmModal
          tone="danger"
          title={t('coverage.confirm.deleteGroupTitle')}
          body={t('coverage.confirm.deleteGroup', { name: groupName })}
          confirmLabel={t('coverage.menu.delete')}
          onCancel={() => setMode(null)}
          onConfirm={() => {
            setMode(null)
            onDelete()
          }}
        />
      )}
    </div>
  )
}

function MenuItem({
  label,
  onClick,
  danger,
}: {
  label: string
  onClick: () => void
  danger?: boolean
}): React.ReactElement {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      style={{
        textAlign: 'left',
        padding: '8px 10px',
        background: 'transparent',
        border: 'none',
        borderRadius: 'var(--radius-sm)',
        color: danger ? 'var(--danger)' : 'var(--text-primary)',
        cursor: 'pointer',
        fontSize: 13,
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-card)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      {label}
    </button>
  )
}

function RenameModal({
  initial,
  onCancel,
  onConfirm,
}: {
  initial: string
  onCancel: () => void
  onConfirm: (name: string) => void
}): React.ReactElement {
  const { t } = useI18n()
  const [value, setValue] = useState(initial)
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])
  const trimmed = value.trim()
  const valid = trimmed.length > 0 && trimmed !== initial
  function submit(): void {
    if (valid) onConfirm(trimmed)
  }
  return (
    <ModalShell onCancel={onCancel}>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          letterSpacing: '0.06em',
          color: 'var(--text-secondary)',
        }}
      >
        {t('coverage.menu.rename')}
      </div>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
          if (e.key === 'Escape') onCancel()
        }}
        aria-label={t('coverage.menu.rename')}
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--text-primary)',
          fontSize: 14,
          padding: '8px 12px',
          outline: 'none',
        }}
      />
      <ModalActions
        onCancel={onCancel}
        cancelLabel={t('coverage.confirm.cancel')}
        confirmLabel={t('coverage.menu.rename')}
        confirmDisabled={!valid}
        onConfirm={submit}
      />
    </ModalShell>
  )
}

function ConfirmModal({
  title,
  body,
  confirmLabel,
  tone = 'danger',
  onCancel,
  onConfirm,
}: {
  title: string
  body: string
  confirmLabel: string
  tone?: 'danger' | 'warning'
  onCancel: () => void
  onConfirm: () => void
}): React.ReactElement {
  const { t } = useI18n()
  const accent = tone === 'danger' ? 'var(--danger)' : 'var(--warning)'
  return (
    <ModalShell onCancel={onCancel}>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          letterSpacing: '0.06em',
          color: accent,
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.55 }}>{body}</div>
      <ModalActions
        onCancel={onCancel}
        cancelLabel={t('coverage.confirm.cancel')}
        confirmLabel={confirmLabel}
        confirmTone={tone}
        onConfirm={onConfirm}
      />
    </ModalShell>
  )
}

function ModalShell({
  children,
  onCancel,
}: {
  children: React.ReactNode
  onCancel: () => void
}): React.ReactElement {
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onCancel}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(5,5,13,0.72)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        display: 'grid',
        placeItems: 'center',
        zIndex: 200,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          minWidth: 340,
          maxWidth: 440,
          padding: '20px 22px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 16px 40px rgba(0,0,0,0.4)',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        {children}
      </div>
    </div>
  )
}

function ModalActions({
  onCancel,
  onConfirm,
  cancelLabel,
  confirmLabel,
  confirmDisabled = false,
  confirmTone = 'danger',
}: {
  onCancel: () => void
  onConfirm: () => void
  cancelLabel: string
  confirmLabel: string
  confirmDisabled?: boolean
  confirmTone?: 'danger' | 'warning' | 'primary'
}): React.ReactElement {
  const bg =
    confirmTone === 'danger'
      ? 'var(--danger)'
      : confirmTone === 'warning'
        ? 'var(--warning)'
        : 'var(--primary)'
  return (
    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
      <button
        type="button"
        onClick={onCancel}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          padding: '7px 14px',
          borderRadius: 6,
          border: '1px solid var(--border-soft)',
          background: 'transparent',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
        }}
      >
        {cancelLabel}
      </button>
      <button
        type="button"
        onClick={onConfirm}
        disabled={confirmDisabled}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          padding: '7px 14px',
          borderRadius: 6,
          border: 'none',
          background: bg,
          color: confirmTone === 'warning' ? '#1a1207' : '#fff',
          cursor: confirmDisabled ? 'not-allowed' : 'pointer',
          opacity: confirmDisabled ? 0.45 : 1,
          fontWeight: 600,
        }}
      >
        {confirmLabel}
      </button>
    </div>
  )
}

function DotsIcon(): React.ReactElement {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" role="img" aria-hidden>
      <circle cx="8" cy="3" r="1.4" fill="currentColor" />
      <circle cx="8" cy="8" r="1.4" fill="currentColor" />
      <circle cx="8" cy="13" r="1.4" fill="currentColor" />
    </svg>
  )
}
