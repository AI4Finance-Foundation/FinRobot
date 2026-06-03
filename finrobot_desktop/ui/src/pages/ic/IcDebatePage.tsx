// IcDebatePage — /ic/:ticker route.
//
// Explicit trigger: never auto-starts debate on mount to avoid inadvertent
// LLM API calls. Shows a start button until the analyst clicks it.
//
// After startDebate():
//   - VerdictCard renders sticky at top (streaming skeleton until verdict arrives)
//   - Two-column DebateColumn layout for bull / bear points
//
// v1 scope: no divergence panel (backend doesn't produce divergence values).
//
// Ephemeral by design (BUG-20260602-015): a debate is NOT persisted as an
// artifact — state lives only in the in-memory debateStore, and the backend
// /api/debate route streams SSE without writing a record. It will not appear in
// history/timeline and is lost on refresh/close. Until artifact persistence
// ships, the page must say so out loud (EphemeralNotice below) rather than
// silently dropping the analyst's debate. Do NOT add a save/export button here
// that implies persistence — there is none yet.

import { useCallback } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router-dom'
import { useDebateStore, selectDebate } from '../../stores/debateStore'
import { VerdictCard } from '../../components/debate/VerdictCard'
import { DebateColumn } from '../../components/debate/DebateColumn'
import { MarketImpliedPanel } from '../../components/debate/MarketImpliedPanel'
import { useToastStore } from '../../stores/toastStore'
import { useI18n } from '../../i18n'

