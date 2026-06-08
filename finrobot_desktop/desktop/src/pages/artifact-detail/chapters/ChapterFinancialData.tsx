// Chapter — Financial Data. Renders the audit-trail data captured at pipeline
// run time as analyst-friendly KV cards (income / balance / market / valuation).
// The original JSON blob is preserved as a collapsible "原始数据" details so
// developers can still verify the inputs without polluting the C-end surface.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { NumberSource } from '../../../components/SourcedNumber'
import { Chapter, KvGrid, SubChapter } from './ChapterBase'
import {
  formatDate,
  formatCompactNumber,
  formatCurrency,
  formatCurrencyCompact,
  formatNumber,
  formatPercent,
} from '../../../utils/format'
import { useI18n, type Locale } from '../../../i18n'
import { BASE_URL } from '../../../api/client'
import { fetchWithTimeout, HEAVY_API_TIMEOUT_MS } from '../../../api/fetch'
import { extractErrorDetail } from '../../../api/errors'

interface ChapterFinancialDataProps {
  rawData: Record<string, unknown> | null
  dataSource: string | null
  fetchedAt: string | null
  ticker: string
  // quote → market_cap & per-share prices (price, 52w hi/lo); reporting →
  // income / balance / EV absolutes (BUG-030).
  quoteCurrency: string
  reportingCurrency: string
}

interface EarningsCallTranscript {
  ticker: string
  quarter: number
  year: number
  date: string | null
  content: string
  summary: string | null
}

interface EarningsCallList {
  ticker: string
  transcripts: EarningsCallTranscript[]
}

interface IncomeShape {
  revenue?: number | null
  ebitda?: number | null
  net_income?: number | null
  gross_margin?: number | null
  operating_margin?: number | null
  depreciation_amortization?: number | null
  rd_expense?: number | null
  sga_expense?: number | null
  interest_expense?: number | null
}

interface BalanceShape {
  total_debt?: number | null
  total_cash?: number | null
}

interface MarketShape {
  market_cap?: number | null
  shares_outstanding?: number | null
  current_price?: number | null
  pe_ratio?: number | null
  price_52w_high?: number | null
  price_52w_low?: number | null
  industry?: string | null
  sector?: string | null
  beta?: number | null
}

interface ValuationShape {
  enterprise_value?: number | null
  ev_ebitda?: number | null
  ev_revenue?: number | null
}

type Cell = {
  label: string
  value: string
  delta?: string
  tone?: 'up' | 'down'
  source?: NumberSource
}

interface ProvenanceShape {
  provider?: string | null
}

function tr(zh: string, en: string, locale: Locale): string {
  return locale === 'en' ? en : zh
}

function buildCompanyCells(
  rawData: Record<string, unknown>,
  market: MarketShape,
  locale: Locale,
): Cell[] {
  const cells: Cell[] = []
  const ticker = rawData['ticker']
  const companyName = rawData['company_name']
  if (typeof ticker === 'string') {
    cells.push({ label: tr('股票代码', 'Ticker', locale), value: ticker })
  }
  if (typeof companyName === 'string') {
    cells.push({ label: tr('公司名称', 'Company', locale), value: companyName })
  }
  if (typeof market.sector === 'string' && market.sector) {
    cells.push({ label: tr('板块', 'Sector', locale), value: market.sector })
  }
  if (typeof market.industry === 'string' && market.industry) {
    cells.push({ label: tr('行业', 'Industry', locale), value: market.industry })
  }
  return cells
}

function buildIncomeCells(
  income: IncomeShape | undefined,
  locale: Locale,
  reportingCurrency: string,
  source?: NumberSource,
): Cell[] {
  if (!income) return []
  const cells: Cell[] = []
  const push = (key: keyof IncomeShape, label: string, mode: 'currency' | 'percent') => {
    const v = income[key]
    if (v === null || v === undefined) return
    if (mode === 'currency') {
      cells.push({
        label,
        value: formatCurrencyCompact(v as number, reportingCurrency, locale),
        source,
      })
    } else {
      cells.push({ label, value: formatPercent(v as number, locale), source })
    }
  }
  push('revenue', tr('营收', 'Revenue', locale), 'currency')
  push('ebitda', 'EBITDA', 'currency')
  push('net_income', tr('净利润', 'Net Income', locale), 'currency')
  push('gross_margin', tr('毛利率', 'Gross Margin', locale), 'percent')
  push('operating_margin', tr('经营利润率', 'Op Margin', locale), 'percent')
  push('depreciation_amortization', tr('折旧摊销', 'D&A', locale), 'currency')
  push('rd_expense', tr('研发费用', 'R&D', locale), 'currency')
  push('sga_expense', tr('销售管理费用', 'SG&A', locale), 'currency')
  push('interest_expense', tr('利息费用', 'Interest', locale), 'currency')
  return cells
}

