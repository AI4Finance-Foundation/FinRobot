import RevenueEbitdaChart from '../../../components/charts/RevenueEbitdaChart'
import MarginTrendChart from '../../../components/charts/MarginTrendChart'
import CashFlowChart from '../../../components/charts/CashFlowChart'
import EpsTrendChart from '../../../components/charts/EpsTrendChart'
import {
  historicalToRevenueEbitdaData,
  historicalToMarginData,
  historicalToCashFlowData,
  historicalToEpsData,
  dcfResultToRevenueEbitdaData,
  dcfResultToMarginData,
} from '../../../utils/chartAdapters'
import type { DCFResult } from '../../../types/finance'
import { useHistoricalData } from '../../../hooks/useHistoricalData'
import { useI18n } from '../../../i18n'
import { TermTip } from '../../../components/TermTip'
import { formatCompactNumber } from '../../../utils/format'
import { Chapter, KvGrid, SubChapter, tableStyle, type KvCell } from './ChapterBase'
import type { NumberSource } from '../../../components/SourcedNumber'
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
  const { t, locale } = useI18n()
  // Locale-aware compact currency: en → $1.23B / $4.5M, zh → $1.23 亿 / $4500 万.
  // Mirrors the `$` + formatCompactNumber convention used in ChapterOwnershipGovernance.
  const fmtMoney = (v: number): string => `$${formatCompactNumber(v, locale)}`
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

  // Provenance for the TTM income figures: provider + fetch time from the
  // captured snapshot, so each KV number is hover-traceable (数字可溯源).
  const provenance = rawData?.provenance as { provider?: string | null } | undefined
  const fetchedAt = rawData?.timestamp as string | undefined
  const provider = provenance?.provider ?? (rawData?.data_source as string | undefined)
  const numberSource: NumberSource | undefined =
    provider || fetchedAt ? { provider: provider ?? undefined, fetched_at: fetchedAt } : undefined

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
  // Only render EPS when at least one year actually carries a number.
  const epsChartData = (historical ? historicalToEpsData(historical) : []).filter(
    (r) => r.eps != null,
  )

  const candidateCells: (KvCell | false)[] = [
    baseRev !== null && {
      label: t('chapter.financial.kv.revenueBase'),
      value: fmtMoney(baseRev),
      delta: rawData?.fiscal_period_end
        ? `FY${String(rawData.fiscal_period_end).slice(0, 4)}`
        : undefined,
      source: numberSource,
    },
    baseEbitda !== null && {
      // EBITDA itself isn't in the glossary, but FCF (below, in the forecast
      // table) is the headline cash term — wrap the first FCF occurrence there.
      label: 'EBITDA',
      value: fmtMoney(baseEbitda),
      source: numberSource,
    },
    baseNet !== null && {
      label: t('chapter.financial.kv.netIncome'),
      value: fmtMoney(baseNet),
      source: numberSource,
    },
  ]
  const cells = candidateCells.filter((c): c is KvCell => c !== false)

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

      {epsChartData.length > 0 && (
        <SubChapter heading={t('chapter.financial.subheading.eps')}>
          <EpsTrendChart data={epsChartData} title={t('chapter.financial.chart.title.eps')} />
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
                <th style={thStyle}>{t('chapter.financial.table.unit')}</th>
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
                    {fmtMoney(v)}
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
                      {fmtMoney(v)}
                    </td>
                  ))}
                </tr>
              )}
              {dcf.projected_fcf && dcf.projected_fcf.length > 0 && (
                <tr>
                  <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                    <TermTip term="FCF">{t('chapter.financial.table.fcf')}</TermTip>
                  </td>
                  {dcf.projected_fcf.map((v, i) => (
                    <td
                      key={`fcf-${i}`}
                      style={{ ...tdStyle, textAlign: 'right', color: 'var(--accent-cyan)' }}
                    >
                      {fmtMoney(v)}
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
  background: 'var(--bg-card-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
