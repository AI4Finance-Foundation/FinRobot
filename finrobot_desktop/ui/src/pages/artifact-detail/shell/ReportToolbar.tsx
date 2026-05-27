// Sticky top toolbar for the 12-chapter research report view.
//
// Single-row, Finder-style (Spacedrive-inspired): one ← back arrow as the
// canonical return path, a 3-segment breadcrumb whose tail doubles as a
// version dropdown, a quote strip with live price / change / distance to
// target, and primary Re-run + Diff actions. The chrome lives in one
// 48px row so the chapter content gets the screen height. What-if
// assumption editing lives in the right rail panel, not here.

import { useNavigate } from 'react-router-dom'
import { useTickerPrice } from '../../../hooks/useTickerData'
import { useRunStreamStore } from '../../../stores/runStreamStore'
import { useToastStore } from '../../../stores/toastStore'
import type { ArtifactSummaryV5 } from '../../../types/v5'
import { useI18n } from '../../../i18n'
import { formatDate } from '../../../utils/format'
import { mapErrorToUserMessage } from '../../../utils/errorMessage'

interface ReportToolbarProps {
  ticker: string
  artifactId: string
  reportType: string
  reportVersionLabel: string
  targetPrice: number | null
  timeline: ArtifactSummaryV5[]
  onOpenDiff: () => void
}

export function ReportToolbar({
  ticker,
  artifactId,
  reportType,
  reportVersionLabel,
  targetPrice,
  timeline,
  onOpenDiff,
}: ReportToolbarProps): React.ReactElement {
  const navigate = useNavigate()
  const { data: priceData } = useTickerPrice(ticker)
  const startRun = useRunStreamStore((s) => s.startRun)
  const addToast = useToastStore((s) => s.addToast)
  const { locale, t } = useI18n()

  const livePrice = priceData?.current_price ?? null
  const changePct = priceData?.change_pct ?? null
  const isUp = typeof changePct === 'number' && changePct >= 0
  const distancePct =
    livePrice !== null && targetPrice !== null && livePrice > 0
      ? ((targetPrice - livePrice) / livePrice) * 100
      : null

  const sameTypeTimeline = timeline.filter((a) => a.type === reportType)

  async function handleRerun(): Promise<void> {
    try {
      await startRun('research', ticker)
      addToast({
        type: 'success',
        title: `${ticker} 重跑研报已启动`,
        description: '分析进行中，完成后可在工作区抽屉查看版本历史',
      })
      navigate(`/stocks/${ticker}`)
    } catch (err) {
      addToast({
        type: 'error',
        title: '启动重跑失败',
        description: mapErrorToUserMessage(err),
      })
    }
  }

  function handleVersionChange(targetArtifactId: string): void {
    if (targetArtifactId && targetArtifactId !== artifactId) {
      navigate(`/stocks/${ticker}/runs/${targetArtifactId}`)
    }
  }

  return (
    <div
      data-testid="report-toolbar"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 30,
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '10px 24px',
        margin: '0 -24px 16px',
        background: 'var(--bg-sticky-88)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        borderBottom: '1px solid var(--border-soft)',
      }}
    >
      {/* Back arrow — the single canonical return path. Always goes to the
          ticker workspace so the breadcrumb and the arrow stay in sync. */}
      <button
        type="button"
        data-testid="report-back"
        onClick={() => navigate(`/stocks/${ticker}`)}
        title={`返回 ${ticker} 工作区`}
        style={backBtnStyle}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = 'var(--text-primary)'
          e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = 'var(--text-secondary)'
          e.currentTarget.style.background = 'transparent'
        }}
      >
        <ArrowLeft />
      </button>

      {/* Breadcrumb — 3 segments, last is a hidden-select dropdown that
          mirrors the version label and lets the user jump siblings. */}
      <div style={breadcrumbBoxStyle}>
        <button type="button" onClick={() => navigate('/stocks')} style={crumbBtnStyle}>
          STOCKS
        </button>
        <Sep />
        <button
          type="button"
          onClick={() => navigate(`/stocks/${ticker}`)}
          style={{ ...crumbBtnStyle, color: 'var(--accent-cyan)' }}
        >
          {ticker}
        </button>
        <Sep />
        <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
          <span style={{ color: 'var(--secondary)' }}>{reportVersionLabel}</span>
          {sameTypeTimeline.length > 1 && (
            <>
              <ChevronDown />
              <select
                data-testid="version-select"
                value={artifactId}
                onChange={(e) => handleVersionChange(e.target.value)}
                title="切换其他版本"
                aria-label="切换其他版本"
                style={hiddenSelectStyle}
              >
                {sameTypeTimeline.map((a) => (
                  <option key={a.id} value={a.id} style={{ background: 'var(--bg-card)' }}>
                    {a.id === artifactId ? `${t('report.timeline.current')} · ` : ''}
                    {formatDate(a.created_at, locale, 'short')}
                    {' · '}
                    {(a.signal ?? 'pending').toUpperCase()}
                  </option>
                ))}
              </select>
            </>
          )}
        </span>
      </div>

      {/* Quote strip — only renders if we have live price data. Keeps the
          row from looking empty pre-fetch but doesn't reserve space. */}
      {typeof livePrice === 'number' && (
        <div style={quoteStripStyle}>
          <span style={quotePriceStyle}>${livePrice.toFixed(2)}</span>
          {typeof changePct === 'number' && (
            <span
              style={{
                ...quoteChipStyle,
                background: isUp ? 'rgba(22,163,74,0.14)' : 'rgba(220,38,38,0.14)',
                color: isUp ? 'var(--success)' : 'var(--danger)',
                border: `1px solid ${isUp ? 'rgba(22,163,74,0.32)' : 'rgba(220,38,38,0.32)'}`,
              }}
            >
              {isUp ? '↑' : '↓'} {Math.abs(changePct).toFixed(2)}%
            </span>
          )}
          {distancePct !== null && (
            <span
              style={{
                ...quoteChipStyle,
                color: 'var(--secondary)',
                background: 'var(--secondary-soft)',
                border: '1px solid var(--secondary)',
              }}
            >
              距目标 {distancePct >= 0 ? '+' : ''}
              {distancePct.toFixed(1)}%
            </span>
          )}
        </div>
      )}

      <span style={{ flex: 1, minWidth: 8 }} />

      {/* Primary actions — Re-run is the focal CTA. Diff sits next to it
          because version comparison is the second most-used action. */}
      <ToolbarButton onClick={handleRerun} primary>
        ↻ Re-run
      </ToolbarButton>
      <ToolbarButton onClick={onOpenDiff}>↹ Diff</ToolbarButton>
    </div>
  )
}