function buildBalanceCells(
  balance: BalanceShape | undefined,
  market: MarketShape,
  locale: Locale,
  quoteCurrency: string,
  reportingCurrency: string,
  source?: NumberSource,
): Cell[] {
  const cells: Cell[] = []
  if (balance?.total_debt !== undefined && balance.total_debt !== null) {
    cells.push({
      label: tr('总负债', 'Total Debt', locale),
      // Balance-sheet absolute → reporting currency.
      value: formatCurrencyCompact(balance.total_debt, reportingCurrency, locale),
      source,
    })
  }
  if (balance?.total_cash !== undefined && balance.total_cash !== null) {
    cells.push({
      label: tr('现金', 'Total Cash', locale),
      value: formatCurrencyCompact(balance.total_cash, reportingCurrency, locale),
      source,
    })
  }
  if (market.market_cap !== undefined && market.market_cap !== null) {
    cells.push({
      label: tr('市值', 'Market Cap', locale),
      // Market cap is a quote-currency figure.
      value: formatCurrencyCompact(market.market_cap, quoteCurrency, locale),
      source,
    })
  }
  if (market.shares_outstanding !== undefined && market.shares_outstanding !== null) {
    cells.push({
      label: tr('总股本', 'Shares Out', locale),
      value: formatCompactNumber(market.shares_outstanding, locale),
      source,
    })
  }
  return cells
}

function buildValuationCells(
  market: MarketShape,
  valuation: ValuationShape | undefined,
  locale: Locale,
  quoteCurrency: string,
  reportingCurrency: string,
  source?: NumberSource,
): Cell[] {
  const cells: Cell[] = []
  if (market.current_price !== undefined && market.current_price !== null) {
    cells.push({
      label: tr('现价', 'Price', locale),
      // Per-share quote → quote currency.
      value: formatCurrency(market.current_price, quoteCurrency, locale, 2),
      source,
    })
  }
  if (market.pe_ratio !== undefined && market.pe_ratio !== null) {
    cells.push({
      label: 'P/E',
      value: `${formatNumber(market.pe_ratio, locale, 1)}x`,
      source,
    })
  }
  if (valuation?.enterprise_value !== undefined && valuation.enterprise_value !== null) {
    cells.push({
      label: 'EV',
      // EV is an absolute reporting-currency figure.
      value: formatCurrencyCompact(valuation.enterprise_value, reportingCurrency, locale),
      source,
    })
  }
  if (valuation?.ev_ebitda !== undefined && valuation.ev_ebitda !== null) {
    cells.push({
      label: 'EV/EBITDA',
      value: `${formatNumber(valuation.ev_ebitda, locale, 1)}x`,
      source,
    })
  }
  if (valuation?.ev_revenue !== undefined && valuation.ev_revenue !== null) {
    cells.push({
      label: 'EV/Revenue',
      value: `${formatNumber(valuation.ev_revenue, locale, 1)}x`,
      source,
    })
  }
  if (market.price_52w_high !== undefined && market.price_52w_high !== null) {
    cells.push({
      label: tr('52 周高', '52W High', locale),
      value: formatCurrency(market.price_52w_high, quoteCurrency, locale, 2),
      source,
    })
  }
  if (market.price_52w_low !== undefined && market.price_52w_low !== null) {
    cells.push({
      label: tr('52 周低', '52W Low', locale),
      value: formatCurrency(market.price_52w_low, quoteCurrency, locale, 2),
      source,
    })
  }
  if (market.beta !== undefined && market.beta !== null) {
    cells.push({
      label: 'Beta',
      value: formatNumber(market.beta, locale, 2),
      source,
    })
  }
  return cells
}

