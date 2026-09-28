// DDM tool panel — the standalone Dividend Discount Model detail body. DDM has no
// dedicated report chapter (it only appears as a football-field method row in the
// full report), so this renders the DDMResult through the SAME shared primitives
// (MetricModule / SubChapter / tableStyle) the report chapters use, giving the tool
// page investment-bank-grade typography instead of a raw K-V dump. Every projected
// year renders (no silent truncation). Strings are inline bilingual literals (the
// ChapterCompetitive `coreLabel` precedent) — no new .po keys in this slice.

import { useI18n } from '../../../i18n'
import { TermTip } from '../../../components/TermTip'
import { formatCurrency, formatPercent } from '../../../utils/format'
import { SubChapter, TableScroll, tableStyle } from './ChapterBase'
import { MetricModule, type MetricCell } from './MetricModule'
import type { DdmShape } from './types'

export function DdmBody({
  ddm,
  // DDM per-share values are quote-currency; standalone pipelines FX-normalize to
  // USD before seeding, so this is USD for foreign issuers too.
  currency,
}: {
  ddm: DdmShape | null
  currency: string
}): React.ReactElement {
  const { locale } = useI18n()
  const L = (zh: string, en: string): string => (locale === 'zh' ? zh : en)
  const inputs = ddm?.inputs
  const value = ddm?.equity_value_per_share ?? null
  const current = inputs?.current_price ?? null
  const growth0 = inputs?.dividend_growth_rates?.[0] ?? null

  const spot = current != null ? formatCurrency(current, currency, locale, 2) : null
  const cells: MetricCell[] = [
    inputs?.dividend_per_share != null &&
      ({
        label: L('每股股利 (DPS)', 'Dividend / Share'),
        value: formatCurrency(inputs.dividend_per_share, currency, locale, 2),
      } as MetricCell),
    inputs?.payout_ratio != null &&
      ({
        label: L('派息率', 'Payout Ratio'),
        value: formatPercent(inputs.payout_ratio, locale),
      } as MetricCell),
    ddm?.cost_of_equity != null &&
      ({
        label: L('股权成本', 'Cost of Equity'),
        value: formatPercent(ddm.cost_of_equity, locale, 2),
        sub: inputs?.beta != null ? `β ${inputs.beta.toFixed(2)}` : undefined,
      } as MetricCell),
    growth0 != null &&
      ({
        label: L('首年股利增速', 'Y1 Dividend Growth'),
        value: formatPercent(growth0, locale),
      } as MetricCell),
    inputs?.terminal_growth_rate != null &&
      ({
        label: L('永续增长率', 'Terminal Growth'),
        value: formatPercent(inputs.terminal_growth_rate, locale, 2),
      } as MetricCell),
    ddm?.pv_dividends_total != null &&
      ({
        label: L('股利现值合计', 'PV of Dividends'),
        value: formatCurrency(ddm.pv_dividends_total, currency, locale, 2),
      } as MetricCell),
    ddm?.pv_terminal != null &&
      ({
        label: L('终值现值', 'PV of Terminal'),
        value: formatCurrency(ddm.pv_terminal, currency, locale, 2),
      } as MetricCell),
    ddm?.terminal_value != null &&
      ({
        label: L('终值', 'Terminal Value'),
        value: formatCurrency(ddm.terminal_value, currency, locale, 2),
      } as MetricCell),
    value != null &&
      ({
        label: L('每股价值', 'Value / Share'),
        value: formatCurrency(value, currency, locale, 2),
        tone: current != null ? (value >= current ? 'up' : 'down') : undefined,
        sub: spot != null ? L(`现价 ${spot}`, `spot ${spot}`) : undefined,
      } as MetricCell),
  ].filter((c): c is MetricCell => Boolean(c))

  const dividends = ddm?.projected_dividends ?? []
  const pvDividends = ddm?.pv_dividends ?? []

  return (
    <>
      {cells.length > 0 && (
        <MetricModule
          title={L('DDM 输入与每股价值', 'DDM Inputs & Value / Share')}
          accent="violet"
          columns={3}
          cells={cells}
        />
      )}

      {dividends.length > 0 && (
        <SubChapter heading={L('股利投影', 'Dividend Projection')}>
          <TableScroll>
            <table style={tableStyle}>
              <thead style={{ background: 'var(--bg-elevated)' }}>
                <tr>
                  <th style={thStyle}>{L('单位', 'Unit')}</th>
                  {dividends.map((_, i) => (
                    <th key={`y-${i}`} style={{ ...thStyle, textAlign: 'right' }}>
                      {L(`第 ${i + 1} 年`, `Y+${i + 1}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                    <TermTip term="DPS">{L('每股股利', 'Dividend / Share')}</TermTip>
                  </td>
                  {dividends.map((v, i) => (
                    <td key={`d-${i}`} style={{ ...tdStyle, textAlign: 'right' }}>
                      {formatCurrency(v, currency, locale, 2)}
                    </td>
                  ))}
                </tr>
                {pvDividends.length > 0 && (
                  <tr>
                    <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                      {L('股利现值', 'PV of Dividend')}
                    </td>
                    {pvDividends.map((v, i) => (
                      <td
                        key={`pv-${i}`}
                        style={{ ...tdStyle, textAlign: 'right', color: 'var(--accent-cyan)' }}
                      >
                        {formatCurrency(v, currency, locale, 2)}
                      </td>
                    ))}
                  </tr>
                )}
              </tbody>
            </table>
          </TableScroll>
        </SubChapter>
      )}
    </>
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