export function IcDebatePage() {
  const { ticker } = useParams<{ ticker: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const addToast = useToastStore((s) => s.addToast)
  const { t, locale } = useI18n()

  const symbol = (ticker ?? '').toUpperCase()
  const artifactId = searchParams.get('artifact_id')
  // The debate is entered from a report, so "back" returns to that report
  // (there is no IC landing page anymore).
  const reportPath = artifactId ? `/stocks/${symbol}/runs/${artifactId}` : `/stocks/${symbol}`

  const debate = useDebateStore(selectDebate(symbol, artifactId))
  const startDebate = useDebateStore((s) => s.startDebate)
  const reset = useDebateStore((s) => s.reset)

  const isIdle = !debate || debate.status === 'idle'
  const isRunning = debate?.status === 'running'
  const isFailed = debate?.status === 'failed'
  const isCompleted = debate?.status === 'completed'

  const handleStart = useCallback(async () => {
    if (!symbol || !artifactId) {
      addToast({
        type: 'error',
        title: t('ic.toast.missingParams.title'),
        description: t('ic.toast.missingParams.desc'),
      })
      return
    }
    try {
      await startDebate(symbol, artifactId)
    } catch (err) {
      addToast({
        type: 'error',
        title: t('ic.toast.startFailed.title'),
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }, [symbol, artifactId, startDebate, addToast, t])

  // Re-run a debate for the SAME (ticker, artifact): clear the prior state then
  // kick off a fresh run. Used by both the failed-state retry and the
  // completed-state re-debate buttons. Backend has no dedup — each run is new.
  const handleRedebate = useCallback(() => {
    if (!artifactId) return
    reset(symbol, artifactId)
    // Re-trigger start after reset; need a tick for the store to clear.
    setTimeout(() => handleStart(), 0)
  }, [symbol, artifactId, reset, handleStart])

  if (!symbol) {
    return (
      <PageFrame>
        <ErrorBanner message={t('ic.error.missingTicker')} />
      </PageFrame>
    )
  }

  return (
    <div
      data-testid="ic-debate-page"
      style={{
        maxWidth: 1200,
        margin: '0 auto',
        padding: '0 32px 80px',
      }}
    >
      {/* Top chrome: breadcrumb + back */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '16px 0 24px',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          letterSpacing: '0.08em',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
        }}
      >
        <button
          type="button"
          onClick={() => navigate(reportPath)}
          style={backBtnStyle}
          title={t('ic.breadcrumb.back')}
          aria-label={t('ic.breadcrumb.back')}
        >
          ‹
        </button>
        <button type="button" onClick={() => navigate(reportPath)} style={crumbBtnStyle}>
          {t('ic.breadcrumb.committee')}
        </button>
        <span style={{ color: 'var(--text-dim)' }}>›</span>
        <span style={{ color: 'var(--accent-cyan)' }}>{symbol}</span>
        {artifactId && (
          <>
            <span style={{ color: 'var(--text-dim)' }}>›</span>
            <span style={{ color: 'var(--text-muted)' }}>{artifactId.slice(0, 12)}…</span>
          </>
        )}
      </div>

      {/* Start state — shown when no debate has started for this ticker */}
      {isIdle && (
        <StartPanel
          ticker={symbol}
          artifactId={artifactId}
          onStart={handleStart}
          onViewReport={() => artifactId && navigate(`/stocks/${symbol}/runs/${artifactId}`)}
        />
      )}

      {/* Active / completed debate */}
      {!isIdle && debate && (
        <>
          {/* Sticky verdict card */}
          <VerdictCard
            verdict={debate.verdict}
            status={debate.status}
            reliable={debate.reliable}
            current_price={debate.current_price}
          />

          {/* Ephemeral notice (BUG-20260602-015): this debate is not saved — be
              honest about it instead of letting the analyst assume it persists. */}
          <EphemeralNotice locale={locale} />

          {/* Re-debate: a completed verdict reflects one moment's data/assumptions.
              Let the analyst re-run against the same report to compare. */}
          {isCompleted && (
            <div style={{ margin: '4px 0 24px', display: 'flex', justifyContent: 'flex-end' }}>
              <button type="button" onClick={handleRedebate} style={secondaryBtnStyle}>
                ⚖ {t('ic.action.retry')}
              </button>
            </div>
          )}

          {/* Error state */}
          {isFailed && debate.error && (
            <div style={{ marginBottom: 24 }}>
              <ErrorBanner message={debate.error} />
              <div style={{ marginTop: 10, display: 'flex', gap: 10 }}>
                <button
                  type="button"
                  onClick={() => artifactId && reset(symbol, artifactId)}
                  style={secondaryBtnStyle}
                >
                  {t('ic.action.reset')}
                </button>
                <button type="button" onClick={handleRedebate} style={primaryBtnStyle}>
                  {t('ic.action.retry')}
                </button>
              </div>
            </div>
          )}

          {/* Reliability caveat over the argument columns. The VerdictCard banner
              downgrades the call to REVIEW when data is unreliable; the precise
              estimates cited in the bull/bear chips below must carry the same
              caveat instead of reading as firm conclusions (the downgrade signal
              has to reach this node, not just the verdict). */}
          {isCompleted && debate.reliable === false && (
            <div
              role="note"
              style={{
                margin: '0 0 16px',
                padding: '10px 14px',
                background: 'color-mix(in srgb, var(--warning) 8%, transparent)',
                border: '1px solid color-mix(in srgb, var(--warning) 28%, transparent)',
                borderRadius: 'var(--radius-sm)',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                lineHeight: 1.6,
                color: 'var(--warning)',
                letterSpacing: '0.02em',
              }}
            >
              ⚠ {t('ic.column.provisional')}
            </div>
          )}

          {/* Market-implied expectations — reverse-DCF expert probe. The
              confirmable evidence base for the judge's one-line SWING_FACTOR:
              shown below the verdict, default-collapsed, never feeding the
              verdict itself. */}
          {isCompleted && <MarketImpliedPanel ticker={symbol} />}

          {/* Two-column bull / bear layout */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 20,
              alignItems: 'start',
            }}
          >
            <DebateColumn
              side="bull"
              points={debate.bull}
              evidence={debate.evidence}
              artifactId={debate.artifactId}
              isRunning={isRunning}
            />
            <DebateColumn
              side="bear"
              points={debate.bear}
              evidence={debate.evidence}
              artifactId={debate.artifactId}
              isRunning={isRunning}
            />
          </div>
        </>
      )}
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

interface StartPanelProps {
  ticker: string
  artifactId: string | null
  onStart: () => void
  onViewReport: () => void
}

function StartPanel({ ticker, artifactId, onStart, onViewReport }: StartPanelProps) {
  const { t } = useI18n()
  return (
    <div
      style={{
        background: 'rgba(15,15,34,0.6)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        padding: '40px 40px 36px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 20,
      }}
    >
      {/* Header */}
      <div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '0.14em',
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            marginBottom: 8,
          }}
        >
          Investment Committee · {ticker}
        </div>
        <h2
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 20,
            letterSpacing: '0.12em',
            color: 'var(--text-primary)',
            margin: 0,
          }}
        >
          {t('ic.start.title')}
        </h2>
      </div>

      {/* Description */}
      <p
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 13,
          lineHeight: 1.7,
          color: 'var(--text-secondary)',
          margin: 0,
          maxWidth: 560,
        }}
      >
        {t('ic.start.desc')}
      </p>

      {/* Artifact context */}
      {artifactId && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '10px 14px',
            background: 'color-mix(in srgb, var(--primary) 6%, transparent)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-muted)',
              letterSpacing: '0.06em',
            }}
          >
            {t('ic.start.reportId')}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-secondary)',
            }}
          >
            {artifactId}
          </span>
          <button
            type="button"
            onClick={onViewReport}
            style={{
              marginLeft: 8,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--primary)',
              letterSpacing: '0.04em',
              padding: 0,
              transition: 'opacity 0.18s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.7')}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          >
            {t('ic.start.viewReport')}
          </button>
        </div>
      )}

      {/* Warning if no artifact_id */}
      {!artifactId && (
        <div
          style={{
            padding: '10px 14px',
            background: 'color-mix(in srgb, var(--warning) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--warning) 28%, transparent)',
            borderRadius: 'var(--radius-sm)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--warning)',
          }}
        >
          ⚠ {t('ic.start.noArtifactWarning')}
        </div>
      )}

      {/* Primary CTA — explicit start button, never auto-triggered */}
      <button
        type="button"
        onClick={onStart}
        disabled={!artifactId}
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 13,
          letterSpacing: '0.12em',
          padding: '12px 32px',
          borderRadius: 'var(--radius-md)',
          border: 'none',
          background: artifactId
            ? 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)'
            : 'var(--border-soft)',
          color: artifactId ? 'var(--text-primary)' : 'var(--text-dim)',
          cursor: artifactId ? 'pointer' : 'not-allowed',
          opacity: artifactId ? 1 : 0.55,
          transition: 'opacity 0.18s',
        }}
        onMouseEnter={(e) => {
          if (artifactId) e.currentTarget.style.opacity = '0.88'
        }}
        onMouseLeave={(e) => {
          if (artifactId) e.currentTarget.style.opacity = '1'
        }}
      >
        ⚖ {t('ic.start.cta')}
      </button>
    </div>
  )
}

