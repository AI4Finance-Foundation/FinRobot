// Sticky top toolbar for the 13-chapter research report view.
//
// Single-row, Finder-style (Spacedrive-inspired): one ← back arrow that returns
// to wherever the user came from, the ticker label, a quote strip with the
// SNAPSHOT price / "as of" date / distance to target, and Export / Re-run
// actions. The price is the report's frozen data-fetch snapshot — NOT a live
// quote — so the toolbar matches the frozen report body (cover, football field,
// technical chapter). Live quotes belong to the workspace dashboard. The chrome
// lives in one 48px row so the chapter content gets the screen height. Version
// switching lives in the right-rail Version Timeline (click a version → its
// report).

import { useNavigate } from 'react-router-dom'
import { useHistoryBack } from '../../../hooks/useHistoryBack'
import { useRunStreamStore, selectRunByTicker } from '../../../stores/runStreamStore'
import { useToastStore } from '../../../stores/toastStore'
import { useI18n } from '../../../i18n'
import { formatCurrency, formatSourceDate } from '../../../utils/format'
import { mapErrorToUserMessage } from '../../../utils/errorMessage'

interface ReportToolbarProps {
  ticker: string
  artifactId: string
  reportType: string
  targetPrice: number | null
  targetLow: number | null
  targetHigh: number | null
  valuationWithheld: boolean
  quoteCurrency: string
  /** The report's frozen data-fetch snapshot quote + when it was taken. The
      toolbar renders THIS, never a live refetch, so the price (and distance to
      target) can't drift away from the frozen report body. */
  snapshotPrice: number | null
  snapshotAsOf: string | null
  /** Export the report as a self-contained interactive HTML. Owned by
      ArtifactDetailPage (it holds the artifact + the query cache to inline). */
  onExportHtml: () => void
}

