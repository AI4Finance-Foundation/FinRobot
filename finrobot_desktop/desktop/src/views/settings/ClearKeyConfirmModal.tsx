// ─── Clear-key confirm modal ─────────────────────────────────────────────────
// Deliberate confirmation before POST /api/settings/clear-secret wipes a stored
// keychain key (BUG-005: the backend PUT never deletes a secret on empty value).

import { useI18n } from '../../i18n'

export function ClearKeyConfirmModal({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void
  onConfirm: () => void
}): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onCancel}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'var(--scrim)',
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
          minWidth: 360,
          maxWidth: 440,
          padding: '22px 24px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
          {t('settings.clearKey.confirmTitle')}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {t('settings.clearKey.confirmBody')}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button type="button" className="btn" onClick={onCancel}>
            {t('settings.clearKey.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="btn"
            style={{
              background: 'var(--danger)',
              borderColor: 'var(--danger)',
              color: 'var(--text-on-primary)',
              fontWeight: 600,
            }}
          >
            {t('settings.clearKey.confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}
