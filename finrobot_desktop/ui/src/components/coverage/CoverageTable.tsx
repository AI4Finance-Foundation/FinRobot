// CoverageTable — the Coverage Desk's main surface: one row per covered ticker,
// columns tuned for an analyst (price/1D, market cap, TTM revenue, EV/EBITDA,
// P/E, latest verdict, live-to-target upside, signal, runs, refresh reasons).
// Numbers are mono + 涨绿跌红; row-level warnings are inline-visible (amber
// triangle), never hidden — per cosmic spec + Coverage plan M3. Compact
// desktop density, not a marketing hero.

import { useI18n } from '../../i18n'
import {
  formatCompactNumber,
  formatCurrency,
  formatNumber,
  formatPercent,
} from '../../utils/format'
import { SourcedNumber } from '../SourcedNumber'
import type { CoverageRow } from '../../api/coverage'
import type { CoverageSort, CoverageSortKey, SortDir } from './coverageSort'

interface Props {
  rows: CoverageRow[]
  selected: string[]
  // Fast-skeleton phase: market/valuation/signal cells render as loading
  // shimmer (pending), not '—' (missing). Research cells stay real.
  marketPending?: boolean
  // Data-column keys the analyst has hidden (COVERAGE_COLUMNS keys).
  hiddenColumns?: string[]
  sort: CoverageSort | null
  onSort: (key: CoverageSortKey) => void
  onToggle: (ticker: string) => void
  onToggleAll: () => void
  onOpenTicker: (ticker: string) => void
  onRunOne: (ticker: string) => void
}

const TH: React.CSSProperties = {
  textAlign: 'right',
  padding: '8px 10px',
  fontSize: 10,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  fontWeight: 500,
  whiteSpace: 'nowrap',
  borderBottom: '1px solid var(--border-soft)',
  position: 'sticky',
  top: 0,
  background: 'var(--bg-deep)',
  zIndex: 1,
}
const TD: React.CSSProperties = {
  textAlign: 'right',
  padding: '9px 10px',
  fontFamily: 'var(--font-mono)',
  fontSize: 13,
  color: 'var(--text-primary)',
  borderTop: '1px solid var(--border-faint)',
  whiteSpace: 'nowrap',
}

function changeColor(v: number | null): string {
  if (v === null || v === 0) return 'var(--text-secondary)'
  return v > 0 ? 'var(--success)' : 'var(--danger)'
}

const SIGNAL_COLOR: Record<string, string> = {
  hit: 'var(--success)',
  watching: 'var(--accent-cyan)',
  failed: 'var(--danger)',
}

const VERDICT_COLOR: Record<string, string> = {
  BUY: 'var(--success)',
  HOLD: 'var(--warning)',
  SELL: 'var(--danger)',
}

