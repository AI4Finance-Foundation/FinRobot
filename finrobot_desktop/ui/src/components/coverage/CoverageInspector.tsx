// CoverageInspector — the desk's right rail, scoped to the ONE focused ticker
// (distinct from the multi-select batch set). Four lenses behind tabs:
//   • Live Market Snapshot   — current price / 1D / market cap / provider (live)
//   • Latest Research Artifact — report date / at-run price / target / live upside
//   • Artifact History        — every run for this ticker (real timeline endpoint)
//   • Data Quality            — currency, TTM basis, warnings / provenance
//
// The Live vs Report split is load-bearing (redesign §5): the artifact's at-run
// price (entry_price, frozen at report time) is shown beside the live price and
// is NEVER overwritten by it. Live Upside is explicitly labelled "vs latest
// price" so it's never mistaken for the report's entry-based upside.

import { useState } from 'react'
import { useI18n } from '../../i18n'
import {
  formatAge,
  formatCompactNumber,
  formatCurrency,
  formatDate,
  formatPercent,
} from '../../utils/format'
import { useV5ArtifactTimeline } from '../../hooks/useV5Artifacts'
import type { CoverageRow } from '../../api/coverage'

type Tab = 'live' | 'report' | 'history' | 'quality'

interface Props {
  row: CoverageRow | null
  onRun: (ticker: string) => void
  onOpen: (ticker: string) => void
  onCompare: (ticker: string) => void
  onRemove: (ticker: string) => void
  // True when comparison is actually possible (focused + selection ≥ 2 distinct
  // tickers). When false, Compare is disabled with explanatory copy instead of
  // looking actionable and then just toasting "需要两个" (BUG: dead-end button).
  compareReady: boolean
  // 'side' = fixed 300px right rail (wide layout); 'dock' = full-width panel
  // stacked below the card wall with a capped height (narrow layout), so a
  // 300px rail never crushes the cards on a small / AI-panel-open window.
  layout: 'side' | 'dock'
}

const VERDICT_COLOR: Record<string, string> = {
  BUY: 'var(--success)',
  HOLD: 'var(--warning)',
  SELL: 'var(--danger)',
}

function changeColor(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return 'var(--text-primary)'
  return v > 0 ? 'var(--success)' : 'var(--danger)'
}

export function CoverageInspector({
  row,
  onRun,
  onOpen,
  onCompare,
  onRemove,
  compareReady,
  layout,
}: Props): React.ReactElement {
  const { t } = useI18n()
  const [tab, setTab] = useState<Tab>('live')
  const shell = layout === 'dock' ? DOCK_SHELL : SHELL

  if (!row) {
    return (
      <aside
        data-testid="coverage-inspector"
        style={shell}
        aria-label={t('coverage.inspector.title')}
      >
        <div
          style={{
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            textAlign: 'center',
            padding: 16,
          }}
        >
          {t('coverage.inspector.empty')}
        </div>
      </aside>
    )
  }

  return (
    <aside
      data-testid="coverage-inspector"
      style={shell}
      aria-label={t('coverage.inspector.title')}
    >
      {/* Header — ticker / company + verdict. */}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 22,
              letterSpacing: '2px',
              color: 'var(--text-primary)',
            }}
          >
            {row.ticker}
          </div>
          <div
            title={row.company ?? row.ticker}
            style={{
              marginTop: 3,
              color: 'var(--text-muted)',
              fontSize: 12,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {row.company ?? row.ticker}
          </div>
        </div>
        {row.latest_verdict && (
          <div
            style={{
              flexShrink: 0,
              alignSelf: 'flex-start',
              padding: '6px 10px',
              borderRadius: 'var(--radius-md)',
              fontFamily: 'var(--font-display)',
              fontSize: 12,
              letterSpacing: '2px',
              color: VERDICT_COLOR[row.latest_verdict] ?? 'var(--text-secondary)',
              border: '1px solid var(--border-soft)',
            }}
          >
            {row.latest_verdict}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 6, margin: '12px 0' }}>
        {(['live', 'report', 'history', 'quality'] as const).map((tb) => {
          const active = tab === tb
          return (
            <button
              key={tb}
              type="button"
              onClick={() => setTab(tb)}
              aria-pressed={active}
              style={{
                flex: 1,
                padding: '6px 8px',
                borderRadius: 'var(--radius-pill)',
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                cursor: 'pointer',
                border: `1px solid ${active ? 'var(--border-cyan-soft)' : 'var(--border-faint)'}`,
                background: active ? 'var(--accent-cyan-soft)' : 'var(--bg-card-overlay)',
                color: active ? 'var(--accent-cyan)' : 'var(--text-muted)',
              }}
            >
              {t(`coverage.inspector.tab.${tb}`)}
            </button>
          )
        })}
      </div>

      {/* Body — scrolls; one panel per tab. */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {tab === 'live' && <LivePanel row={row} />}
        {tab === 'report' && <ReportPanel row={row} />}
        {tab === 'history' && <HistoryPanel row={row} />}
        {tab === 'quality' && <QualityPanel row={row} />}
      </div>

      {/* Actions — always visible. */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 12 }}>
        <ActionButton
          label={t('coverage.inspector.runResearch')}
          onClick={() => onRun(row.ticker)}
        />
        <ActionButton
          label={t('coverage.inspector.openStock')}
          onClick={() => onOpen(row.ticker)}
        />
        <ActionButton
          label={
            compareReady ? t('coverage.inspector.compare') : t('coverage.inspector.compareHint')
          }
          onClick={() => onCompare(row.ticker)}
          disabled={!compareReady}
        />
        <ActionButton
          label={t('coverage.inspector.remove')}
          danger
          onClick={() => onRemove(row.ticker)}
        />
      </div>
      <div
        style={{
          marginTop: 10,
          padding: '10px 12px',
          border: '1px solid var(--border-faint)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--text-muted)',
          fontSize: 11,
          lineHeight: 1.5,
        }}
      >
        {t('coverage.inspector.removeNote')}
      </div>
    </aside>
  )
}

