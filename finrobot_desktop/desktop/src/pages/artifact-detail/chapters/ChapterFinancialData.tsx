// Chapter — Financial Data. Renders the audit-trail data captured at pipeline
// run time as analyst-friendly KV cards (income / balance / market / valuation).
// The original JSON blob is preserved as a collapsible "原始数据" details so
// developers can still verify the inputs without polluting the C-end surface.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { NumberSource } from '../../../components/SourcedNumber'
import { Chapter, SubChapter } from './ChapterBase'
import { MetricModule, type MetricCell, type RangePositioner } from './MetricModule'
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

// Visual cell = a MetricCell with a string label (this chapter's labels are all
// plain strings). `ratio`/`sub`/`addr` are pure presentation added by the
// builders — they never change the value, source, or caliber of a number.
type Cell = MetricCell & { label: string }

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
  let n = 0
  // `mode='percent'` cells that are MARGINS carry an inline proportion bar (the
  // value is a 0–1 ratio → fill). Other fields get no bar (no natural 0–100%).
  const push = (
    key: keyof IncomeShape,
    label: string,
    mode: 'currency' | 'percent',
    opts?: { sub?: string; bar?: boolean },
  ) => {
    const v = income[key]
    if (v === null || v === undefined) return
    n += 1
    const addr = `IS·${String(n).padStart(2, '0')}`
    if (mode === 'currency') {
      cells.push({
        label,
        value: formatCurrencyCompact(v as number, reportingCurrency, locale),
        source,
        addr,
        sub: opts?.sub,
      })
    } else {
      cells.push({
        label,
        value: formatPercent(v as number, locale),
        source,
        addr,
        // Margin proportion bar — fill = the ratio itself (clamped in the bar).
        ratio: opts?.bar ? (v as number) : undefined,
      })
    }
  }
  push('revenue', tr('营收', 'Revenue', locale), 'currency', {
    sub: tr('顶线 · 净销售额', 'TOP LINE · NET SALES', locale),
  })
  push('ebitda', 'EBITDA', 'currency', {
    sub: tr('经营性现金利润', 'OPERATING CASH PROFIT', locale),
  })
  push('net_income', tr('净利润', 'Net Income', locale), 'currency', {
    sub: tr('底线 · GAAP', 'BOTTOM LINE · GAAP', locale),
  })
  push('gross_margin', tr('毛利率', 'Gross Margin', locale), 'percent', { bar: true })
  push('operating_margin', tr('营业利润率', 'Operating Margin', locale), 'percent', { bar: true })
  push('depreciation_amortization', tr('折旧摊销', 'D&A', locale), 'currency', {
    sub: tr('非现金支出', 'NON-CASH CHARGE', locale),
  })
  push('rd_expense', tr('研发费用', 'R&D', locale), 'currency', {
    sub: tr('创新投入', 'INNOVATION SPEND', locale),
  })
  push('sga_expense', tr('销售管理费用', 'SG&A', locale), 'currency', {
    sub: tr('管理费用', 'OVERHEAD', locale),
  })
  push('interest_expense', tr('利息费用', 'Interest', locale), 'currency', {
    sub: tr('融资成本', 'FINANCING COST', locale),
  })
  return cells
}