export function CoverageTable({
  rows,
  selected,
  marketPending = false,
  hiddenColumns = [],
  sort,
  onSort,
  onToggle,
  onToggleAll,
  onOpenTicker,
  onRunOne,
}: Props): React.ReactElement {
  const { t, locale } = useI18n()
  const allSelected = rows.length > 0 && selected.length === rows.length

  // Market cell: a loading shimmer in the fast-skeleton phase, the real value
  // otherwise — so "pending" never reads as "missing".
  const mc = (node: React.ReactNode): React.ReactNode => (marketPending ? <CellShimmer /> : node)
  // Column visibility — ticker/select/action are structural and always shown.
  const vis = (key: string): boolean => !hiddenColumns.includes(key)

  // Sortable header — a button so it's keyboard-operable; shows a caret on the
  // active column. Non-sortable columns (verdict/signal/status/action) stay
  // plain <th>.
  function SortTh({
    label,
    sortKey,
    align = 'right',
  }: {
    label: string
    sortKey: CoverageSortKey
    align?: 'left' | 'right'
  }): React.ReactElement {
    const active = sort?.key === sortKey
    return (
      <th style={{ ...TH, padding: 0, textAlign: align }}>
        <button
          type="button"
          onClick={() => onSort(sortKey)}
          aria-label={t('coverage.sortBy', { col: label })}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            width: '100%',
            justifyContent: align === 'left' ? 'flex-start' : 'flex-end',
            padding: '8px 10px',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            font: 'inherit',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            fontSize: 10,
            fontWeight: active ? 600 : 500,
            color: active ? 'var(--text-secondary)' : 'var(--text-muted)',
          }}
        >
          {label}
          <SortCaret dir={active ? sort?.dir : undefined} />
        </button>
      </th>
    )
  }

  return (
    <div style={{ overflow: 'auto', height: '100%' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 920 }}>
        <thead>
          <tr>
            <th style={{ ...TH, textAlign: 'center', width: 32 }}>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={onToggleAll}
                aria-label={t('coverage.table.selectAll')}
              />
            </th>
            <SortTh label={t('coverage.col.ticker')} sortKey="ticker" align="left" />
            {vis('price') && <SortTh label={t('coverage.col.price')} sortKey="price" />}
            {vis('change_pct_1d') && <SortTh label="1D" sortKey="change_pct_1d" />}
            {vis('market_cap') && <SortTh label={t('coverage.col.mcap')} sortKey="market_cap" />}
            {vis('revenue_ttm') && (
              <SortTh label={t('coverage.col.revttm')} sortKey="revenue_ttm" />
            )}
            {vis('ev_ebitda') && <SortTh label="EV/EBITDA" sortKey="ev_ebitda" />}
            {vis('pe') && <SortTh label="P/E" sortKey="pe" />}
            {vis('verdict') && (
              <th style={{ ...TH, textAlign: 'center' }}>{t('coverage.col.verdict')}</th>
            )}
            {vis('upside') && (
              <SortTh label={t('coverage.col.upside')} sortKey="upside_to_target_live" />
            )}
            {vis('signal') && (
              <th style={{ ...TH, textAlign: 'center' }}>{t('coverage.col.signal')}</th>
            )}
            {vis('runs') && <SortTh label={t('coverage.col.runs')} sortKey="run_count" />}
            {vis('status') && (
              <th style={{ ...TH, textAlign: 'center' }}>{t('coverage.col.status')}</th>
            )}
            <th style={{ ...TH, textAlign: 'center', width: 56 }} />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isSel = selected.includes(r.ticker)
            const ccy = r.currency || 'USD'
            return (
              <tr
                key={r.ticker}
                style={{ background: isSel ? 'var(--primary-soft)' : 'transparent' }}
              >
                <td style={{ ...TD, textAlign: 'center' }}>
                  <input
                    type="checkbox"
                    checked={isSel}
                    onChange={() => onToggle(r.ticker)}
                    aria-label={`select ${r.ticker}`}
                  />
                </td>
                <td style={{ ...TD, textAlign: 'left' }}>
                  <button
                    type="button"
                    onClick={() => onOpenTicker(r.ticker)}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      padding: 0,
                      font: 'inherit',
                      color: 'var(--text-primary)',
                      fontWeight: 600,
                    }}
                    title={r.company ?? r.ticker}
                  >
                    {r.ticker}
                  </button>
                </td>
                {vis('price') && (
                  <td style={TD}>
                    {mc(
                      <SourcedNumber
                        value={r.price}
                        source={r.sources?.price ?? undefined}
                        ticker={r.ticker}
                        format={(v) => formatCurrency(v, ccy, locale)}
                      />,
                    )}
                  </td>
                )}
                {vis('change_pct_1d') && (
                  <td style={{ ...TD, color: changeColor(r.change_pct_1d) }}>
                    {mc(
                      <SourcedNumber
                        value={r.change_pct_1d}
                        source={r.sources?.change_pct_1d ?? undefined}
                        ticker={r.ticker}
                        format={(v) => `${v > 0 ? '+' : ''}${v.toFixed(2)}%`}
                      />,
                    )}
                  </td>
                )}
                {vis('market_cap') && (
                  <td style={TD}>
                    {mc(
                      <SourcedNumber
                        value={r.market_cap}
                        source={r.sources?.market_cap ?? undefined}
                        ticker={r.ticker}
                        format={(v) => formatCompactNumber(v, locale)}
                      />,
                    )}
                  </td>
                )}
                {vis('revenue_ttm') && (
                  <td style={TD}>
                    {mc(
                      <SourcedNumber
                        value={r.revenue_ttm}
                        source={r.sources?.revenue_ttm ?? undefined}
                        ticker={r.ticker}
                        format={(v) => formatCompactNumber(v, locale)}
                      />,
                    )}
                  </td>
                )}
                {vis('ev_ebitda') && (
                  <td style={TD}>
                    {mc(
                      <SourcedNumber
                        value={r.ev_ebitda}
                        source={r.sources?.ev_ebitda ?? undefined}
                        ticker={r.ticker}
                        format={(v) => `${formatNumber(v, locale, 1)}×`}
                      />,
                    )}
                  </td>
                )}
                {vis('pe') && (
                  <td style={TD}>
                    {mc(
                      <SourcedNumber
                        value={r.pe}
                        source={r.sources?.pe ?? undefined}
                        ticker={r.ticker}
                        format={(v) => `${formatNumber(v, locale, 1)}×`}
                      />,
                    )}
                  </td>
                )}
                {vis('verdict') && (
                  <td style={{ ...TD, textAlign: 'center' }}>
                    {r.latest_verdict ? (
                      <span
                        style={{
                          color: VERDICT_COLOR[r.latest_verdict] ?? 'var(--text-secondary)',
                          fontWeight: 700,
                          fontSize: 11,
                          letterSpacing: '0.05em',
                        }}
                      >
                        {r.latest_verdict}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>{t('coverage.notRun')}</span>
                    )}
                  </td>
                )}
                {vis('upside') && (
                  <td style={{ ...TD, color: changeColor(r.upside_to_target_live) }}>
                    {mc(
                      <SourcedNumber
                        value={r.upside_to_target_live}
                        source={r.sources?.upside_to_target_live ?? undefined}
                        ticker={r.ticker}
                        format={(v) => formatPercent(v, locale, 1)}
                      />,
                    )}
                  </td>
                )}
                {vis('signal') && (
                  <td style={{ ...TD, textAlign: 'center' }}>
                    {mc(
                      r.signal ? (
                        <span title={r.signal} style={{ color: SIGNAL_COLOR[r.signal] }}>
                          ●
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-dim)' }}>—</span>
                      ),
                    )}
                  </td>
                )}
                {vis('runs') && <td style={TD}>{r.run_count > 0 ? r.run_count : '—'}</td>}
                {vis('status') && (
                  <td style={{ ...TD, textAlign: 'center' }}>
                    <StatusCell row={r} />
                  </td>
                )}
                <td style={{ ...TD, textAlign: 'center' }}>
                  <button
                    type="button"
                    onClick={() => onRunOne(r.ticker)}
                    title={t('coverage.runOne')}
                    style={{
                      background: 'var(--primary-soft)',
                      border: '1px solid var(--border-soft)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--primary)',
                      cursor: 'pointer',
                      fontSize: 11,
                      padding: '3px 8px',
                    }}
                  >
                    {t('coverage.run')}
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// Status cell: an in-flight run, a failed run, refresh reasons, or warnings —
// whichever is most pressing — always inline-visible (no hover-only state).
function StatusCell({ row }: { row: CoverageRow }): React.ReactElement {
  const { t } = useI18n()
  if (row.run_status === 'running' || row.run_status === 'created') {
    return (
      <span title={t('coverage.running')} style={{ color: 'var(--accent-cyan)', fontSize: 11 }}>
        ● {t('coverage.running')}
      </span>
    )
  }
  const reasons = row.needs_refresh
  const warnings = row.warnings
  if (reasons.length === 0 && warnings.length === 0) {
    return <span style={{ color: 'var(--text-dim)' }}>—</span>
  }
  const tip = [...reasons.map((r) => r.detail), ...warnings].join('\n')
  const isError = row.run_status === 'failed'
  return (
    <span
      title={tip}
      style={{
        color: isError ? 'var(--danger)' : 'var(--warning)',
        cursor: 'help',
        fontSize: 12,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 3,
      }}
    >
      <WarnTriangle color={isError ? 'var(--danger)' : 'var(--warning)'} />
      {reasons.length + warnings.length}
    </span>
  )
}