export function ChapterFinancialData({
  rawData,
  dataSource,
  fetchedAt,
  ticker,
  quoteCurrency,
  reportingCurrency,
}: ChapterFinancialDataProps): React.ReactElement {
  const { locale } = useI18n()
  const [showRaw, setShowRaw] = useState(false)
  const data = rawData ?? {}

  const income = data['income'] as IncomeShape | undefined
  const balance = data['balance'] as BalanceShape | undefined
  const market = (data['market'] as MarketShape | undefined) ?? {}
  const valuation = data['valuation'] as ValuationShape | undefined

  // Provenance for the snapshot's numbers: the provider that supplied them +
  // when they were fetched. `provenance.provider` (DataProvenance) is the
  // canonical source-of-truth; `dataSource` is the legacy top-level mirror.
  const provenance = data['provenance'] as ProvenanceShape | undefined
  const sourceProvider = provenance?.provider ?? dataSource ?? undefined
  const numberSource: NumberSource | undefined =
    sourceProvider || fetchedAt
      ? { provider: sourceProvider, fetched_at: fetchedAt ?? undefined }
      : undefined

  const companyCells = buildCompanyCells(data, market, locale)
  const incomeCells = buildIncomeCells(income, locale, reportingCurrency, numberSource)
  const balanceCells = buildBalanceCells(
    balance,
    market,
    locale,
    quoteCurrency,
    reportingCurrency,
    numberSource,
  )
  const valuationCells = buildValuationCells(
    market,
    valuation,
    locale,
    quoteCurrency,
    reportingCurrency,
    numberSource,
  )

  return (
    <Chapter id="data">
      {/* Provenance strip */}
      <div
        style={{
          display: 'flex',
          gap: 18,
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          marginBottom: 14,
          flexWrap: 'wrap',
        }}
      >
        <span>
          {tr('数据来源', 'DATA SOURCE', locale)}:{' '}
          <span style={{ color: 'var(--accent-cyan)' }}>
            {sourceProvider ?? tr('未知', 'unknown', locale)}
          </span>
        </span>
        {fetchedAt && (
          <span>
            {tr('抓取时间', 'FETCHED AT', locale)}:{' '}
            <span style={{ color: 'var(--text-secondary)' }}>
              {formatDate(fetchedAt, locale, 'datetime')}
            </span>
          </span>
        )}
      </div>

      {companyCells.length > 0 && (
        <SubChapter heading={tr('公司信息', 'Company', locale)}>
          <KvGrid cells={companyCells} columns={4} />
        </SubChapter>
      )}

      {incomeCells.length > 0 && (
        <SubChapter heading={tr('损益表', 'Income Statement', locale)}>
          <KvGrid cells={incomeCells} columns={4} />
        </SubChapter>
      )}

      {balanceCells.length > 0 && (
        <SubChapter heading={tr('资产负债', 'Balance Sheet', locale)}>
          <KvGrid cells={balanceCells} columns={4} />
        </SubChapter>
      )}

      {valuationCells.length > 0 && (
        <SubChapter heading={tr('估值倍数', 'Valuation Multiples', locale)}>
          <KvGrid cells={valuationCells} columns={4} />
        </SubChapter>
      )}

      <SubChapter heading={tr('财报电话会逐字稿', 'Earnings Call Transcripts', locale)}>
        <EarningsCallSection ticker={ticker} locale={locale} />
      </SubChapter>

      {companyCells.length === 0 &&
        incomeCells.length === 0 &&
        balanceCells.length === 0 &&
        valuationCells.length === 0 && (
          <p
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 12.5,
              color: 'var(--text-muted)',
              padding: '14px 18px',
              background: 'var(--surface-panel-50)',
              border: '1px dashed var(--border-soft)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            {tr(
              '该研报未保存原始数据快照，请重新生成研报以获得完整数据溯源。',
              'No raw data snapshot for this report — re-run to regenerate.',
              locale,
            )}
          </p>
        )}

      {/* Developer-only raw JSON, collapsed by default */}
      {Object.keys(data).length > 0 && (
        <div style={{ marginTop: 22 }}>
          <button
            type="button"
            onClick={() => setShowRaw((s) => !s)}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              background: 'transparent',
              border: '1px dashed var(--border-soft)',
              borderRadius: 4,
              padding: '5px 10px',
              cursor: 'pointer',
            }}
          >
            {showRaw
              ? tr('▼ 折叠原始 JSON', '▼ Hide raw JSON', locale)
              : tr('▶ 展开原始 JSON（开发者调试）', '▶ Show raw JSON (debug)', locale)}
          </button>
          {showRaw && (
            <pre
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10.5,
                color: 'var(--text-dim)',
                background: 'var(--surface-panel-60)',
                padding: 14,
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-soft)',
                marginTop: 8,
                overflow: 'auto',
                maxHeight: 480,
                lineHeight: 1.55,
              }}
            >
              {JSON.stringify(data, null, 2)}
            </pre>
          )}
        </div>
      )}
    </Chapter>
  )
}

