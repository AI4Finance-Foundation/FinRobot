import PeerComparisonChart from '../../../components/charts/PeerComparisonChart'
import CompanyRadarChart from '../../../components/charts/CompanyRadarChart'
import { compsResultToPeerChartData, compsResultToRadarData } from '../../../utils/chartAdapters'
import type { CompsResult } from '../../../types/finance'
import { useI18n } from '../../../i18n'
import { TermTip } from '../../../components/TermTip'
import { MarkdownLite } from '../../../components/MarkdownLite'
import { formatCurrencyCompact } from '../../../utils/format'
import { Chapter, Narrative, SubChapter, TableScroll, tableStyle } from './ChapterBase'
import type { PeerCompsShape, ThesisShape } from './types'

interface ChapterCompetitiveProps {
  peers: PeerCompsShape | null
  thesis: ThesisShape | null
  // Balance-sheet financial (bank / insurer): lead the multiples on P/B, not
  // EV/EBITDA (a category error for deposit-takers). Persisted as
  // ValuationSynthesis.financial_sector. Undefined on the standalone comps tool
  // page (treated as non-bank).
  financialSector?: boolean
}

export function ChapterCompetitive(props: ChapterCompetitiveProps): React.ReactElement {
  return (
    <Chapter id="competitive">
      <CompetitiveBody {...props} />
    </Chapter>
  )
}

/** The peer-comps content WITHOUT the numbered <Chapter> chrome, so the standalone
 * comps tool page (CompactArtifactViewer) reuses the exact same peer table + heat
 * shading + medians + charts under its own section header. `thesis` is null on a
 * standalone comps artifact, so the competitor-analysis narrative simply omits. */
