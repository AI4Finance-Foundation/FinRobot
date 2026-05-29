import RevenueEbitdaChart from '../../../components/charts/RevenueEbitdaChart'
import MarginTrendChart from '../../../components/charts/MarginTrendChart'
import CashFlowChart from '../../../components/charts/CashFlowChart'
import {
  historicalToRevenueEbitdaData,
  historicalToMarginData,
  historicalToCashFlowData,
  dcfResultToRevenueEbitdaData,
  dcfResultToMarginData,
} from '../../../utils/chartAdapters'
import type { DCFResult } from '../../../stores/appStore'
import { useHistoricalData } from '../../../hooks/useHistoricalData'
import { useI18n } from '../../../i18n'
import { Chapter, KvGrid, SubChapter, tableStyle } from './ChapterBase'
import type { DcfShape } from './types'

interface ChapterFinancialAnalysisProps {
  ticker: string
  dcf: DcfShape | null
  rawData: Record<string, unknown> | null
}

export function ChapterFinancialAnalysis({
  ticker,
  dcf,
  rawData,
}: ChapterFinancialAnalysisProps): React.ReactElement {
  const { t } = useI18n()
  const { data: historical } = useHistoricalData(ticker)
  // raw_data is FinancialData.model_dump() — the money line items live under
  // `income.*`, NOT at the top level (the sibling ChapterFinancialData reads
  // `data['income']` the same way). Reading the top level silently blanked the
  // EBITDA / net-income / FCF cards and degraded the revenue card to the DCF
  // base-year fallback instead of the real TTM income statement.
  const income = rawData?.income as Record<string, unknown> | undefined
  const baseRev = (income?.revenue as number | undefined) ?? dcf?.inputs?.revenue_base ?? null
  const baseEbitda = (income?.ebitda as number | undefined) ?? null
  const baseNet = (income?.net_income as number | undefined) ?? null
  const fcfTtm = (income?.fcf_ttm as number | undefined) ?? null

  const hasDcfForecast =
    dcf?.projected_revenue != null &&
    dcf.projected_revenue.length > 0 &&
    dcf.projected_ebitda != null &&
    dcf.projected_ebitda.length > 0 &&
    dcf.inputs?.revenue_base != null &&
    dcf.inputs?.ebitda_margin != null

  const revenueChartData = (() => {
    const hist = historical ? historicalToRevenueEbitdaData(historical) : []
    if (hasDcfForecast) {
      const fcst = dcfResultToRevenueEbitdaData(dcf as unknown as DCFResult)
      return [...hist, ...fcst.slice(1)]
    }
    return hist
  })()

  const marginChartData = (() => {
    const hist = historical ? historicalToMarginData(historical) : []
    if (hasDcfForecast) {
      const fcst = dcfResultToMarginData(dcf as unknown as DCFResult)
      return [...hist, ...fcst.slice(1)]
    }
    return hist
  })()

  const cashFlowChartData = historical ? historicalToCashFlowData(historical) : []

  const cells = [
    baseRev !== null && {
      label: t('chapter.financial.kv.revenueBase'),
      value: fmtBillions(baseRev),
      delta: rawData?.fiscal_period_end
        ? `FY${String(rawData.fiscal_period_end).slice(0, 4)}`
        : undefined,
    },
    baseEbitda !== null && { label: 'EBITDA', value: fmtBillions(baseEbitda) },
    baseNet !== null && {
      label: t('chapter.financial.kv.netIncome'),
      value: fmtBillions(baseNet),
    },
    fcfTtm !== null && {
      label: t('chapter.financial.kv.fcfTtm'),
      value: fmtBillions(fcfTtm),
    },
  ].filter((c): c is { label: string; value: string; delta?: string } => c !== false)

  return (
    <Chapter id="financial">
      {cells.length > 0 && <KvGrid cells={cells} columns={4} />}

      {revenueChartData.length > 0 && (
        <SubChapter heading={t('chapter.financial.subheading.revenueEbitda')}>
          <RevenueEbitdaChart
            data={revenueChartData}
            title={t('chapter.financial.chart.title.revenueEbitda')}
          />
        </SubChapter>
      )}

      {marginChartData.length > 0 && (
        <SubChapter heading={t('chapter.financial.subheading.marginTrend')}>
          <MarginTrendChart
            data={marginChartData}
            title={t('chapter.financial.chart.title.margin')}
          />
        </SubChapter>
      )}

      {cashFlowChartData.length > 0 && (
        <SubChapter heading={t('chapter.financial.subheading.cashFlow')}>
          <CashFlowChart
            data={cashFlowChartData}
            title={t('chapter.financial.chart.title.cashFlow')}
          />
        </SubChapter>
      )}

      {dcf?.projected_revenue && dcf.projected_revenue.length > 0 && (
        <SubChapter heading={t('chapter.financial.subheading.dcfForecast')}>
          <table style={tableStyle}>
            <thead style={{ background: 'var(--bg-elevated)' }}>
              <tr>
                <th style={thStyle}>$B</th>
                {dcf.projected_revenue.map((_, i) => (
                  <th key={`year-${i}`} style={thStyle}>
                    {t('chapter.financial.table.yearPlus', { n: i + 1 })}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                  {t('chapter.financial.table.revenue')}
                </td>
                {dcf.projected_revenue.map((v, i) => (
                  <td key={`rev-${i}`} style={{ ...tdStyle, textAlign: 'right' }}>
                    {fmtBillions(v)}
                  </td>
                ))}
              </tr>
              {dcf.projected_ebitda && dcf.projected_ebitda.length > 0 && (
                <tr>
                  <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                    EBITDA
                  </td>
                  {dcf.projected_ebitda.map((v, i) => (
                    <td key={`ebitda-${i}`} style={{ ...tdStyle, textAlign: 'right' }}>
                      {fmtBillions(v)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.projected_fcf && dcf.projected_fcf.length > 0 && (
                <tr>
                  <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                    {t('chapter.financial.table.fcf')}
                  </td>
                  {dcf.projected_fcf.map((v, i) => (
                    <td
                      key={`fcf-${i}`}
                      style={{ ...tdStyle, textAlign: 'right', color: 'var(--accent-cyan)' }}
                    >
                      {fmtBillions(v)}
                    </td>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
          <p
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-dim)',
              marginTop: 6,
              letterSpacing: '0.04em',
            }}
          >
            {t('chapter.financial.table.source')}
          </p>
        </SubChapter>
      )}

      {cells.length === 0 && !dcf?.projected_revenue && (
        <p style={emptyMsg}>{t('chapter.financial.empty')}</p>
      )}
    </Chapter>
  )
}

function fmtBillions(v: number): string {
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  return `$${v.toFixed(0)}`
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
const emptyMsg: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'rgba(15, 15, 34, 0.5)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
