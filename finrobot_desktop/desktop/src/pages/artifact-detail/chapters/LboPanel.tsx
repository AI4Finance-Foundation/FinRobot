// LBO tool panel — the standalone Leveraged Buyout detail body. LBO has no
// dedicated report chapter (it only appears as the football-field ability-to-pay
// row), so this renders the LBOResult through the SAME shared primitives
// (MetricModule / SubChapter / tableStyle) the report chapters use. Every schedule
// year and every sensitivity cell renders (no silent truncation). Strings are
// inline bilingual literals (the ChapterCompetitive `coreLabel` precedent).
//
// Degrades cleanly: when the lbo_calculation step failed (impossible capital
// structure → entry_ev / schedule null, the MU peak-EBITDA case), the entry/exit
// modules + schedule omit and a calm "did not resolve" note renders — the deal
// assumptions + compute warnings still surface elsewhere on the page, never a crash
// or an empty shell.

import { useI18n } from '../../../i18n'
import { formatCurrencyCompact, formatPercent } from '../../../utils/format'
import { SubChapter, TableScroll, tableStyle } from './ChapterBase'
import { MetricModule, type MetricCell } from './MetricModule'
import type { LboInputsShape, LboShape } from './types'

export function LboBody({
  lbo,
  inputs,
  // LBO figures are FX-normalized to USD by the standalone pipeline before seeding
  // (BUG-073 family), so this is USD for foreign issuers too.
  currency,
}: {
  lbo: LboShape | null
  inputs: LboInputsShape | null
  currency: string
}): React.ReactElement {
  const { locale } = useI18n()
  const L = (zh: string, en: string): string => (locale === 'zh' ? zh : en)
  const money = (v: number | null | undefined): string =>
    v == null ? '—' : formatCurrencyCompact(v, currency, locale)

  const resolved = lbo?.entry_ev != null && lbo?.entry_equity != null

  const entryCells: MetricCell[] = [
    lbo?.entry_ev != null &&
      ({ label: L('入场企业价值', 'Entry EV'), value: money(lbo.entry_ev) } as MetricCell),
    lbo?.entry_debt != null &&
      ({ label: L('入场债务', 'Entry Debt'), value: money(lbo.entry_debt) } as MetricCell),
    lbo?.entry_equity != null &&
      ({ label: L('入场股权', 'Entry Equity'), value: money(lbo.entry_equity) } as MetricCell),
    inputs?.leverage_multiple != null &&
      ({
        label: L('杠杆倍数', 'Leverage'),
        value: `${inputs.leverage_multiple.toFixed(1)}×`,
        sub: L('债务 / EBITDA', 'Debt / EBITDA'),
      } as MetricCell),
    inputs?.entry_ev_ebitda != null &&
      ({
        label: L('入场 EV/EBITDA', 'Entry EV/EBITDA'),
        value: `${inputs.entry_ev_ebitda.toFixed(1)}×`,
      } as MetricCell),
  ].filter((c): c is MetricCell => Boolean(c))

  const exitCells: MetricCell[] = [
    lbo?.exit_ebitda != null &&
      ({ label: L('退出 EBITDA', 'Exit EBITDA'), value: money(lbo.exit_ebitda) } as MetricCell),
    lbo?.exit_ev != null &&
      ({ label: L('退出企业价值', 'Exit EV'), value: money(lbo.exit_ev) } as MetricCell),
    lbo?.exit_equity != null &&
      ({ label: L('退出股权', 'Exit Equity'), value: money(lbo.exit_equity) } as MetricCell),
    inputs?.holding_period_years != null &&
      ({
        label: L('持有期', 'Holding Period'),
        value: L(`${inputs.holding_period_years} 年`, `${inputs.holding_period_years} yr`),
      } as MetricCell),
    inputs?.exit_ev_ebitda != null &&
      ({
        label: L('退出 EV/EBITDA', 'Exit EV/EBITDA'),
        value: `${inputs.exit_ev_ebitda.toFixed(1)}×`,
      } as MetricCell),
  ].filter((c): c is MetricCell => Boolean(c))

  const schedule = lbo?.schedule ?? []

  return (
    <>
      {entryCells.length > 0 && (
        <MetricModule title={L('入场', 'Entry')} accent="violet" columns={3} cells={entryCells} />
      )}
      {exitCells.length > 0 && (
        <MetricModule title={L('退出', 'Exit')} accent="cyan" columns={3} cells={exitCells} />
      )}

      {schedule.length > 0 && (
        <SubChapter heading={L('债务偿还计划', 'Debt Schedule')}>
          <TableScroll>
            <table style={tableStyle}>
              <thead style={{ background: 'var(--bg-elevated)' }}>
                <tr>
                  <th style={thStyle}>{L('年', 'Year')}</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>{L('营收', 'Revenue')}</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>EBITDA</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>FCF</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>{L('强制摊还', 'Mand. Amort')}</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>{L('现金清扫', 'Cash Sweep')}</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>{L('循环贷提取', 'Revolver')}</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>{L('期末债务', 'End Debt')}</th>
                </tr>
              </thead>
              <tbody>
                {schedule.map((y) => (
                  <tr key={`yr-${y.year}`}>
                    <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                      {y.year}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{money(y.revenue)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{money(y.ebitda)}</td>
                    <td
                      style={{
                        ...tdStyle,
                        textAlign: 'right',
                        color: y.fcf < 0 ? 'var(--danger)' : 'var(--accent-cyan)',
                      }}
                    >
                      {money(y.fcf)}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{money(y.mandatory_amort)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{money(y.cash_sweep_amount)}</td>
                    <td
                      style={{
                        ...tdStyle,
                        textAlign: 'right',
                        color: y.revolver_draw > 0 ? 'var(--warning)' : 'var(--text-secondary)',
                      }}
                    >
                      {money(y.revolver_draw)}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right', color: 'var(--text-primary)' }}>
                      {money(y.ending_debt)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </SubChapter>
      )}

      <LboSensitivity lbo={lbo} />

      {lbo?.capital_structure_warning && (
        <p style={disclosureNote}>{lbo.capital_structure_warning}</p>
      )}

      {!resolved && schedule.length === 0 && (
        <p style={mutedNote}>
          {L(
            'LBO 模型未收敛为可行的资本结构 — 见下方计算警告与下方的交易假设 / 溯源。',
            'The LBO model did not resolve to a feasible capital structure — see the compute warnings below plus the deal assumptions / provenance.',
          )}
        </p>
      )}
    </>
  )
}

/** IRR sensitivity matrix — entry EV/EBITDA rows × exit EV/EBITDA cols. Every cell
 * renders (no truncation); a cell is heat-shaded by its IRR (green high, red low). */
function LboSensitivity({ lbo }: { lbo: LboShape | null }): React.ReactElement | null {
  const { locale } = useI18n()
  const L = (zh: string, en: string): string => (locale === 'zh' ? zh : en)
  const sens = lbo?.sensitivity
  const entries = sens?.entry_multiples
  const exits = sens?.exit_multiples
  const grid = sens?.irr_grid
  if (!entries || !exits || !grid || entries.length === 0 || exits.length === 0) return null

  const flat = grid.flat().filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  const lo = flat.length ? Math.min(...flat) : 0
  const hi = flat.length ? Math.max(...flat) : 1

  return (
    <SubChapter
      heading={L('IRR 敏感性 (入场 × 退出 EV/EBITDA)', 'IRR Sensitivity (Entry × Exit EV/EBITDA)')}
    >
      <TableScroll>
        <table style={tableStyle}>
          <thead style={{ background: 'var(--bg-elevated)' }}>
            <tr>
              <th style={thStyle}>{L('入场 \\ 退出', 'Entry \\ Exit')}</th>
              {exits.map((x) => (
                <th key={`ex-${x}`} style={{ ...thStyle, textAlign: 'right' }}>
                  {x.toFixed(1)}×
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((en, i) => (
              <tr key={`en-${en}`}>
                <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                  {en.toFixed(1)}×
                </td>
                {exits.map((_, j) => {
                  const v = grid[i]?.[j]
                  const has = typeof v === 'number' && Number.isFinite(v)
                  return (
                    <td
                      key={`c-${i}-${j}`}
                      style={{
                        ...tdStyle,
                        textAlign: 'right',
                        background: has ? heatBg(v as number, lo, hi) : undefined,
                      }}
                    >
                      {has ? formatPercent(v as number, locale) : '—'}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </SubChapter>
  )
}

// Green (highest IRR) → red (lowest) shade, normalised across the grid. Subtle
// alpha, cosmic tokens only — a scannability aid, never a verdict.
function heatBg(v: number, lo: number, hi: number): string {
  if (hi <= lo) return 'transparent'
  const t = (v - lo) / (hi - lo) // 0 = worst, 1 = best
  const color = t >= 0.5 ? 'var(--success)' : 'var(--danger)'
  const intensity = Math.abs(t - 0.5) * 2 // 0 at midpoint, 1 at extremes
  const alpha = Math.round(4 + intensity * 16) // 4%–20%
  return `color-mix(in srgb, ${color} ${alpha}%, transparent)`
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
const disclosureNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  lineHeight: 1.7,
  color: 'var(--text-muted)',
  padding: '12px 16px',
  background: 'var(--bg-card-50)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  marginTop: 12,
}
const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'var(--bg-card-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  lineHeight: 1.6,
}