// Tells the analyst the debate is ephemeral — not saved, not in history/timeline,
// gone on refresh/close. Inline locale literals (precedent: VersionDiffBanner); no
// .po entry until persistence ships and the copy stabilizes.
function EphemeralNotice({ locale }: { locale: 'zh' | 'en' }) {
  const text =
    locale === 'zh'
      ? '此辩论不会被保存——不会出现在历史 / 时间线中,刷新或关闭页面后即丢失。'
      : 'This debate is not saved — it won’t appear in history/timeline and is lost on refresh or close.'
  return (
    <div
      data-testid="ic-ephemeral-notice"
      role="note"
      style={{
        margin: '4px 0 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        background: 'color-mix(in srgb, var(--warning) 7%, transparent)',
        border: '1px solid color-mix(in srgb, var(--warning) 24%, transparent)',
        borderRadius: 'var(--radius-sm)',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        lineHeight: 1.5,
        color: 'var(--warning)',
        letterSpacing: '0.02em',
      }}
    >
      <span aria-hidden>⚠</span>
      <span>{text}</span>
    </div>
  )
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      style={{
        padding: '12px 16px',
        background: 'color-mix(in srgb, var(--danger) 8%, transparent)',
        border: '1px solid color-mix(in srgb, var(--danger) 28%, transparent)',
        borderRadius: 'var(--radius-sm)',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--danger)',
        letterSpacing: '0.04em',
      }}
    >
      {message}
    </div>
  )
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '40px 32px 80px' }}>{children}</div>
  )
}

// ── Button styles ─────────────────────────────────────────────────────────────

const backBtnStyle: React.CSSProperties = {
  width: 28,
  height: 28,
  display: 'grid',
  placeItems: 'center',
  border: '1px solid var(--border-soft)',
  background: 'transparent',
  borderRadius: 6,
  cursor: 'pointer',
  color: 'var(--text-secondary)',
  fontSize: 16,
  transition: 'all 0.18s',
  flexShrink: 0,
}

const crumbBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  padding: 0,
  margin: 0,
  cursor: 'pointer',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  letterSpacing: '0.08em',
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  transition: 'color 0.18s',
}

const primaryBtnStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  letterSpacing: '0.06em',
  padding: '7px 16px',
  borderRadius: 6,
  border: 'none',
  background: 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)',
  color: 'var(--text-primary)',
  cursor: 'pointer',
  transition: 'opacity 0.18s',
}

const secondaryBtnStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  letterSpacing: '0.06em',
  padding: '7px 16px',
  borderRadius: 6,
  border: '1px solid var(--border-soft)',
  background: 'transparent',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
  transition: 'all 0.18s',
}
