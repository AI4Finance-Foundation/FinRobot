// CoverageCard — one ticker in the workspace card wall. Uniform height via a
// minHeight FLOOR (comfort 244 / compact 196), not a hard `height` cap: the
// content (head · price · 2×2 metrics · quality row · report count) is
// fixed-shape — company names ellipsis, status text ellipsis — so every card
// renders the same height anyway, but a hard cap shorter than that content
// silently clipped the bottom row. The floor keeps the rhythm without ever
// hiding content. Every
// number renders through SourcedNumber (provenance popover + inline amber
// warning), 涨绿跌红, mono digits, all colors via cosmic tokens.
//
// Fields (locked by the redesign spec): ticker/company · price/1D · verdict ·
// market cap · revenue TTM · EV/EBITDA-or-P/E · live upside · warning/freshness ·
// report count + latest report date. Live Upside is labelled "vs latest price"
// in the inspector; on the dense card the column header carries that meaning.

import { memo } from 'react'
import { useI18n } from '../../i18n'
import {
  formatAge,
  formatCompactNumber,
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from '../../utils/format'
import { SourcedNumber } from '../SourcedNumber'
import { coveragePriority } from './coveragePriority'
import type { CoverageRow } from '../../api/coverage'
import type { CoverageDensity } from '../../stores/coverageStore'

interface Props {
  row: CoverageRow
  density: CoverageDensity
  // Fast-skeleton phase: market cells render as a loading shimmer, not '—'.
  marketPending?: boolean
  // True only in the Needs Action triage view — surfaces the full, un-truncated
  // "why this card needs you" reason row (UX-005). Kept off the All view so it
  // stays compact.
  showReasons?: boolean
  onOpen: (ticker: string) => void
}

const VERDICT: Record<string, { color: string; bg: string }> = {
  BUY: { color: 'var(--success)', bg: 'var(--success-soft)' },
  HOLD: { color: 'var(--warning)', bg: 'var(--warning-soft)' },
  SELL: { color: 'var(--danger)', bg: 'var(--danger-soft)' },
}

function changeColor(v: number | null): string {
  if (v === null || v === 0) return 'var(--text-secondary)'
  return v > 0 ? 'var(--success)' : 'var(--danger)'
}

// The single most pressing line for the quality row: an in-flight run, a
// failure, a refresh reason, a data warning — else "fresh". Tone drives the pill
// color (cyan = ok/live, amber = attention). Never hover-only (cosmic spec).
function cardStatus(
  row: CoverageRow,
  t: (k: string) => string,
): { text: string; tone: 'ok' | 'warn' } {
  if (row.run_status === 'running' || row.run_status === 'created')
    return { text: t('coverage.running'), tone: 'ok' }
  const { reasons } = coveragePriority(row)
  if (reasons.length > 0) return { text: reasons[0], tone: 'warn' }
  return { text: t('coverage.card.fresh'), tone: 'ok' }
}

export const CoverageCard = memo(function CoverageCard({
  row,
  density,
  marketPending = false,
  showReasons = false,
  onOpen,
}: Props): React.ReactElement {
  const { t, locale } = useI18n()
  const compact = density === 'compact'
  const ccy = row.currency || 'USD'
  const verdict = row.latest_verdict ? VERDICT[row.latest_verdict] : null
  const status = cardStatus(row, t)
  const priority = coveragePriority(row)
  const needsWarn = priority.needsAction
  // Up to two reasons, shown un-truncated (line-clamp:2) in the triage view so
  // the analyst sees WHY each card needs them without opening the inspector
  // (UX-005). Only in Needs Action — the All view stays compact.
  const reasonRows = showReasons && needsWarn ? priority.reasons.slice(0, 2) : []

  const mc = (node: React.ReactNode): React.ReactNode => (marketPending ? <Shimmer /> : node)

  // EV/EBITDA when computable, else P/E — one slot, label follows the value.
  const useEv = row.ev_ebitda != null
  const multipleLabel = useEv ? 'EV/EBITDA' : 'P/E TTM'
  const multipleValue = useEv ? row.ev_ebitda : row.pe
  const multipleSource = useEv ? row.sources?.ev_ebitda : row.sources?.pe

  const provider = row.sources?.price?.provider ?? null
  const asOf = row.price_as_of ? formatAge(row.price_as_of) : ccy

  return (
    <article
      data-ticker={row.ticker}
      data-testid={`coverage-card-${row.ticker}`}
      role="link"
      tabIndex={0}
      aria-label={t('coverage.card.open', { ticker: row.ticker })}
      onClick={() => onOpen(row.ticker)}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(row.ticker)
        }
      }}
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        // Default grid stretch is fine now that the grid uses
        // gridAutoRows:'max-content' — the row track is sized to full content, so
        // stretch makes every card in a row equal height (uniform wall) without
        // clipping or overflowing into the next row. minHeight is just a floor.
        minHeight: compact ? 196 : 244,
        padding: compact ? 12 : 16,
        boxSizing: 'border-box',
        cursor: 'pointer',
        borderRadius: 'var(--radius-lg)',
        border: `1px solid ${needsWarn ? 'var(--border-amber-soft)' : 'var(--border-soft)'}`,
        background: 'linear-gradient(180deg, var(--bg-card-deep), var(--bg-card-overlay))',
        boxShadow: 'none',
        // NOTE: content-visibility:auto windowing was removed here. It reported
        // contain-intrinsic-size as the card's grid-row height, capping the box
        // shorter than its content and clipping the actions row (run/open) — the
        // exact bug this card had. For a coverage desk (tens, low-hundreds of
        // tickers) rendering every card is cheap; a true 1000+ wall would want
        // real list virtualization, not a size hint that silently truncates.
      }}
    >
      {/* Head: ticker / company + state badge. The entire card opens the ticker
          workspace; running research lives inside that workspace, not on the
          coverage archive card. */}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: compact ? 16 : 20,
              letterSpacing: '2.2px',
              color: 'var(--text-primary)',
            }}
          >
            {row.ticker}
          </div>
          <div
            title={row.company ?? row.ticker}
            style={{
              marginTop: 4,
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
        <span
          style={{
            flexShrink: 0,
            marginTop: 2,
            width: 18,
            height: 18,
            borderRadius: 'var(--radius-pill)',
            border: '1px solid var(--border-soft)',
            background: needsWarn ? 'var(--warning-soft)' : 'var(--primary-soft)',
            boxShadow: needsWarn ? 'var(--warning-glow)' : 'var(--glow-blue-soft)',
          }}
          aria-hidden
        />
      </div>

      {/* Price + 1D, with the verdict badge. */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 12,
          marginTop: compact ? 10 : 14,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: compact ? 16 : 22,
              fontWeight: 700,
              color: 'var(--text-primary)',
            }}
          >
            {mc(
              <SourcedNumber
                value={row.price}
                source={row.sources?.price ?? undefined}
                ticker={row.ticker}
                format={(v) => formatCurrency(v, ccy, locale)}
              />,
            )}
          </div>
          <div
            style={{
              marginTop: 4,
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              color: changeColor(row.change_pct_1d),
            }}
          >
            {mc(
              row.change_pct_1d == null ? (
                <span style={{ color: 'var(--text-dim)' }}>—</span>
              ) : (
                `${row.change_pct_1d > 0 ? '+' : ''}${row.change_pct_1d.toFixed(2)}% · 1D`
              ),
            )}
          </div>
        </div>
        <div
          style={{
            flexShrink: 0,
            minWidth: compact ? 58 : 72,
            padding: compact ? '6px 8px' : '8px 10px',
            borderRadius: 'var(--radius-md)',
            textAlign: 'center',
            fontFamily: 'var(--font-display)',
            fontSize: compact ? 10 : 12,
            letterSpacing: '2px',
            color: verdict ? verdict.color : 'var(--text-muted)',
            background: verdict ? verdict.bg : 'var(--neutral-soft)',
            border: `1px solid ${verdict ? verdict.bg : 'var(--border-soft)'}`,
          }}
        >
          {row.latest_verdict ?? t('coverage.notRun')}
        </div>
      </div>

      {/* Why this card needs action (UX-005) — un-truncated (line-clamp:2, NOT
          nowrap-ellipsis: backend detail length is uncontrolled). Triage view
          only; the card minHeight is a floor and the grid uses
          gridAutoRows:'max-content', so a 2-line row grows the card, never clips
          it. */}
      {reasonRows.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            marginTop: compact ? 8 : 10,
          }}
        >
          {reasonRows.map((reason, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 6,
                color: 'var(--accent-amber)',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                lineHeight: 1.4,
              }}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 16 16"
                role="img"
                aria-hidden="true"
                style={{ flexShrink: 0, marginTop: 1 }}
              >
                <path
                  d="M8 2 L14.5 13.5 H1.5 Z"
                  fill="var(--warning-soft)"
                  stroke="var(--warning)"
                  strokeWidth="1.3"
                  strokeLinejoin="round"
                />
                <line
                  x1="8"
                  y1="6.2"
                  x2="8"
                  y2="9.6"
                  stroke="var(--warning)"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                />
                <circle cx="8" cy="11.4" r="0.85" fill="var(--warning)" />
              </svg>
              <span
                style={{
                  minWidth: 0,
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                }}
              >
                {reason}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Metrics 2×2 — market cap / revenue TTM / EV-EBITDA-or-PE / live upside.
          Fixed four slots so the card height never depends on data. */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: compact ? 6 : 8,
          marginTop: compact ? 8 : 12,
        }}
      >
        <Metric label={t('coverage.col.mcap')}>
          {mc(
            <SourcedNumber
              value={row.market_cap}
              source={row.sources?.market_cap ?? undefined}
              ticker={row.ticker}
              format={(v) => `${ccy} ${formatCompactNumber(v, locale)}`}
            />,
          )}
        </Metric>
        <Metric label={t('coverage.col.revttm')}>
          {mc(
            <SourcedNumber
              value={row.revenue_ttm}
              source={row.sources?.revenue_ttm ?? undefined}
              ticker={row.ticker}
              format={(v) => `${ccy} ${formatCompactNumber(v, locale)}`}
            />,
          )}
        </Metric>
        <Metric label={multipleLabel}>
          {mc(
            <SourcedNumber
              value={multipleValue}
              source={multipleSource ?? undefined}
              ticker={row.ticker}
              format={(v) => `${formatNumber(v, locale, 1)}×`}
            />,
          )}
        </Metric>
        <Metric label={t('coverage.col.upside')}>
          <span style={{ color: changeColor(row.upside_to_target_live) }}>
            {mc(
              <SourcedNumber
                value={row.upside_to_target_live}
                source={row.sources?.upside_to_target_live ?? undefined}
                ticker={row.ticker}
                format={(v) => formatPercent(v, locale, 1)}
              />,
            )}
          </span>
        </Metric>
      </div>

      {/* Quality row — freshness / warning pill + provider·as_of. Pushed to the
          bottom so all cards align regardless of company-name length. */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 10,
          marginTop: 'auto',
          paddingTop: 10,
          minWidth: 0,
        }}
      >
        <span
          title={status.text}
          style={{
            flexShrink: 1,
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            padding: '5px 8px',
            borderRadius: 'var(--radius-pill)',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: status.tone === 'warn' ? 'var(--accent-amber)' : 'var(--accent-cyan)',
            background: status.tone === 'warn' ? 'var(--warning-soft)' : 'var(--accent-cyan-soft)',
            border: `1px solid ${
              status.tone === 'warn' ? 'var(--border-amber-soft)' : 'var(--border-cyan-soft)'
            }`,
          }}
        >
          {status.text}
        </span>
        <span
          title={provider ?? undefined}
          style={{
            flexShrink: 0,
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            whiteSpace: 'nowrap',
          }}
        >
          {provider ? `${provider} · ${asOf}` : asOf}
        </span>
      </div>

      {/* Report count + latest date. Card click opens the ticker workspace, where
          the user can run research and inspect prior artifacts. */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-start',
          alignItems: 'center',
          gap: 8,
          marginTop: compact ? 8 : 10,
        }}
      >
        <span
          style={{
            minWidth: 0,
            textAlign: 'left',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {/* Honest tally: "N 份研报" counts ONLY thesis-bearing research
              (research_count). A ticker with just model runs (DCF/LBO/comps)
              shows the model-record count, never inflated into a report count. */}
          {row.research_count > 0
            ? t('coverage.card.reports', {
                n: row.research_count,
                date: row.latest_at ? formatDate(row.latest_at, locale, 'short') : '—',
              })
            : row.artifact_count > 0
              ? t('coverage.card.modelOnly', { n: row.artifact_count })
              : t('coverage.card.noReports')}
        </span>
      </div>
    </article>
  )
})

function Metric({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        gap: 8,
        minWidth: 0,
        padding: '7px 9px',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--border-faint)',
        background: 'var(--bg-card-translucent)',
      }}
    >
      <span
        style={{
          color: 'var(--text-muted)',
          fontSize: 10,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </span>
      <span
        style={{
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          whiteSpace: 'nowrap',
        }}
      >
        {children}
      </span>
    </div>
  )
}

function Shimmer(): React.ReactElement {
  return (
    <span
      className="skeleton"
      role="img"
      aria-label="loading"
      style={{ display: 'inline-block', width: 44, height: 11, verticalAlign: 'middle' }}
    />
  )
}