// Fast-skeleton placeholder for a pending market cell — reuses the global
// `.skeleton` shimmer so "loading" is visually distinct from "—" (missing).
function CellShimmer(): React.ReactElement {
  return (
    <span
      className="skeleton"
      role="img"
      aria-label="loading"
      style={{ display: 'inline-block', width: 40, height: 11, verticalAlign: 'middle' }}
    />
  )
}

// Active-column sort direction caret. Inline SVG (cosmic spec: simple icons
// hand-drawn); renders nothing on inactive columns so headers don't jitter.
function SortCaret({ dir }: { dir?: SortDir }): React.ReactElement | null {
  if (!dir) return null
  return (
    <svg width="8" height="8" viewBox="0 0 8 8" role="img" aria-hidden style={{ flexShrink: 0 }}>
      <path d={dir === 'asc' ? 'M4 1 L7 6 L1 6 Z' : 'M1 2 L7 2 L4 7 Z'} fill="var(--primary)" />
    </svg>
  )
}

function WarnTriangle({ color }: { color: string }): React.ReactElement {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 16 16"
      role="img"
      aria-label="warning"
      style={{ flexShrink: 0 }}
    >
      <path
        d="M8 2 L14.5 13.5 H1.5 Z"
        fill="none"
        stroke={color}
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <line
        x1="8"
        y1="6.2"
        x2="8"
        y2="9.6"
        stroke={color}
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="8" cy="11.4" r="0.85" fill={color} />
    </svg>
  )
}
