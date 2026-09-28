// ─── SEC 13F institutional-holdings section ─────────────────────────────────
// The 13F reverse index is OFF by default (building it downloads a whole
// quarter of market-wide filings — ~1-2h). This section shows cache state,
// flips auto-sync, and triggers a manual build behind a confirm (BUG-009).

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, BASE_URL } from '../../api/client'
import { fetchWithTimeout } from '../../api/fetch'
import { useToastStore } from '../../stores/toastStore'
import { mapErrorToUserMessage, FetchHttpError } from '../../utils/errorMessage'
import { useI18n } from '../../i18n'
import { ToggleRow } from './controls'

interface RefreshRuntime {
  status: 'idle' | 'running' | 'done' | 'error'
  period_end: string | null
  started_at: string | null
  finished_at: string | null
  error: string | null
}

interface SecHoldingsStatusShape {
  populated: boolean
  row_count: number
  latest_period_end: string | null
  distinct_tickers: number
  // Most recent quarter whose 13F filing deadline has passed; `stale` means
  // the cache lags it and a re-sync is overdue (backend SecHoldingsStatus).
  expected_period_end: string | null
  stale: boolean
  identity_configured: boolean
  auto_refresh: boolean
  refresh: RefreshRuntime
}

export function SecHoldingsSection(): React.ReactElement {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)

  const { data: status } = useQuery<SecHoldingsStatusShape>({
    queryKey: ['sec-holdings-status'],
    queryFn: async () => {
      const resp = await fetchWithTimeout(`${BASE_URL}/api/sec-holdings/status`)
      if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
      return (await resp.json()) as SecHoldingsStatusShape
    },
    refetchInterval: (query) => (query.state.data?.refresh.status === 'running' ? 2000 : false),
  })

  const refreshMutation = useMutation({
    mutationFn: async () => {
      const resp = await fetchWithTimeout(`${BASE_URL}/api/sec-holdings/refresh`, {
        method: 'POST',
      })
      if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
      return (await resp.json()) as SecHoldingsStatusShape
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['sec-holdings-status'], data)
      if (data.refresh.status === 'error') {
        addToast({
          type: 'error',
          title: t('settings.secHoldings.syncFailed'),
          description:
            data.refresh.error === 'identity_missing'
              ? t('settings.secHoldings.identityRequired')
              : (data.refresh.error ?? t('settings.secHoldings.syncFailed')),
        })
      }
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('settings.secHoldings.syncFailed'),
        description: mapErrorToUserMessage(err),
      })
    },
  })

  const autoRefreshMutation = useMutation({
    mutationFn: async (v: boolean) => {
      const { data, error } = await api.PUT('/api/settings', {
        body: { sec_holdings_auto_refresh: v } as never,
      })
      if (error) throw new Error('settings update failed')
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sec-holdings-status'] })
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  const [confirmOpen, setConfirmOpen] = useState(false)

  const running = status?.refresh.status === 'running' || refreshMutation.isPending
  const identityOk = status?.identity_configured ?? false
  const startedAt = status?.refresh.started_at ?? null
  const startedAtLabel = (() => {
    if (!running || !startedAt) return null
    const d = new Date(startedAt)
    if (Number.isNaN(d.getTime())) return null
    return t('settings.secHoldings.startedAt', { time: d.toLocaleString() })
  })()

  const statusLine = (() => {
    if (!status) return ''
    if (status.populated && status.latest_period_end) {
      return t('settings.secHoldings.statusPopulated', {
        rows: status.row_count.toLocaleString(),
        tickers: status.distinct_tickers.toLocaleString(),
        period: status.latest_period_end,
      })
    }
    return t('settings.secHoldings.statusEmpty')
  })()

  return (
    <section className="settings-section" data-section="secHoldings">
      <h2 className="settings-section-title">{t('settings.section.secHoldings')}</h2>
      <p className="settings-section-desc">{t('settings.secHoldings.intro')}</p>

      <div className="settings-field">
        <p className="settings-hint" style={{ fontFamily: 'var(--font-mono)' }}>
          {statusLine}
        </p>
        {status?.stale && status.expected_period_end && (
          <p className="settings-hint is-warn" style={{ marginTop: 4 }}>
            {t('settings.secHoldings.stale', { expected: status.expected_period_end })}
          </p>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn"
            disabled={!identityOk || running}
            onClick={() => setConfirmOpen(true)}
          >
            <svg width="13" height="13" viewBox="0 0 12 12" fill="none" aria-hidden>
              <path
                d="M10.5 6a4.5 4.5 0 1 1-1.32-3.18M10.5 1.5V4H8"
                stroke="currentColor"
                strokeWidth="1.3"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {running ? t('settings.secHoldings.syncing') : t('settings.secHoldings.syncNow')}
          </button>
          {!identityOk && (
            <span className="settings-hint is-warn">
              {t('settings.secHoldings.identityRequired')}
            </span>
          )}
        </div>
        {running && (
          <>
            {startedAtLabel && (
              <p className="settings-hint" style={{ marginTop: 6 }}>
                {startedAtLabel}
              </p>
            )}
            <p className="settings-hint" style={{ marginTop: 6 }}>
              {t('settings.secHoldings.runningHint')}
            </p>
          </>
        )}
        {refreshMutation.isError && !running && (
          <p className="settings-hint is-bad" style={{ marginTop: 6 }}>
            {t('settings.secHoldings.syncError')}{' '}
            <button
              type="button"
              onClick={() => refreshMutation.mutate()}
              style={{
                background: 'transparent',
                border: 'none',
                padding: 0,
                color: 'var(--danger)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.75rem',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              {t('common.retry')}
            </button>
          </p>
        )}
      </div>

      <ToggleRow
        label={t('settings.secHoldings.autoRefresh')}
        desc={t('settings.secHoldings.autoRefreshDesc')}
        enabled={status?.auto_refresh ?? false}
        onToggle={() => autoRefreshMutation.mutate(!(status?.auto_refresh ?? false))}
      />

      {confirmOpen && (
        <SecHoldingsConfirmModal
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => {
            setConfirmOpen(false)
            refreshMutation.mutate()
          }}
        />
      )}
    </section>
  )
}

function SecHoldingsConfirmModal({
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
          maxWidth: 460,
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
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--warning)' }}>
          {t('settings.secHoldings.confirmTitle')}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-primary)', lineHeight: 1.6 }}>
          {t('settings.secHoldings.confirmBody')}
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
              background: 'var(--warning)',
              borderColor: 'var(--warning)',
              color: 'var(--text-on-warning)',
              fontWeight: 600,
            }}
          >
            {t('settings.secHoldings.confirmProceed')}
          </button>
        </div>
      </div>
    </div>
  )
}
