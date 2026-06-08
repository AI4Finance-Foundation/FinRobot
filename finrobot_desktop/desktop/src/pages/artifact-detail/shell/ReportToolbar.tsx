// Sticky top toolbar for the 13-chapter research report view.
//
// Single-row, Finder-style (Spacedrive-inspired): one ← back arrow that returns
// to wherever the user came from, the ticker label, a quote strip with live
// price / change / distance to target, and Export / Re-run actions. The chrome
// lives in one 48px row so the chapter content gets the screen height. Version
// switching lives in the right-rail Version Timeline (click a version → its
// report); What-if assumption editing lives in the right rail too.

import { useNavigate } from 'react-router-dom'
import { useTickerPrice } from '../../../hooks/useTickerData'
import { useHistoryBack } from '../../../hooks/useHistoryBack'
import { useRunStreamStore } from '../../../stores/runStreamStore'
import { useToastStore } from '../../../stores/toastStore'
import { useI18n } from '../../../i18n'
import { mapErrorToUserMessage } from '../../../utils/errorMessage'

interface ReportToolbarProps {
  ticker: string
  artifactId: string
  reportType: string
  targetPrice: number | null
  /** Export the report as a self-contained interactive HTML. Owned by
      ArtifactDetailPage (it holds the artifact + the query cache to inline). */
  onExportHtml: () => void
  /** Navigate to /ic/:ticker?artifact_id=<id>. Only passed for equity_research reports. */
  onOpenIcDebate?: () => void
}