// ── Panels ───────────────────────────────────────────────────────────────────

function LivePanel({ row }: { row: CoverageRow }): React.ReactElement {
  const { t, locale } = useI18n()
  const ccy = row.currency || 'USD'
  return (
    <Panel title={t('coverage.inspector.liveTitle')}>
      <Kv label={t('coverage.col.price')}>{formatCurrency(row.price, ccy, locale)}</Kv>
      <Kv label="1D" valueColor={changeColor(row.change_pct_1d)}>
        {row.change_pct_1d == null
          ? '—'
          : `${row.change_pct_1d > 0 ? '+' : ''}${row.change_pct_1d.toFixed(2)}%`}
      </Kv>
      <Kv label={t('coverage.col.mcap')}>
        {row.market_cap == null ? '—' : `${ccy} ${formatCompactNumber(row.market_cap, locale)}`}
      </Kv>
      <Kv label={t('coverage.inspector.provider')}>{row.sources?.price?.provider ?? '—'}</Kv>
      <Kv label={t('coverage.inspector.asOf')}>
        {row.price_as_of ? formatAge(row.price_as_of) : '—'}
      </Kv>
    </Panel>
  )
}

function ReportPanel({ row }: { row: CoverageRow }): React.ReactElement {
  const { t, locale } = useI18n()
  const ccy = row.currency || 'USD'
  // "Latest Research" shows the latest THESIS-bearing research only. A ticker
  // with just model artifacts (DCF/LBO/comps) has research_count 0 → no report.
  if (row.research_count === 0) {
    return (
      <Panel title={t('coverage.inspector.reportTitle')}>
        <div style={{ color: 'var(--text-muted)', fontSize: 11, padding: '6px 0' }}>
          {row.artifact_count > 0
            ? t('coverage.card.modelOnly', { n: row.artifact_count })
            : t('coverage.inspector.noReport')}
        </div>
      </Panel>
    )
  }
  return (
    <Panel title={t('coverage.inspector.reportTitle')}>
      <Kv label={t('coverage.inspector.reportDate')}>
        {row.latest_at ? formatDate(row.latest_at, locale, 'short') : '—'}
      </Kv>
      {/* At-run price = entry_price, frozen at report time — shown beside the
          live price above and never overwritten by it (§5). */}
      <Kv label={t('coverage.inspector.atRunPrice')}>
        {formatCurrency(row.entry_price, ccy, locale)}
      </Kv>
      <Kv label={t('coverage.inspector.targetPrice')}>
        {formatCurrency(row.target_price, ccy, locale)}
      </Kv>
      <Kv
        label={t('coverage.inspector.liveUpside')}
        valueColor={changeColor(row.upside_to_target_live)}
      >
        {row.upside_to_target_live == null
          ? '—'
          : t('coverage.inspector.upsideVsLatest', {
              pct: formatPercent(row.upside_to_target_live, locale, 1),
            })}
      </Kv>
    </Panel>
  )
}

// Match the coverage service's own list_by_ticker ceiling (200) so History
// shows every artifact the card counts, not the endpoint's default-50 slice.
const HISTORY_LIMIT = 200