export function CompetitiveBody({
  peers,
  thesis,
  financialSector,
}: ChapterCompetitiveProps): React.ReactElement {
  const { t, locale } = useI18n()
  const isBank = financialSector === true
  const narrative = thesis?.competitor_analysis ?? null
  const target = peers?.target
  const peerList = (peers?.peers ?? []).filter((p) => !target || p.ticker !== target.ticker)
  const all = target ? [target, ...peerList] : peerList

  // Heat-shading reference = the SAME median the page advertises per column, so a
  // cell's green/red can never contradict the stated "Peer median" line or the
  // radar beside it.
  //  • Multiples (P/E · core P/E · EV/EBITDA): the BACKEND median (peers.median_*),
  //    which applies the NM-cap (drops P/E>75 etc.). A frontend re-median over all
  //    visible peers diverged (uncapped P/E 83.6 vs the advertised 43.1), shading
  //    a mid-range peer green while it sat ABOVE the stated median. No frontend
  //    fallback — if the backend median is absent the column is simply un-shaded.
  //  • Margins (gross · op): no backend median + no NM-cap → a frontend median over
  //    ≥3 visible peers is both consistent and stable.
  const marginsStable = peerList.length >= 3
  const med = {
    pe: peers?.median_pe ?? null,
    corePe: peers?.median_core_pe ?? null,
    // The primary multiple column: P/B for banks, EV/EBITDA otherwise.
    primary: isBank ? (peers?.median_pb ?? null) : (peers?.median_ev_ebitda ?? null),
    gross: marginsStable ? peerMedian(peerList.map((p) => p.gross_margin)) : null,
    opMargin: marginsStable ? peerMedian(peerList.map((p) => p.operating_margin)) : null,
  }

  // No fitting i18n key for the NOPAT-core caliber — inline literal per the
  // VersionDiffBanner precedent (do not touch .po in this task). The comps
  // price target (football-field "Comps (core P/E)") is computed on this core
  // median, so surfacing it here lets an analyst reconcile target ↔ table.
  const coreLabel =
    locale === 'zh'
      ? {
          header: '核心 P/E',
          tooltip:
            'NOPAT 核心盈利口径 P/E（市值 / NOPAT），剔除非经营性损益。Comps 估值目标用同业核心 P/E 中位数计算，与此列对齐。',
          medianPrefix: '核心 P/E',
        }
      : {
          header: 'Core P/E',
          tooltip:
            'NOPAT core-earnings P/E (market cap / NOPAT), stripping non-operating items. The Comps price target uses the peer core-P/E median, so it reconciles with this column.',
          medianPrefix: 'Core P/E',
        }

  const compsForCharts: CompsResult | null =
    target && peerList.length > 0
      ? ({
          target,
          peers: peerList,
          median_ev_ebitda: peers?.median_ev_ebitda ?? null,
          median_pb: peers?.median_pb ?? null,
          median_pe: peers?.median_pe ?? null,
          median_ev_revenue: peers?.median_ev_revenue ?? null,
          mean_ev_ebitda: null,
          mean_pe: null,
          peer_justification: peers?.peer_justification ?? '',
          positioning_narrative: peers?.positioning_narrative ?? '',
        } as unknown as CompsResult)
      : null
  const peerBarData = compsForCharts ? compsResultToPeerChartData(compsForCharts) : []
  const radarData = compsForCharts ? compsResultToRadarData(compsForCharts) : []

  return (
    <>
      {narrative && (
        <Narrative>
          <MarkdownLite text={narrative} />
        </Narrative>
      )}

      {all.length > 0 ? (
        <TableScroll>
          <table style={tableStyle}>
            <thead style={{ background: 'var(--bg-elevated)' }}>
              <tr>
                <th style={thStyle}>{t('chapter.competitive.col.ticker')}</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>
                  {t('chapter.competitive.col.revenue')}
                </th>
                <th style={{ ...thStyle, textAlign: 'right' }}>
                  <TermTip term="P/E" />
                </th>
                {/* Core P/E keeps its bespoke comps-reconciliation gloss (the
                  football-field "Comps (core P/E)" target is computed on this
                  column's median). TermTip supplies the standard hover + "ask
                  FinRobot" deep dive; the inline `title` stays as a quick
                  reconciliation hint that the tooltip text spells out. */}
                <th
                  style={{ ...thStyle, textAlign: 'right', cursor: 'help' }}
                  title={coreLabel.tooltip}
                >
                  <TermTip term="Core P/E">{coreLabel.header}</TermTip>
                </th>
                <th style={{ ...thStyle, textAlign: 'right' }}>
                  <TermTip term={isBank ? 'P/B' : 'EV/EBITDA'} />
                </th>
                <th style={{ ...thStyle, textAlign: 'right' }}>
                  {t('chapter.competitive.col.grossMargin')}
                </th>
                <th style={{ ...thStyle, textAlign: 'right' }}>
                  {t('chapter.competitive.col.opMargin')}
                </th>
              </tr>
            </thead>
            <tbody>
              {all.map((c, i) => {
                const isTarget = i === 0 && target !== undefined
                const primaryMult = isBank ? (c.pb_ratio ?? null) : c.ev_ebitda
                const h = {
                  pe: heat(c.pe_ratio, med.pe, true),
                  corePe: heat(c.core_pe_ratio, med.corePe, true),
                  ev: heat(primaryMult, med.primary, true),
                  gross: heat(c.gross_margin, med.gross, false),
                  op: heat(c.operating_margin, med.opMargin, false),
                }
                return (
                  <tr
                    key={`${isTarget ? 'target' : 'peer'}:${c.ticker}:${i}`}
                    // Bloomberg EQRV "subject row": the target gets a thick cyan
                    // left rail (on top of the existing faint cyan tint) so it is
                    // instantly separable from the peers below it. data-target lets
                    // the test assert the marker without coupling to inline colors.
                    data-target={isTarget ? '' : undefined}
                    style={
                      isTarget
                        ? {
                            background: 'color-mix(in srgb, var(--accent-cyan) 6%, transparent)',
                            boxShadow: 'inset 3px 0 0 0 var(--accent-cyan)',
                          }
                        : undefined
                    }
                  >
                    <td
                      style={{
                        ...tdStyle,
                        color: isTarget ? 'var(--accent-cyan)' : 'var(--text-primary)',
                        fontWeight: 500,
                      }}
                    >
                      {c.ticker}
                      {c.name && (
                        <span
                          style={{
                            marginLeft: 8,
                            color: 'var(--text-muted)',
                            fontSize: 11,
                            fontWeight: 300,
                          }}
                        >
                          {c.name}
                        </span>
                      )}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>
                      {/* Canonical USD: the comps pipeline FX-normalizes BOTH the
                        target and every peer to USD before computing multiples
                        (fx_normalize.normalize_company_to_usd sets
                        reporting_currency='USD'), so this column is USD even for
                        a TWD-reporting ADR target. We pass 'USD' explicitly
                        rather than the report's reporting_currency, which would
                        mislabel the normalized values (BUG-030). */}
                      {formatCurrencyCompact(c.revenue, 'USD', locale)}
                    </td>
                    <td
                      style={{ ...tdStyle, textAlign: 'right', ...h.pe.style }}
                      title={h.pe.title}
                    >
                      {c.pe_ratio !== null && c.pe_ratio !== undefined
                        ? c.pe_ratio.toFixed(1)
                        : '—'}
                    </td>
                    <td
                      style={{
                        ...tdStyle,
                        textAlign: 'right',
                        color: 'var(--accent-cyan)',
                        ...h.corePe.style,
                      }}
                      title={h.corePe.title}
                    >
                      {c.core_pe_ratio !== null && c.core_pe_ratio !== undefined
                        ? c.core_pe_ratio.toFixed(1)
                        : '—'}
                    </td>
                    <td
                      style={{ ...tdStyle, textAlign: 'right', ...h.ev.style }}
                      title={h.ev.title}
                    >
                      {primaryMult !== null && primaryMult !== undefined
                        ? primaryMult.toFixed(1)
                        : '—'}
                    </td>
                    <td
                      style={{ ...tdStyle, textAlign: 'right', ...h.gross.style }}
                      title={h.gross.title}
                    >
                      {c.gross_margin != null ? (c.gross_margin * 100).toFixed(1) + '%' : '—'}
                    </td>
                    <td
                      style={{ ...tdStyle, textAlign: 'right', ...h.op.style }}
                      title={h.op.title}
                    >
                      {c.operating_margin != null
                        ? (c.operating_margin * 100).toFixed(1) + '%'
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </TableScroll>
      ) : (
        <p style={mutedNote}>{t('chapter.competitive.empty')}</p>
      )}

      {/* Heat-shading legend — describes EXACTLY what heat() does so the green/red
        tints read without a manual: green = the company is cheaper (lower
        multiple) OR stronger (higher margin) than the peer median; red = richer /
        weaker; the ±5% deadband shows no tint. The first chip mirrors the target
        row's left accent so the "subject row" marker is self-explaining too. */}
      {all.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 14,
            marginTop: 8,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          <span>{t('chapter.competitive.heat.label')}</span>
          <HeatSwatch color="var(--success)" label={t('chapter.competitive.heat.favorable')} />
          <HeatSwatch color="var(--danger)" label={t('chapter.competitive.heat.unfavorable')} />
          <span>{t('chapter.competitive.heat.inline')}</span>
        </div>
      )}

      {med.pe != null || med.corePe != null || med.primary != null ? (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-muted)',
            marginTop: 6,
          }}
        >
          {t('chapter.competitive.peerMedian')}
          {peers?.median_pe != null && (
            <span style={{ marginLeft: 10, color: 'var(--text-secondary)' }}>
              P/E {peers.median_pe.toFixed(1)}
            </span>
          )}
          {peers?.median_core_pe != null && (
            <span
              style={{ marginLeft: 10, color: 'var(--accent-cyan)', cursor: 'help' }}
              title={coreLabel.tooltip}
            >
              {coreLabel.medianPrefix} {peers.median_core_pe.toFixed(1)}
            </span>
          )}
          {med.primary != null && (
            <span style={{ marginLeft: 10, color: 'var(--text-secondary)' }}>
              {isBank ? 'P/B' : 'EV/EBITDA'} {med.primary.toFixed(1)}
            </span>
          )}
        </p>
      ) : null}

      {isBank && all.length > 0 && (
        <p style={caliberNote}>
          {locale === 'zh'
            ? '银行口径 comps:用 P/B 与 P/E。对存款机构而言 EV/EBITDA 是口径错误——存款是经营性原料而非资本结构,且无干净 EBITDA。'
            : 'Bank-caliber comps: led on P/B and P/E. EV/EBITDA is a category error for a deposit-funded institution — deposits are operating raw material, not capital structure, and there is no clean EBITDA.'}
        </p>
      )}

      {peerBarData.length > 0 && (
        <SubChapter heading={t('chapter.competitive.subheading.multiples')}>
          <PeerComparisonChart
            data={peerBarData}
            title={t('chapter.competitive.chart.multiples')}
            // Banks: primary bar = P/B (EV/EBITDA is a category error for them).
            primaryKey={isBank ? 'pb_ratio' : 'ev_ebitda'}
            primaryName={isBank ? 'P/B' : undefined}
          />
        </SubChapter>
      )}

      {/* Radar profiles a company on margins + multiples; for a bank the margin
          axes are undefined (no COGS) and EV/EBITDA is a category error, leaving
          too few valid axes — the P/B + P/E table above carries the comparison. */}
      {!isBank && radarData.length > 0 && (
        <SubChapter heading={t('chapter.competitive.subheading.profile')}>
          <CompanyRadarChart data={radarData} title={t('chapter.competitive.chart.radar')} />
        </SubChapter>
      )}

      {peers?.positioning_narrative && (
        <SubChapter heading={t('chapter.competitive.subheading.positioning')}>
          <MarkdownLite
            text={peers.positioning_narrative}
            style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)' }}
          />
        </SubChapter>
      )}
    </>
  )
}