function ArrowLeft(): React.ReactElement {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M15 18L9 12l6-6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ChevronDown(): React.ReactElement {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      style={{ marginLeft: 3, color: 'var(--text-muted)' }}
    >
      <path
        d="M6 9l6 6 6-6"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function Sep(): React.ReactElement {
  return <span style={{ color: 'var(--text-dim)', margin: '0 6px' }}>›</span>
}

function ToolbarButton({
  children,
  onClick,
  disabled,
  primary,
  title,
}: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
  primary?: boolean
  title?: string
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        padding: '6px 11px',
        borderRadius: 6,
        border: primary ? 'none' : '1px solid var(--border-soft)',
        background: primary
          ? 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)'
          : 'transparent',
        color: primary ? 'white' : 'var(--text-secondary)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        letterSpacing: '0.04em',
        transition: 'all 0.18s',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </button>
  )
}

const backBtnStyle: React.CSSProperties = {
  width: 30,
  height: 30,
  display: 'grid',
  placeItems: 'center',
  border: '1px solid var(--border-soft)',
  background: 'transparent',
  borderRadius: 6,
  cursor: 'pointer',
  color: 'var(--text-secondary)',
  transition: 'all 0.18s',
  flexShrink: 0,
}

const breadcrumbBoxStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  letterSpacing: '0.06em',
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  display: 'flex',
  alignItems: 'center',
  minWidth: 0,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
}

const crumbBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  padding: 0,
  margin: 0,
  cursor: 'pointer',
  fontFamily: 'inherit',
  fontSize: 'inherit',
  letterSpacing: 'inherit',
  color: 'var(--text-muted)',
  textTransform: 'inherit',
  transition: 'color 0.18s',
}

const hiddenSelectStyle: React.CSSProperties = {
  position: 'absolute',
  inset: 0,
  opacity: 0,
  cursor: 'pointer',
  appearance: 'none',
  border: 'none',
  background: 'transparent',
}

const quoteStripStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  fontFamily: 'var(--font-mono)',
  paddingLeft: 14,
  borderLeft: '1px solid var(--border-faint)',
  marginLeft: 4,
}

const quotePriceStyle: React.CSSProperties = {
  fontSize: 15,
  color: 'var(--text-primary)',
  fontVariantNumeric: 'tabular-nums',
}

const quoteChipStyle: React.CSSProperties = {
  fontSize: 11,
  padding: '2px 7px',
  borderRadius: 5,
  fontVariantNumeric: 'tabular-nums',
}
