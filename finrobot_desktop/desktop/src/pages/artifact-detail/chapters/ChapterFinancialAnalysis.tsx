import RevenueEbitdaChart from '../../../components/charts/RevenueEbitdaChart'
import MarginTrendChart from '../../../components/charts/MarginTrendChart'
import BankTrajectoryChart from '../../../components/charts/BankTrajectoryChart'
import CashFlowChart from '../../../components/charts/CashFlowChart'
import EpsTrendChart from '../../../components/charts/EpsTrendChart'
import {
  historicalToRevenueEbitdaData,
  historicalToMarginData,
  historicalToBankTrajectoryData,
  historicalToCashFlowData,
  historicalToEpsData,
  dcfResultToRevenueEbitdaData,
  dcfResultToMarginData,
} from '../../../utils/chartAdapters'
import type { DCFResult, HistoricalMetrics } from '../../../types/finance'
import { useI18n } from '../../../i18n'
import { formatCurrencyCompact } from '../../../utils/format'
import { Chapter, SubChapter } from './ChapterBase'
import { DcfForecastTable } from './DcfForecastTable'
import { ProfitWaterfall, type WaterfallRow } from './ProfitWaterfall'
import type { NumberSource } from '../../../components/SourcedNumber'
import type { DcfShape } from './types'

interface ChapterFinancialAnalysisProps {
  dcf: DcfShape | null
  rawData: Record<string, unknown> | null
  // Multi-year trend series, FROZEN into the artifact at generation time (read
  // from outputs.structured.historical_metrics via deriveReportData) — never a
  // live ['historical'] refetch. The narrative's growth/trend claims are
  // computed from these series, so a live refetch could drift the chart
  // endpoints out of sync with the frozen prose (new fiscal year / restatement).
  historicalMetrics: HistoricalMetrics | null
  // All amounts here are income-statement absolutes (revenue / EBITDA /
  // net income / projected FCF) → reporting currency (BUG-030).
  reportingCurrency: string
  // Balance-sheet financial (bank / insurer): EBITDA / EBITDA-margin are a
  // category error, so the branch hides them and renders a Revenue + Net Income
  // (+ ROE when equity is present) trajectory instead. Persisted as
  // ValuationSynthesis.financial_sector.
  financialSector?: boolean
}

export function ChapterFinancialAnalysis({
  dcf,
  rawData,
  historicalMetrics,
  reportingCurrency,
  financialSector,
}: ChapterFinancialAnalysisProps): React.ReactElement {
  const { t, locale } = useI18n()
  const isBank = financialSector === true
  // Currency-aware compact: en → $1.23B / $4.5M, zh → $1.23 亿; non-USD →
  // HK$1.23B / TWD 1.23B. Reporting currency (IS-caliber line items).
  const fmtMoney = (v: number): string => formatCurrencyCompact(v, reportingCurrency, locale)
  const historical = historicalMetrics
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

  // Bank-caliber trajectory (Revenue + Net Income + ROE) — replaces the
  // Revenue&EBITDA + margin charts for balance-sheet financials.
  const bankTrajectory = isBank && historical ? historicalToBankTrajectoryData(historical) : []

  const cashFlowChartData = historical ? historicalToCashFlowData(historical) : []
  // Only render EPS when at least one year actually carries a number.
  const epsChartData = (historical ? historicalToEpsData(historical) : []).filter(
    (r) => r.eps != null,
  )

  // Base-year profit cascade: revenue is the 100% reference; EBITDA / net income
  // render as nested proportional bars whose widths ARE their margins. Each row
  // appears only when present (mirrors the old per-cell omission), and a loss
  // (negative step) turns the bar red. Revenue carries the fiscal-year tag.
  const waterfallRows: WaterfallRow[] = []
  if (baseRev !== null) {
    waterfallRows.push({
      tone: 'rev',
      label: t('chapter.financial.kv.revenueBase'),
      value: fmtMoney(baseRev),
      raw: baseRev,
      source: numberSource,
      // baseRev (income.revenue) is a TTM figure (Σ latest 4 quarters, per
      // FinancialData.fiscal_period_end's backend contract), NOT an annual
      // report — `fiscal_period_end` is the TTM window's end date, so tagging
      // it "FY{year}" claimed a completed fiscal year that, mid-year, hasn't
      // happened yet (analysts read that as the 10-K figure).
      periodTag: rawData?.fiscal_period_end
        ? `TTM · ${String(rawData.fiscal_period_end).slice(0, 7)}`
        : undefined,
    })
  }
  // EBITDA is a category error for a deposit-taking financial — omit the row
  // (the bank branch renders Revenue + Net Income + ROE below instead).
  if (!isBank && baseEbitda !== null) {
    waterfallRows.push({
      tone: 'ebitda',
      label: 'EBITDA',
      value: fmtMoney(baseEbitda),
      raw: baseEbitda,
      source: numberSource,
    })
  }
  if (baseNet !== null) {
    waterfallRows.push({
      tone: 'net',
      label: t('chapter.financial.kv.netIncome'),
      value: fmtMoney(baseNet),
      raw: baseNet,
      source: numberSource,
    })
  }

  return (
    <Chapter id="financial">
      <ProfitWaterfall rows={waterfallRows} />

      {isBank && bankTrajectory.length > 0 && (
        <SubChapter
          heading={locale === 'zh' ? '营收 · 净利润 · ROE 轨迹' : 'Revenue · Net Income · ROE'}
        >
          <BankTrajectoryChart
            data={bankTrajectory}
            title={locale === 'zh' ? '营收 · 净利润 · ROE' : 'Revenue · Net Income · ROE'}
          />
          <p style={caliberNote}>
            {locale === 'zh'
              ? '银行口径:略去 EBITDA 与 EBITDA 利润率——对存款机构是口径错误(存款是经营性原料而非资本结构,且无干净 EBITDA)。盈利能力看净利润与 ROE。'
              : 'Bank caliber: EBITDA and EBITDA-margin are omitted — category errors for a deposit-funded institution (deposits are operating raw material, not capital structure, and there is no clean EBITDA). Profitability is read on Net Income and Return on Equity.'}
          </p>
        </SubChapter>
      )}

      {!isBank && revenueChartData.length > 0 && (
        <SubChapter heading={t('chapter.financial.subheading.revenueEbitda')}>
          <RevenueEbitdaChart
            data={revenueChartData}
            title={t('chapter.financial.chart.title.revenueEbitda')}
          />
        </SubChapter>
      )}

      {!isBank && marginChartData.length > 0 && (
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

      <DcfForecastTable dcf={dcf} reportingCurrency={reportingCurrency} />

      {waterfallRows.length === 0 && !dcf?.projected_revenue && (
        <p style={emptyMsg}>{t('chapter.financial.empty')}</p>
      )}
    </Chapter>
  )
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
// Calm caliber note (ChapterAuditBanner "note" tone): a structural fact (why the
// bank branch omits EBITDA), not a defect — muted, no glow, no red.
const caliberNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  color: 'var(--text-muted)',
  lineHeight: 1.6,
  margin: '8px 0 0',
  padding: '8px 12px',
  background: 'var(--bg-card-50)',
  borderLeft: '2px solid color-mix(in srgb, var(--secondary) 55%, transparent)',
  borderRadius: 'var(--radius-sm)',
}