export function ReportToolbar({
  ticker,
  artifactId,
  reportType,
  targetPrice,
  onExportHtml,
  onOpenIcDebate,
}: ReportToolbarProps): React.ReactElement {
  const navigate = useNavigate()
  // Back = return to wherever the user opened the report from. Falls back to the
  // ticker workspace on a cold-start / deep link, the report's natural parent.
  const goBack = useHistoryBack(`/stocks/${ticker}`)
  const { data: priceData } = useTickerPrice(ticker)
  const startRun = useRunStreamStore((s) => s.startRun)
  const addToast = useToastStore((s) => s.addToast)
  const { t } = useI18n()

  const livePrice = priceData?.current_price ?? null
  const changePct = priceData?.change_pct ?? null
  const isUp = typeof changePct === 'number' && changePct >= 0
  const distancePct =
    livePrice !== null && targetPrice !== null && livePrice > 0
      ? ((targetPrice - livePrice) / livePrice) * 100
      : null

  // Map artifact type → pipeline_type accepted by POST /api/runs.
  // artifact type uses snake_case; pipeline type uses kebab-case for ic-memo.
  function reportTypeToPipelineType(type: string): string {
    const MAP: Record<string, string> = {
      equity_research: 'research',
      earnings: 'earnings',
      dcf: 'dcf',
      lbo: 'lbo',
      ddm: 'ddm',
      comps: 'comps',
      ic_memo: 'ic-memo',
      peer_research: 'research', // no dedicated pipeline; re-run as full research
      ad_hoc: 'research',
    }
    return MAP[type] ?? 'research'
  }

  async function handleRerun(): Promise<void> {
    const pipelineType = reportTypeToPipelineType(reportType)
    try {
      // Pass the current artifact as the re-run source so the new version's
      // meta.parent_artifact_id records the lineage the diff view follows.
      await startRun(pipelineType, ticker, artifactId)
      addToast({
        type: 'success',
        title: t('report.toolbar.rerunStarted', { ticker, reportType }),
        description: t('report.toolbar.rerunStartedBody'),
      })
      navigate(`/stocks/${ticker}`)
    } catch (err) {
      addToast({
        type: 'error',
        title: t('report.toolbar.rerunFailed'),
        description: mapErrorToUserMessage(err),
      })
    }
  }

  return (
    <div
      data-testid="report-toolbar"
      style={{
        // Stickiness is owned by the grid-item wrapper in ArtifactDetailPage
        // (its parent is the tall grid, so it has room to stick). This bar just
        // provides the chrome — full-bleed bg/blur that covers content scrolling
        // underneath once the wrapper pins it to the top.
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '10px 24px',
        margin: '0 -24px',
        background: 'var(--bg-sticky-88)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        borderBottom: '1px solid var(--border-soft)',
      }}
    >
      {/* Back arrow — returns to where the user came from (useHistoryBack),
          not a hardcoded destination. Version switching lives in the right-rail
          Version Timeline, so no breadcrumb / version dropdown here. */}
      <button
        type="button"
        data-testid="report-back"
        onClick={goBack}
        title={t('report.toolbar.back', { ticker })}
        style={backBtnStyle}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = 'var(--text-primary)'
          e.currentTarget.style.background = 'var(--wash-white-04)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = 'var(--text-secondary)'
          e.currentTarget.style.background = 'transparent'
        }}
      >
        <ArrowLeft />
      </button>

      {/* Ticker label — lightweight wayfinding (matches the workspace back
          strip's "← TICKER"), not a hierarchy. */}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
          letterSpacing: '0.08em',
          color: 'var(--accent-cyan)',
          textTransform: 'uppercase',
        }}
      >
        {ticker}
      </span>

      {/* Quote strip — only renders if we have live price data. Keeps the
          row from looking empty pre-fetch but doesn't reserve space. */}
      {typeof livePrice === 'number' && (
        <div style={quoteStripStyle}>
          <span style={quotePriceStyle}>${livePrice.toFixed(2)}</span>
          {typeof changePct === 'number' && (
            <span
              style={{
                ...quoteChipStyle,
                background: isUp
                  ? 'color-mix(in srgb, var(--success) 14%, transparent)'
                  : 'color-mix(in srgb, var(--danger) 14%, transparent)',
                color: isUp ? 'var(--success)' : 'var(--danger)',
                border: `1px solid ${
                  isUp
                    ? 'color-mix(in srgb, var(--success) 32%, transparent)'
                    : 'color-mix(in srgb, var(--danger) 32%, transparent)'
                }`,
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
              {t('report.toolbar.toTarget')} {distancePct >= 0 ? '+' : ''}
              {distancePct.toFixed(1)}%
            </span>
          )}
        </div>
      )}

      <span style={{ flex: 1, minWidth: 8 }} />

      {/* Export HTML — page-faithful mirror (see handleExportHtml): same DOM,
          theme, charts, continuous scroll. The single export path. */}
      <ToolbarButton onClick={onExportHtml} title={t('report.toolbar.exportHtmlTitle')}>
        ⤓ {t('report.toolbar.exportHtml')}
      </ToolbarButton>

      {/* Primary actions — Re-run is the focal CTA. Version comparison lives
          inline in the report body (VersionDiffBanner), not as a toolbar modal. */}
      <ToolbarButton onClick={handleRerun} primary>
        ↻ {t('report.toolbar.rerun')}
      </ToolbarButton>
      {/* Version comparison moved inline: the VersionDiffBanner at the top of the
          report body shows "what changed vs a prior version" with a base selector,
          replacing the old modal diff button. */}
      {/* IC Debate entry — only surfaces for equity_research reports. Rendered
          conditionally (not disabled+title) because a disabled element fires no
          hover and title tooltips are mouse-only, so keyboard/touch users would
          get no reason it is unavailable. The handler is already undefined off
          equity, so off-equity reports simply omit the button. */}
      {reportType === 'equity_research' && onOpenIcDebate && (
        <ToolbarButton onClick={onOpenIcDebate} title={t('report.toolbar.icDebateTitle')}>
          ⚖ {t('report.toolbar.icDebate')}
        </ToolbarButton>
      )}
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
        color: primary ? 'var(--text-primary)' : 'var(--text-secondary)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        letterSpacing: '0.04em',
        transition: 'all 0.18s',
        whiteSpace: 'nowrap',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
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