export function ReportToolbar({
  ticker,
  artifactId,
  reportType,
  targetPrice,
  targetLow,
  targetHigh,
  valuationWithheld,
  quoteCurrency,
  snapshotPrice,
  snapshotAsOf,
  onExportHtml,
}: ReportToolbarProps): React.ReactElement {
  const navigate = useNavigate()
  // Back = return to wherever the user opened the report from. Falls back to the
  // ticker workspace on a cold-start / deep link, the report's natural parent.
  const goBack = useHistoryBack(`/stocks/${ticker}`)
  const startRun = useRunStreamStore((s) => s.startRun)
  // Disable Re-run while this ticker already has a live run. startRun itself
  // refuses duplicates (the store-level lock is the real guard); this is the
  // UX feedback layer so the button reads as unavailable instead of erroring.
  const activeRun = useRunStreamStore(selectRunByTicker(ticker))
  const isRunActive = activeRun?.status === 'running'
  const addToast = useToastStore((s) => s.addToast)
  const { t, locale } = useI18n()
  const rangeLabel =
    isFiniteNumber(targetLow) && isFiniteNumber(targetHigh)
      ? `${formatCurrency(targetLow, quoteCurrency, locale, 2)}–${formatCurrency(
          targetHigh,
          quoteCurrency,
          locale,
          2,
        )}`
      : null
  const targetRangeCopy = locale === 'zh' ? '目标区间' : 'Target range'
  const withheldCopy = locale === 'zh' ? '点目标价已隐藏' : 'Point target withheld'
  const fairValueCopy = locale === 'zh' ? '合理价值' : 'Fair value'
  const withinRangeCopy = locale === 'zh' ? '现价在区间内' : 'within range'
  // In-band = the point is withheld because the snapshot price sits INSIDE the published
  // band → fairly valued (mirrors backend `_range_spans_market`; strict containment
  // matches the band the analyst sees). Lead with "fair value", drop the amber "withheld"
  // alarm — a fairly-valued HOLD is a conclusion, not a data caveat.
  const inFairValueBand =
    valuationWithheld &&
    isFiniteNumber(targetLow) &&
    isFiniteNumber(targetHigh) &&
    typeof snapshotPrice === 'number' &&
    snapshotPrice > 0 &&
    Math.min(targetLow, targetHigh) <= snapshotPrice &&
    snapshotPrice <= Math.max(targetLow, targetHigh)

  // Distance to target is measured from the SNAPSHOT price (the price the target
  // was set against), so it reconciles with the cover's upside — not a live gap.
  const distancePct =
    snapshotPrice !== null && targetPrice !== null && snapshotPrice > 0
      ? ((targetPrice - snapshotPrice) / snapshotPrice) * 100
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
    // Fresh store read, not the render-scope flag: a double-click's second
    // event can land before React re-commits the disabled button, but the
    // first click's occupation is already in the store (written synchronously
    // by startRun), so this read catches it and skips the duplicate toast.
    if (useRunStreamStore.getState().runs[ticker]?.status === 'running') return
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

      {/* Quote strip — the frozen snapshot price + when it was taken + distance
          to target. No live change% chip: a snapshot has no intraday delta, and
          showing one would re-introduce a live number into a point-in-time
          report. Only renders when the artifact carries a snapshot price. */}
      {typeof snapshotPrice === 'number' && (
        <div style={quoteStripStyle} data-testid="report-snapshot-quote">
          {/* Snapshot price in the report's quote currency — never a hardcoded
              `$` (a non-USD ADR would otherwise be mislabelled). */}
          <span style={quotePriceStyle}>
            {formatCurrency(snapshotPrice, quoteCurrency, locale, 2)}
          </span>
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
          {distancePct === null && valuationWithheld && rangeLabel && (
            <>
              <span
                style={{
                  ...quoteChipStyle,
                  // Fairly valued → neutral secondary (the band colour), not the amber
                  // warning a genuine withhold uses.
                  color: inFairValueBand ? 'var(--secondary)' : 'var(--accent-amber)',
                  background: inFairValueBand ? 'var(--secondary-soft)' : 'var(--warning-soft)',
                  border: inFairValueBand
                    ? '1px solid var(--secondary)'
                    : '1px solid color-mix(in srgb, var(--warning) 45%, transparent)',
                }}
              >
                {inFairValueBand ? fairValueCopy : targetRangeCopy} {rangeLabel}
              </span>
              <span
                style={{
                  ...quoteChipStyle,
                  color: 'var(--text-muted)',
                  background: 'var(--wash-white-04)',
                  border: '1px solid var(--border-faint)',
                }}
              >
                {inFairValueBand ? withinRangeCopy : withheldCopy}
              </span>
            </>
          )}
        </div>
      )}

      <span style={{ flex: 1, minWidth: 8 }} />

      {/* "As of" provenance grouped with the actions on the right (ticker/price ·
          value range on the left | as-of · export · re-run on the right) — the
          snapshot date governs what an export/re-run is taken against. */}
      {snapshotAsOf && (
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            letterSpacing: '0.04em',
            whiteSpace: 'nowrap',
          }}
          data-testid="report-asof"
        >
          {t('sourced.asOf')} {formatSourceDate(snapshotAsOf, locale)}
        </span>
      )}

      {/* Export HTML — page-faithful mirror (see handleExportHtml): same DOM,
          theme, charts, continuous scroll. The single export path. */}
      <ToolbarButton onClick={onExportHtml} title={t('report.toolbar.exportHtmlTitle')}>
        ⤓ {t('report.toolbar.exportHtml')}
      </ToolbarButton>

      {/* Primary actions — Re-run is the focal CTA. Version comparison lives
          inline in the report body (VersionDiffBanner), not as a toolbar modal.
          Disabled while the ticker already has a live run: a second click would
          be refused by the store lock anyway, but the button must say so. */}
      <ToolbarButton
        onClick={handleRerun}
        primary
        disabled={isRunActive}
        title={isRunActive ? t('report.toolbar.rerunRunningTitle', { ticker }) : undefined}
      >
        ↻ {t('report.toolbar.rerun')}
      </ToolbarButton>
      {/* Version comparison moved inline: the VersionDiffBanner at the top of the
          report body shows "what changed vs a prior version" with a base selector,
          replacing the old modal diff button. */}
    </div>
  )
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
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