// One legend chip: a small color swatch + its meaning. Inline SVG swatch (a
// rounded rect filled with the same token the heat() background uses) keeps the
// legend visually matched to the cells without an animation or new token.
function HeatSwatch({ color, label }: { color: string; label: string }): React.ReactElement {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <svg width={14} height={14} viewBox="0 0 14 14" aria-hidden role="presentation">
        <rect x={1} y={1} width={12} height={12} rx={3} fill={color} opacity={0.85} />
      </svg>
      {label}
    </span>
  )
}

const thStyle: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontWeight: 500,
  fontSize: 10.5,
  color: 'var(--secondary)',
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  borderBottom: '1px solid var(--border-soft)',
}
const tdStyle: React.CSSProperties = {
  padding: '9px 14px',
  borderBottom: '1px solid var(--border-faint)',
  color: 'var(--text-secondary)',
  fontVariantNumeric: 'tabular-nums',
}
const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'var(--bg-card-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
// Calm caliber note (ChapterAuditBanner "note" tone): muted, no glow, no red — a
// structural fact (why this branch uses P/B, not a defect).
const caliberNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  color: 'var(--text-muted)',
  lineHeight: 1.6,
  margin: '10px 0 0',
  padding: '8px 12px',
  background: 'var(--bg-card-50)',
  borderLeft: '2px solid color-mix(in srgb, var(--secondary) 55%, transparent)',
  borderRadius: 'var(--radius-sm)',
}