export function buildBalanceCells(
  balance: BalanceShape | undefined,
  market: MarketShape,
  locale: Locale,
  quoteCurrency: string,
  reportingCurrency: string,
  source?: NumberSource,
): Cell[] {
  const cells: Cell[] = []
  const addr = (): string => `BS·${String(cells.length + 1).padStart(2, '0')}`
  if (balance?.total_debt !== undefined && balance.total_debt !== null) {
    cells.push({
      label: tr('总负债', 'Total Debt', locale),
      // Balance-sheet absolute → reporting currency.
      value: formatCurrencyCompact(balance.total_debt, reportingCurrency, locale),
      source,
      addr: addr(),
      sub: tr('总杠杆', 'GROSS LEVERAGE', locale),
    })
  }
  if (balance?.total_cash !== undefined && balance.total_cash !== null) {
    cells.push({
      label: tr('现金', 'Total Cash', locale),
      value: formatCurrencyCompact(balance.total_cash, reportingCurrency, locale),
      source,
      addr: addr(),
      sub: tr('流动性', 'LIQUIDITY', locale),
    })
  }
  if (market.market_cap !== undefined && market.market_cap !== null) {
    cells.push({
      label: tr('市值', 'Market Cap', locale),
      // Market cap is a quote-currency figure.
      value: formatCurrencyCompact(market.market_cap, quoteCurrency, locale),
      source,
      addr: addr(),
      sub: tr('股权价值', 'EQUITY VALUE', locale),
    })
  }
  if (market.shares_outstanding !== undefined && market.shares_outstanding !== null) {
    cells.push({
      label: tr('总股本', 'Shares Out', locale),
      value: formatCompactNumber(market.shares_outstanding, locale),
      source,
      addr: addr(),
      // Not a reported diluted count: FMP carries no raw shares field at all
      // (shares_outstanding = market_cap / price at the provider layer), and
      // even on the yfinance path a mismatch against market_cap/price falls
      // back to that same market-cap-implied count (engine/compute/coordinators/
      // extractor.py). "DILUTED" claimed a 10-Q-sourced diluted count this
      // pipeline never has.
      sub: tr('隐含', 'IMPLIED', locale),
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
  // When the 52-week positioner renders (price+high+low all present), the 52w
  // high/low live there instead of as standalone cells, so each datum appears
  // once. When it can't render, we fall back to showing whatever 52w cells exist.
  includeRange52Cells = true,
): Cell[] {
  const cells: Cell[] = []
  const addr = (): string => `VL·${String(cells.length + 1).padStart(2, '0')}`
  if (market.current_price !== undefined && market.current_price !== null) {
    cells.push({
      label: tr('现价', 'Price', locale),
      // Per-share quote → quote currency.
      value: formatCurrency(market.current_price, quoteCurrency, locale, 2),
      source,
      addr: addr(),
      sub: tr('最新 · 收盘', 'LAST · CLOSE', locale),
    })
  }
  if (market.pe_ratio !== undefined && market.pe_ratio !== null) {
    cells.push({
      label: 'P/E',
      value: `${formatNumber(market.pe_ratio, locale, 1)}x`,
      source,
      addr: addr(),
      sub: tr('盈利倍数', 'EARNINGS MULTIPLE', locale),
    })
  }
  if (valuation?.enterprise_value !== undefined && valuation.enterprise_value !== null) {
    cells.push({
      label: 'EV',
      // EV is an absolute reporting-currency figure.
      value: formatCurrencyCompact(valuation.enterprise_value, reportingCurrency, locale),
      source,
      addr: addr(),
      sub: tr('企业价值', 'TOTAL CAPITAL', locale),
    })
  }
  if (valuation?.ev_ebitda !== undefined && valuation.ev_ebitda !== null) {
    cells.push({
      label: 'EV/EBITDA',
      value: `${formatNumber(valuation.ev_ebitda, locale, 1)}x`,
      source,
      addr: addr(),
      sub: tr('资本倍数', 'CAPITAL MULTIPLE', locale),
    })
  }
  if (valuation?.ev_revenue !== undefined && valuation.ev_revenue !== null) {
    cells.push({
      label: 'EV/Revenue',
      value: `${formatNumber(valuation.ev_revenue, locale, 1)}x`,
      source,
      addr: addr(),
      sub: tr('销售倍数', 'SALES MULTIPLE', locale),
    })
  }
  if (market.beta !== undefined && market.beta !== null) {
    cells.push({
      label: 'Beta',
      value: formatNumber(market.beta, locale, 2),
      source,
      addr: addr(),
      sub: tr('系统性风险', 'SYSTEMATIC RISK', locale),
    })
  }
  if (includeRange52Cells) {
    if (market.price_52w_high !== undefined && market.price_52w_high !== null) {
      cells.push({
        label: tr('52 周高', '52W High', locale),
        value: formatCurrency(market.price_52w_high, quoteCurrency, locale, 2),
        source,
        addr: addr(),
      })
    }
    if (market.price_52w_low !== undefined && market.price_52w_low !== null) {
      cells.push({
        label: tr('52 周低', '52W Low', locale),
        value: formatCurrency(market.price_52w_low, quoteCurrency, locale, 2),
        source,
        addr: addr(),
      })
    }
  }
  return cells
}

/** Build the 52-week-range positioner ONLY when price + high + low are all
 *  present and high > low. Returns null otherwise (the caller then keeps the 52w
 *  high/low as plain cells so no datum is dropped). Position = (price − low) /
 *  (high − low); the component clamps it to [0,1]. This is a pure visual
 *  re-presentation of three numbers we already display — it computes a bar
 *  POSITION, never a new financial value. */
function buildRange52(
  market: MarketShape,
  locale: Locale,
  quoteCurrency: string,
  source: NumberSource | undefined,
): RangePositioner | null {
  const price = market.current_price
  const high = market.price_52w_high
  const low = market.price_52w_low
  if (
    price === undefined ||
    price === null ||
    high === undefined ||
    high === null ||
    low === undefined ||
    low === null ||
    !(high > low)
  ) {
    return null
  }
  const position = (price - low) / (high - low)
  const pctOfBand = Math.round(Math.max(0, Math.min(1, position)) * 100)
  const near =
    position >= 0.8
      ? tr('· 接近高位', '· NEAR HIGH', locale)
      : position <= 0.2
        ? tr('· 接近低位', '· NEAR LOW', locale)
        : ''
  return {
    label: tr('52 周区间定位', '52-WEEK RANGE POSITION', locale),
    position,
    current: formatCurrency(price, quoteCurrency, locale, 2),
    currentSource: source,
    currentCap: tr('现价', 'CURRENT', locale),
    low: formatCurrency(low, quoteCurrency, locale, 2),
    lowSource: source,
    lowCap: tr('52 周低', '52W LOW', locale),
    high: formatCurrency(high, quoteCurrency, locale, 2),
    highSource: source,
    highCap: tr('52 周高', '52W HIGH', locale),
    caption: `${pctOfBand}%${tr(' 区间', ' OF BAND', locale)} ${near}`.trim(),
  }
}

// ── Group glyphs (terminal chips for the module title bars; inline SVG, tokens
//    only — `currentColor` inherits the chip's accent so one glyph fits any rail).
/** Sets the SVG colour context so a `currentColor` glyph paints in the rail hue. */
function GlyphChip({
  color,
  glyph,
}: {
  color: string
  glyph: React.ReactNode
}): React.ReactElement {
  return <span style={{ color, display: 'grid', placeItems: 'center' }}>{glyph}</span>
}
function CompanyGlyph(): React.ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <rect x="2" y="3.4" width="6" height="8" rx="0.8" stroke="currentColor" strokeWidth="1.1" />
      <path d="M8 6.2h4v5.2H8" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
      <path
        d="M3.6 5.4h2.8 M3.6 7.3h2.8 M3.6 9.2h2.8 M9.4 8h1.2 M9.4 9.6h1.2"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={0.7}
        strokeLinecap="round"
      />
    </svg>
  )
}
function IncomeGlyph(): React.ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <line x1="2" y1="12" x2="12" y2="12" stroke="currentColor" strokeWidth="1.2" />
      <rect x="2.4" y="6.5" width="2.4" height="4" fill="currentColor" fillOpacity={0.45} />
      <rect x="5.8" y="4" width="2.4" height="6.5" fill="currentColor" fillOpacity={0.7} />
      <rect x="9.2" y="1.8" width="2.4" height="8.7" fill="currentColor" />
    </svg>
  )
}
function BalanceGlyph(): React.ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d="M7 1.5 L12 4 L12 4.6 L2 4.6 L2 4 Z"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinejoin="round"
      />
      <path d="M3.6 5.2v4.8 M7 5.2v4.8 M10.4 5.2v4.8" stroke="currentColor" strokeWidth="1.1" />
      <line x1="2" y1="11.4" x2="12" y2="11.4" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  )
}
function ValuationGlyph(): React.ReactElement {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M2 12 L12 2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <circle cx="4" cy="4" r="1.7" stroke="currentColor" strokeWidth="1.1" />
      <circle cx="10" cy="10" r="1.7" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  )
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
  // The 52-week positioner renders when price+high+low are all present (high>low);
  // when it does, the 52w high/low move into it (each datum shown once), so the
  // standalone 52w cells are suppressed. When it can't render, they stay as cells.
  const range52 = buildRange52(market, locale, quoteCurrency, numberSource)
  const valuationCells = buildValuationCells(
    market,
    valuation,
    locale,
    quoteCurrency,
    reportingCurrency,
    numberSource,
    range52 === null,
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
        <MetricModule
          title={tr('公司信息', 'Company', locale)}
          accent="success"
          glyph={<GlyphChip color="var(--success)" glyph={<CompanyGlyph />} />}
          cells={companyCells}
          columns={2}
        />
      )}

      {incomeCells.length > 0 && (
        <MetricModule
          title={tr('损益表', 'Income Statement', locale)}
          accent="primary"
          glyph={<GlyphChip color="var(--primary)" glyph={<IncomeGlyph />} />}
          meta={tr('TTM · 报告币种', 'TTM · REPORTING', locale)}
          cells={incomeCells}
          columns={3}
        />
      )}

      {balanceCells.length > 0 && (
        <MetricModule
          title={tr('资产负债', 'Balance Sheet', locale)}
          accent="cyan"
          glyph={<GlyphChip color="var(--accent-cyan)" glyph={<BalanceGlyph />} />}
          meta={tr('最新季度', 'LATEST QTR', locale)}
          cells={balanceCells}
          columns={2}
        />
      )}

      {(valuationCells.length > 0 || range52 !== null) && (
        <MetricModule
          title={tr('估值倍数', 'Valuation Multiples', locale)}
          accent="violet"
          glyph={<GlyphChip color="var(--secondary)" glyph={<ValuationGlyph />} />}
          meta={tr('报告时 · ×', 'AT REPORT · ×', locale)}
          cells={valuationCells}
          columns={3}
          range={range52 ?? undefined}
        />
      )}

      <SubChapter heading={tr('财报电话会逐字稿', 'Earnings Call Transcripts', locale)}>
        <EarningsCallSection ticker={ticker} locale={locale} />
      </SubChapter>

      {companyCells.length === 0 &&
        incomeCells.length === 0 &&
        balanceCells.length === 0 &&
        valuationCells.length === 0 &&
        range52 === null && (
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

      {/* Developer-only raw JSON snapshot — gated to dev builds (import.meta.env.DEV)
          so it never reaches analysts or the exported PDF (prod build → DEV false).
          The snapshot is a debug aid, not analyst-grade source traceability. */}
      {import.meta.env.DEV && Object.keys(data).length > 0 && (
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
      {/* Honest provenance label. Unlike every other report surface, this panel
          is NOT frozen and NOT part of the analysis — the equity_research
          narrative references no earnings call (verified: zero transcript refs
          across the pipeline + all agent instructions). A live-latest transcript
          sitting beside a report frozen to a date would otherwise let a reader
          assume the report incorporated it. The which-call ambiguity is closed
          by the visible quarter buttons + call date below; this line closes the
          is-it-part-of-the-report ambiguity. (If a future pipeline step ever
          CONSUMES transcript content, revisit freezing — see BACKLOG.) */}
      <p style={{ ...noteStyle, marginBottom: 10 }}>
        {tr(
          '参考:财报电话会逐字稿 · 不属于本报告的分析范围',
          "Reference: earnings call transcripts · not part of this report's analysis",
          locale,
        )}
      </p>
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
          // Measure cap — the chapter column is far wider than a readable prose
          // line; uncapped, this ran to ~180 characters/line (the report's
          // prose convention elsewhere in this component is 68ch).
          maxWidth: '68ch',
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