function HistoryPanel({ row }: { row: CoverageRow }): React.ReactElement {
  const { t, locale } = useI18n()
  // Every artifact for this ticker (research + models), newest first — the full
  // timeline, archived included (audit §19). Explicit limit so a heavily-run
  // ticker isn't truncated at the endpoint default while the header counts more.
  const { data, isLoading, isError } = useV5ArtifactTimeline(row.ticker, HISTORY_LIMIT)

  return (
    <Panel title={t('coverage.inspector.historyTitle')}>
      {/* Honest tally: thesis research vs all records. */}
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 6 }}>
        {t('coverage.inspector.recordCounts', {
          research: row.research_count,
          artifact: row.artifact_count,
        })}
      </div>
      {isLoading ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 11, padding: '6px 0' }}>…</div>
      ) : isError ? (
        <div style={{ color: 'var(--danger)', fontSize: 11, padding: '6px 0' }}>
          {t('coverage.inspector.historyError')}
        </div>
      ) : !data || data.length === 0 ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 11, padding: '6px 0' }}>
          {t('coverage.inspector.noReport')}
        </div>
      ) : (
        data.map((a, i) => (
          <div
            key={a.id}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 10,
              padding: '8px 0',
              borderTop: i === 0 ? 'none' : '1px solid var(--border-faint)',
            }}
          >
            <span style={{ minWidth: 0 }}>
              <strong
                style={{
                  display: 'block',
                  color: 'var(--text-primary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              >
                {formatDate(a.created_at, locale, 'short')}
                {a.verdict ? ` · ${a.verdict}` : ''}
              </strong>
              <span
                style={{
                  display: 'block',
                  color: 'var(--text-muted)',
                  fontSize: 11,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {a.tagline || a.type}
              </span>
            </span>
            <a
              href={`/stocks/${row.ticker}/runs/${a.id}`}
              aria-label={t('coverage.inspector.openArtifact')}
              title={t('coverage.inspector.openArtifact')}
              style={{
                flexShrink: 0,
                width: 28,
                height: 28,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '1px solid var(--border-soft)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-elevated)',
                color: 'var(--text-secondary)',
                textDecoration: 'none',
              }}
            >
              ↗
            </a>
          </div>
        ))
      )}
    </Panel>
  )
}

function QualityPanel({ row }: { row: CoverageRow }): React.ReactElement {
  const { t } = useI18n()
  return (
    <Panel title={t('coverage.inspector.qualityTitle')}>
      <Kv label={t('coverage.inspector.currency')}>{row.currency ?? '—'}</Kv>
      <Kv label={t('coverage.inspector.revenueBasis')}>TTM</Kv>
      <Kv label={t('coverage.inspector.priceAsOf')}>
        {row.sources?.price?.as_of ? formatAge(row.sources.price.as_of) : '—'}
      </Kv>
      {row.warnings.length === 0 ? (
        <Kv label={t('coverage.inspector.warning')}>{t('coverage.inspector.noWarning')}</Kv>
      ) : (
        <div style={{ paddingTop: 6 }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>
            {t('coverage.inspector.warning')}
          </div>
          {row.warnings.map((w, i) => (
            <div key={i} style={{ color: 'var(--accent-amber)', fontSize: 11, lineHeight: 1.5 }}>
              · {w}
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

// ── Primitives ───────────────────────────────────────────────────────────────

const SHELL: React.CSSProperties = {
  width: 300,
  flexShrink: 0,
  display: 'flex',
  flexDirection: 'column',
  padding: 16,
  border: '1px solid var(--border-glow)',
  borderRadius: 'var(--radius-lg)',
  background: 'var(--bg-card-deep)',
  overflow: 'hidden',
}

// Dock variant: full-width, stacked below the card wall, height-capped with the
// body scrolling internally (the tab panels already scroll) so it never pushes
// the card wall off-screen on a narrow window.
const DOCK_SHELL: React.CSSProperties = {
  ...SHELL,
  width: '100%',
  maxHeight: 320,
  flexShrink: 0,
}

function Panel({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}): React.ReactElement {
  return (
    <section
      style={{
        padding: 12,
        marginBottom: 12,
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-faint)',
        background: 'var(--bg-card-translucent)',
      }}
    >
      <div
        style={{
          marginBottom: 8,
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-display)',
          fontSize: 11,
          letterSpacing: '1.4px',
        }}
      >
        {title}
      </div>
      {children}
    </section>
  )
}

function Kv({
  label,
  children,
  valueColor,
}: {
  label: string
  children: React.ReactNode
  valueColor?: string
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) auto',
        gap: 10,
        padding: '6px 0',
        borderTop: '1px solid var(--border-faint)',
        color: 'var(--text-muted)',
        fontSize: 11,
      }}
    >
      <span>{label}</span>
      <strong
        style={{
          color: valueColor ?? 'var(--text-primary)',
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
        }}
      >
        {children}
      </strong>
    </div>
  )
}

function ActionButton({
  label,
  onClick,
  danger,
  disabled,
}: {
  label: string
  onClick: () => void
  danger?: boolean
  disabled?: boolean
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '9px 10px',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--bg-card-overlay)',
        color: danger ? 'var(--danger)' : 'var(--text-secondary)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        fontSize: 12,
      }}
    >
      {label}
    </button>
  )
}