// ── Comps heat-shading ──────────────────────────────────────────────────────
// Shade each numeric cell by its signed deviation from THIS table's peer median
// (computed over the visible peers, the same set the football-field comps target
// anchored on — "cite the computation"). Conventional comps read: lower multiple
// = cheaper = green; higher margin = better = green (涨绿跌红). Subtle by design —
// a scannability aid, never a verdict (the call lives on the cover).
function peerMedian(nums: Array<number | null | undefined>): number | null {
  const xs = nums.filter((n): n is number => typeof n === 'number' && Number.isFinite(n))
  if (xs.length === 0) return null
  const sorted = [...xs].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

interface HeatCell {
  style?: React.CSSProperties
  title?: string
}

// lowerFavorable: true for valuation multiples (cheaper = green), false for
// margins (higher = green). Deadband ±5% of median reads as "in line" (no tint).
function heat(
  value: number | null | undefined,
  med: number | null,
  lowerFavorable: boolean,
): HeatCell {
  if (value == null || !Number.isFinite(value) || med == null || med <= 0) return {}
  const dev = (value - med) / Math.abs(med)
  if (Math.abs(dev) < 0.05) return {}
  const favorable = lowerFavorable ? dev < 0 : dev > 0
  const intensity = Math.min(1, (Math.abs(dev) - 0.05) / 0.6)
  const alpha = Math.round(6 + intensity * 14) // 6%–20%
  return {
    style: {
      background: `color-mix(in srgb, ${favorable ? 'var(--success)' : 'var(--danger)'} ${alpha}%, transparent)`,
    },
    title: `${dev > 0 ? '+' : ''}${(dev * 100).toFixed(0)}% vs peer median`,
  }
}