function EarningsCallSection({
  ticker,
  locale,
}: {
  ticker: string
  locale: Locale
}): React.ReactElement {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['earnings-calls', ticker],
    queryFn: async () => {
      const resp = await fetchWithTimeout(
        `${BASE_URL}/api/data/${ticker}/earnings-calls?limit=8`,
        {},
        HEAVY_API_TIMEOUT_MS,
      )
      if (!resp.ok) {
        throw new Error(
          await extractErrorDetail(
            resp,
            tr('无法加载财报电话会逐字稿', 'Failed to load earnings call transcripts', locale),
          ),
        )
      }
      return resp.json() as Promise<EarningsCallList>
    },
    enabled: !!ticker,
    retry: false,
    staleTime: 60 * 60_000,
    gcTime: 24 * 60 * 60_000,
    refetchOnMount: false,
  })

  if (isError) {
    return (
      <p style={noteStyle}>
        {(error as Error)?.message ?? tr('加载失败', 'Failed to load', locale)}
      </p>
    )
  }
  if (isLoading && !data) {
    return <p style={noteStyle}>{tr('加载逐字稿中…', 'Loading transcripts…', locale)}</p>
  }
  const transcripts = data?.transcripts ?? []
  if (transcripts.length === 0) {
    return (
      <p style={noteStyle}>
        {tr(
          `${ticker} 暂无可用的财报电话会逐字稿`,
          `No earnings call transcripts available for ${ticker}`,
          locale,
        )}
      </p>
    )
  }
  // Identity-based selection: a composite key (year+quarter+index) survives
  // background refetches that reorder/shorten the list, and the trailing index
  // disambiguates genuine duplicate (year,quarter) pairs (amended filings).
  const keyOf = (tx: EarningsCallTranscript, idx: number): string =>
    `${tx.year}-Q${tx.quarter}-${idx}`
  const selected = transcripts.find((tx, i) => keyOf(tx, i) === selectedKey) ?? transcripts[0]

  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 8,
          flexWrap: 'wrap',
          marginBottom: 10,
        }}
      >
        {transcripts.map((tx, i) => {
          const key = keyOf(tx, i)
          const active = key === (selectedKey ?? keyOf(transcripts[0], 0))
          return (
            <button
              key={key}
              type="button"
              onClick={() => setSelectedKey(key)}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                letterSpacing: '0.04em',
                padding: '4px 10px',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${active ? 'var(--accent-cyan)' : 'var(--border-soft)'}`,
                background: active
                  ? 'color-mix(in srgb, var(--accent-cyan) 12%, transparent)'
                  : 'transparent',
                color: active ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              Q{tx.quarter} {tx.year}
            </button>
          )
        })}
      </div>
      {selected.date && (
        <p style={{ ...noteStyle, marginBottom: 8 }}>{formatDate(selected.date, locale, 'long')}</p>
      )}
      <div
        style={{
          padding: 14,
          maxHeight: 360,
          overflowY: 'auto',
          fontFamily: 'var(--font-body)',
          fontSize: 12.5,
          lineHeight: 1.7,
          color: 'var(--text-primary)',
          background: 'var(--surface-panel-40)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-sm)',
          whiteSpace: 'pre-wrap',
        }}
      >
        {selected.content ||
          tr(
            '该季度逐字稿暂不可用。',
            'Transcript content not available for this quarter.',
            locale,
          )}
      </div>
    </div>
  )
}

const noteStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '12px 16px',
  background: 'var(--surface-panel-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  margin: 0,
}
