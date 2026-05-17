import { useState, useEffect } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useAppStore } from '../stores/appStore'
import { useTickerFinancials, useTickerPrice } from '../hooks/useTickerData'
import PriceChart from '../components/charts/PriceChart'
import TechnicalAnalysisView from '../components/charts/TechnicalAnalysisView'
import ResearchSummary from '../components/ResearchSummary'
import CatalystPanel from '../components/CatalystPanel'
import NewsFeed from '../components/NewsFeed'
import { useCatalysts } from '../hooks/useCatalysts'
import { fmtUsd, fmtPct, fmtMult, fmtPrice } from '../utils/formatters'
import { BASE_URL } from '../api/client'

type ChartMode = 'simple' | 'technical'

type AnalysisType = 'income' | 'balance' | 'cashflow' | 'risk' | 'competitors' | 'overview'

interface AnalysisResult {
  result: string
  ticker: string
  analysis_type: string
}

const ANALYSIS_BUTTONS: { type: AnalysisType; label: string }[] = [
  { type: 'income', label: '收入分析' },
  { type: 'balance', label: '资产负债' },
  { type: 'cashflow', label: '现金流' },
  { type: 'risk', label: '风险评估' },
  { type: 'competitors', label: '竞争格局' },
  { type: 'overview', label: '综合概览' },
]

const ANALYSIS_LABELS: Record<AnalysisType, string> = {
  income: '收入分析',
  balance: '资产负债',
  cashflow: '现金流',
  risk: '风险评估',
  competitors: '竞争格局',
  overview: '综合概览',
}

// ── Types for new endpoints ────────────────────────────────────────────────────

interface ScoreResult {
  total: number
  fundamental: number
  valuation: number
  catalyst: number
  sentiment: number
  signal: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'
  breakdown: {
    fundamental: string
    valuation: string
    catalyst: string
    sentiment: string
  }
}

interface SniperResult {
  ideal_buy: number
  secondary_buy: number
  stop_loss: number
  take_profit: number
  position_size_pct: number
  risk_reward_ratio: number
  support_level: number
  resistance_level: number
}

// ── Source Tag ─────────────────────────────────────────────────────────────────

function SourceTag({ label }: { label: string }) {
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '8px',
        color: 'var(--text-muted)',
        background: 'var(--bg-3, var(--surface))',
        padding: '1px 5px',
        borderRadius: '2px',
        marginLeft: '6px',
        verticalAlign: 'middle',
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
      }}
    >
      {label}
    </span>
  )
}

// ── Signal colors ──────────────────────────────────────────────────────────────

function signalColor(signal: string): string {
  switch (signal) {
    case 'STRONG_BUY': return 'var(--positive)'
    case 'BUY':        return 'var(--positive)'
    case 'HOLD':       return 'var(--accent, #f59e0b)'
    case 'SELL':       return 'var(--negative)'
    case 'STRONG_SELL':return 'var(--negative)'
    default:           return 'var(--text-muted)'
  }
}

function signalBg(signal: string): string {
  switch (signal) {
    case 'STRONG_BUY': return 'var(--positive-bg, rgba(34,197,94,0.12))'
    case 'BUY':        return 'var(--positive-bg, rgba(34,197,94,0.12))'
    case 'HOLD':       return 'rgba(245,158,11,0.12)'
    case 'SELL':       return 'var(--negative-bg, rgba(239,68,68,0.12))'
    case 'STRONG_SELL':return 'var(--negative-bg, rgba(239,68,68,0.12))'
    default:           return 'var(--surface)'
  }
}

// ── Score Card ─────────────────────────────────────────────────────────────────

function ScoreBar({ value, color }: { value: number; color: string }) {
  return (
    <div
      style={{
        height: '4px',
        background: 'var(--border)',
        borderRadius: '2px',
        overflow: 'hidden',
        marginTop: '4px',
      }}
    >
      <div
        style={{
          height: '100%',
          width: `${Math.min(100, Math.max(0, value))}%`,
          background: color,
          borderRadius: '2px',
          transition: 'width 0.5s ease',
        }}
      />
    </div>
  )
}

function CompositeScoreCard({ score }: { score: ScoreResult }) {
  const subScores = [
    { key: 'fundamental', label: 'Fundamental', value: score.fundamental },
    { key: 'valuation',   label: 'Valuation',   value: score.valuation },
    { key: 'catalyst',    label: 'Catalyst',     value: score.catalyst },
    { key: 'sentiment',   label: 'Sentiment',    value: score.sentiment },
  ] as const

  const color = signalColor(score.signal)
  const bg = signalBg(score.signal)

  return (
    <div
      style={{
        background: 'var(--bg-2, var(--elevated))',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm, 6px)',
        padding: '16px 18px',
        marginBottom: '12px',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '16px' }}>
        <div>
          <div
            style={{
              fontSize: '10px',
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              fontFamily: 'var(--font-mono)',
              marginBottom: '4px',
            }}
          >
            综合评分
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '36px',
                fontWeight: 700,
                color: color,
                lineHeight: 1,
              }}
            >
              {Math.round(score.total)}
            </span>
            <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>/100</span>
          </div>
        </div>
        <div>
          <span
            style={{
              display: 'inline-block',
              padding: '4px 10px',
              borderRadius: '4px',
              background: bg,
              color: color,
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              fontWeight: 700,
              letterSpacing: '0.06em',
              border: `1px solid ${color}`,
            }}
          >
            {score.signal === 'STRONG_BUY' ? '强烈买入' :
             score.signal === 'BUY' ? '买入' :
             score.signal === 'HOLD' ? '持有' :
             score.signal === 'SELL' ? '卖出' :
             '强烈卖出'}
          </span>
        </div>
      </div>

      {/* Sub-score bars */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {subScores.map(({ key, label, value }) => {
          const barColor = value >= 60 ? 'var(--positive)' : value >= 40 ? 'var(--accent, #f59e0b)' : 'var(--negative)'
          return (
            <div key={key}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 500 }}>
                  {label}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '12px',
                      color: barColor,
                      fontWeight: 600,
                    }}
                  >
                    {Math.round(value)}
                  </span>
                  <span
                    style={{
                      fontSize: '11px',
                      color: 'var(--text-muted)',
                      maxWidth: '200px',
                      textAlign: 'right',
                      fontStyle: 'italic',
                    }}
                  >
                    {score.breakdown[key as keyof typeof score.breakdown]}
                  </span>
                </div>
              </div>
              <ScoreBar value={value} color={barColor} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Sniper Points Card ─────────────────────────────────────────────────────────

function SniperCard({ sniper }: { sniper: SniperResult }) {
  const pricePoints = [
    { label: 'Ideal Buy',      value: sniper.ideal_buy,     color: 'var(--positive)' },
    { label: 'Secondary Buy',  value: sniper.secondary_buy, color: 'var(--positive)' },
    { label: 'Stop Loss',      value: sniper.stop_loss,     color: 'var(--negative)' },
    { label: 'Take Profit',    value: sniper.take_profit,   color: 'var(--accent, #f59e0b)' },
  ]

  return (
    <div
      style={{
        background: 'var(--bg-2, var(--elevated))',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm, 6px)',
        padding: '16px 18px',
        marginBottom: '12px',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
        <div
          style={{
            fontSize: '10px',
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            fontFamily: 'var(--font-mono)',
          }}
        >
          作战计划
        </div>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Position:{' '}
            <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
              {sniper.position_size_pct.toFixed(1)}%
            </span>
          </span>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            R:R ={' '}
            <span style={{ color: 'var(--accent, #f59e0b)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
              {sniper.risk_reward_ratio.toFixed(2)}
            </span>
          </span>
        </div>
      </div>

      {/* 2x2 price grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '10px',
        }}
      >
        {pricePoints.map(({ label, value, color }) => (
          <div
            key={label}
            style={{
              padding: '10px 12px',
              background: 'var(--surface)',
              border: `1px solid var(--border)`,
              borderRadius: '4px',
              borderLeft: `3px solid ${color}`,
            }}
          >
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              {label}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '16px',
                fontWeight: 700,
                color,
              }}
            >
              {fmtPrice(value)}
            </div>
          </div>
        ))}
      </div>

      {/* Support / Resistance */}
      <div style={{ display: 'flex', gap: '16px', marginTop: '10px' }}>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Support:{' '}
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--positive)' }}>
            {fmtPrice(sniper.support_level)}
          </span>
        </span>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Resistance:{' '}
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--negative)' }}>
            {fmtPrice(sniper.resistance_level)}
          </span>
        </span>
      </div>
    </div>
  )
}

// ── KPI Card with source tag + explanation ─────────────────────────────────────

interface KpiRowProps {
  label: string
  value: string
  source: string
  explanation: string
  loading?: boolean
}

function KpiRow({ label, value, source, explanation, loading }: KpiRowProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '2px',
        padding: '10px 12px',
        background: 'var(--bg-2, var(--elevated))',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm, 6px)',
      }}
    >
      <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em', fontFamily: 'var(--font-mono)' }}>
        {label}
      </div>
      {loading ? (
        <div className="skeleton" style={{ width: 80, height: 18, borderRadius: 3 }} />
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ fontSize: '15px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
              {value}
            </span>
            <SourceTag label={source} />
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
            {explanation}
          </div>
        </>
      )}
    </div>
  )
}

// ── Skeleton card for loading state ───────────────────────────────────────────

function CardSkeleton({ height = 160 }: { height?: number }) {
  return (
    <div
      style={{
        background: 'var(--bg-2, var(--elevated))',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm, 6px)',
        padding: '16px 18px',
        marginBottom: '12px',
        height,
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}
    >
      <div className="skeleton" style={{ width: 120, height: 12 }} />
      <div className="skeleton" style={{ width: 60, height: 36 }} />
      <div className="skeleton" style={{ width: '100%', height: 8 }} />
      <div className="skeleton" style={{ width: '100%', height: 8 }} />
      <div className="skeleton" style={{ width: '80%', height: 8 }} />
    </div>
  )
}

// ── "Run DCF First" prompt ─────────────────────────────────────────────────────

function RunDcfPrompt() {
  return (
    <div
      style={{
        background: 'var(--bg-2, var(--elevated))',
        border: '1px dashed var(--border)',
        borderRadius: 'var(--r-sm, 6px)',
        padding: '20px',
        marginBottom: '12px',
        textAlign: 'center',
        color: 'var(--text-muted)',
        fontSize: '13px',
      }}
    >
      <div style={{ fontSize: '18px', marginBottom: '6px' }}>◎</div>
      <div>请先运行 <strong style={{ color: 'var(--accent, #f59e0b)', fontFamily: 'var(--font-mono)' }}>DCF 估值</strong> 以解锁综合评分与作战计划</div>
      <div style={{ fontSize: '11px', marginTop: '4px', fontStyle: 'italic' }}>
        点击上方工具栏的 DCF 按钮
      </div>
    </div>
  )
}

// ── Price history fetcher for sniper endpoint ──────────────────────────────────

interface PriceHistoryItem {
  date: string
  close: number
  [key: string]: string | number | boolean | null
}

function usePriceHistory(ticker: string) {
  return useQuery({
    queryKey: ['price-history', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/price`)
      if (!resp.ok) throw new Error('Failed to fetch price history')
      const data = await resp.json() as { history?: PriceHistoryItem[] }
      return data.history ?? []
    },
    enabled: !!ticker,
    staleTime: 5 * 60_000,
  })
}

// ── Main OverviewTab ───────────────────────────────────────────────────────────

export default function OverviewTab() {
  const ticker = useAppStore((s) => s.ticker)
  const researchResult = useAppStore((s) => s.researchResult)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const catalysts = useAppStore((s) => s.catalysts)
  const catalystsLoading = useAppStore((s) => s.catalystsLoading)
  const dcfResult = useAppStore((s) => s.dcfResult)

  const [chartMode, setChartMode] = useState<ChartMode>('simple')
  const [activeAnalysisType, setActiveAnalysisType] = useState<AnalysisType | null>(null)

  // Fetch catalysts when ticker changes
  useCatalysts()

  // Fetch price + financials for KPI cards
  const { data: priceData } = useTickerPrice(ticker ?? '')
  const { data: financials, isLoading: finLoading } = useTickerFinancials(ticker ?? '')
  const { data: priceHistory } = usePriceHistory(ticker ?? '')

  // ── Composite Score mutation ──────────────────────────────────────────────────
  const scoreMutation = useMutation<ScoreResult, Error, void>({
    mutationFn: async () => {
      const fin = financials as Record<string, unknown> | undefined
      const income = (fin?.income ?? {}) as Record<string, unknown>
      const market = (fin?.market ?? {}) as Record<string, unknown>

      const grossMargin = income.revenue && (income.revenue as number) > 0
        ? ((income.gross_profit as number | undefined) ?? 0) / (income.revenue as number)
        : undefined

      const revenueGrowth = income.revenue_growth_yoy as number | undefined

      // Gather catalysts from store
      const catalystList = catalysts ?? []
      const positiveCatalysts = catalystList.filter((c) => c.sentiment === 'positive').length
      const negativeCatalysts = catalystList.filter((c) => c.sentiment === 'negative').length

      const dcfUpside = dcfResult?.implied_price && priceData?.current_price
        ? ((dcfResult.implied_price - priceData.current_price) / priceData.current_price) * 100
        : undefined

      const body: Record<string, unknown> = {
        pe_ratio: market.pe_ratio as number | undefined,
        gross_margin: grossMargin,
        revenue_growth_yoy: revenueGrowth,
        positive_catalysts: positiveCatalysts,
        negative_catalysts: negativeCatalysts,
        dcf_upside_pct: dcfUpside,
      }

      const resp = await fetch(`${BASE_URL}/api/compute/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) throw new Error(`Score compute failed: ${resp.status}`)
      return resp.json() as Promise<ScoreResult>
    },
  })

  // ── Sniper mutation ───────────────────────────────────────────────────────────
  const sniperMutation = useMutation<SniperResult, Error, void>({
    mutationFn: async () => {
      const closePrices = (priceHistory ?? []).map((h) => h.close).filter(Boolean)

      const body: Record<string, unknown> = {
        ticker,
        current_price: priceData?.current_price ?? 100,
        dcf_target: dcfResult?.implied_price ?? priceData?.current_price ?? 100,
        historical_prices: closePrices.slice(-252), // up to 1 year of daily closes
      }

      const resp = await fetch(`${BASE_URL}/api/compute/sniper`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) throw new Error(`Sniper compute failed: ${resp.status}`)
      return resp.json() as Promise<SniperResult>
    },
  })

  // Trigger score + sniper when dcfResult + priceData are available
  useEffect(() => {
    if (!dcfResult || !priceData || !ticker) return
    scoreMutation.mutate()
    sniperMutation.mutate()
  // Only re-trigger when the core inputs change (not on every render)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, dcfResult?.implied_price, priceData?.current_price])

  // ── Quick Analysis mutation ───────────────────────────────────────────────────
  const analyzeMutation = useMutation<AnalysisResult, Error, { ticker: string; type: AnalysisType }>({
    mutationFn: async ({ ticker: t, type }) => {
      const resp = await fetch(`/api/analyze/${t}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis_type: type }),
      })
      if (!resp.ok) throw new Error(`Analysis failed: ${resp.status}`)
      return resp.json() as Promise<AnalysisResult>
    },
  })

  function handleAnalyze(type: AnalysisType) {
    if (!ticker) return
    setActiveAnalysisType(type)
    analyzeMutation.mutate({ ticker, type })
  }

  // ── Derived KPI values ────────────────────────────────────────────────────────
  const fin = financials as Record<string, unknown> | undefined
  const income = (fin?.income ?? {}) as Record<string, unknown>
  const market = (fin?.market ?? {}) as Record<string, unknown>
  const valuation = (fin?.valuation ?? {}) as Record<string, unknown>

  const revenue = income.revenue as number | undefined
  const ebitda = income.ebitda as number | undefined
  const ebitdaMargin = revenue && revenue > 0 && ebitda != null ? ebitda / revenue : undefined
  const peRatio = market.pe_ratio as number | undefined
  const dcfTarget = dcfResult?.implied_price

  // Derived verdict from research or DCF
  let verdict = '—'
  if (researchResult?.recommendation) {
    verdict = researchResult.recommendation.toUpperCase()
  } else if (dcfResult && priceData?.current_price) {
    const upside = ((dcfResult.implied_price - priceData.current_price) / priceData.current_price) * 100
    verdict = upside > 15 ? 'BUY' : upside < -10 ? 'SELL' : 'HOLD'
  }

  const hasDcf = !!dcfResult

  return (
    <div className="tab-content overview-tab">

      {/* ── Composite Score + Sniper (require DCF) ── */}
      {!hasDcf ? (
        <RunDcfPrompt />
      ) : (
        <>
          {/* Composite Score */}
          {scoreMutation.isPending && <CardSkeleton height={200} />}
          {scoreMutation.isSuccess && scoreMutation.data && (
            <CompositeScoreCard score={scoreMutation.data} />
          )}
          {scoreMutation.isError && (
            <div
              style={{
                padding: '10px 14px',
                marginBottom: '12px',
                borderRadius: '6px',
                background: 'var(--negative-bg)',
                color: 'var(--negative)',
                fontSize: '12px',
                border: '1px solid var(--negative)',
              }}
            >
              Score unavailable: {scoreMutation.error.message}
            </div>
          )}

          {/* Sniper Points */}
          {sniperMutation.isPending && <CardSkeleton height={160} />}
          {sniperMutation.isSuccess && sniperMutation.data && (
            <SniperCard sniper={sniperMutation.data} />
          )}
          {sniperMutation.isError && (
            <div
              style={{
                padding: '10px 14px',
                marginBottom: '12px',
                borderRadius: '6px',
                background: 'var(--negative-bg)',
                color: 'var(--negative)',
                fontSize: '12px',
                border: '1px solid var(--negative)',
              }}
            >
              Sniper points unavailable: {sniperMutation.error.message}
            </div>
          )}
        </>
      )}

      {/* ── KPI Cards with source tags ── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
          gap: '8px',
          marginBottom: '12px',
        }}
      >
        <KpiRow
          label="Revenue (TTM)"
          value={revenue != null ? fmtUsd(revenue) : '—'}
          source="yfinance"
          explanation="过去12个月总营收"
          loading={finLoading}
        />
        <KpiRow
          label="EBITDA Margin"
          value={ebitdaMargin != null ? fmtPct(ebitdaMargin) : '—'}
          source="yfinance"
          explanation="扣除财务调整前的盈利能力"
          loading={finLoading}
        />
        <KpiRow
          label="P/E Ratio"
          value={peRatio != null ? fmtMult(peRatio) : '—'}
          source="yfinance"
          explanation="每一元盈利对应的股价"
          loading={finLoading}
        />
        <KpiRow
          label="DCF Target"
          value={dcfTarget != null ? fmtPrice(dcfTarget) : '—'}
          source="dcf-model"
          explanation="基于现金流折现模型的内在价值"
          loading={false}
        />
        <KpiRow
          label="Verdict"
          value={verdict}
          source="finagent"
          explanation="基于估值与基本面的综合判断"
          loading={false}
        />
        {valuation.ev_ebitda != null && (
          <KpiRow
            label="EV/EBITDA"
            value={fmtMult(valuation.ev_ebitda as number)}
            source="yfinance"
            explanation="企业价值相对于经营利润的倍数"
            loading={finLoading}
          />
        )}
      </div>

      {/* ── Chart mode toggle + price chart ── */}
      <div>
        <div className="chart-mode-toggle">
          <button
            className={`chart-mode-btn${chartMode === 'simple' ? ' active' : ''}`}
            onClick={() => setChartMode('simple')}
          >
            Simple
          </button>
          <button
            className={`chart-mode-btn${chartMode === 'technical' ? ' active' : ''}`}
            onClick={() => setChartMode('technical')}
          >
            Technical
          </button>
        </div>
        {chartMode === 'simple' ? (
          <PriceChart title={`${ticker} Price`} />
        ) : (
          <TechnicalAnalysisView />
        )}
      </div>

      {/* ── Research summary ── */}
      {researchResult ? (
        <ResearchSummary result={researchResult} currentPrice={currentPrice} />
      ) : (
        <div className="empty-state-card">
          <p>跑一次 Research 分析以查看投资论点</p>
        </div>
      )}

      {/* ── Catalyst panel ── */}
      {ticker && (
        <CatalystPanel
          catalysts={catalysts ?? []}
          loading={catalystsLoading}
        />
      )}

      {/* ── News feed ── */}
      {ticker && <NewsFeed />}

      {/* ── Quick Analysis section ── */}
      {ticker && (
        <div className="quick-analysis-section">
          <p className="section-title">快速分析</p>
          <div className="quick-analysis-btn-group">
            {ANALYSIS_BUTTONS.map(({ type, label }) => {
              const isActive = activeAnalysisType === type
              const isLoading = isActive && analyzeMutation.isPending
              return (
                <button
                  key={type}
                  className={`quick-analysis-btn${isActive ? ' quick-analysis-btn--active' : ''}`}
                  onClick={() => handleAnalyze(type)}
                  disabled={analyzeMutation.isPending}
                >
                  {isLoading ? '...' : label}
                </button>
              )
            })}
          </div>

          {analyzeMutation.isPending && (
            <div className="quick-analysis-result">
              <p className="quick-analysis-result-title">
                {activeAnalysisType ? ANALYSIS_LABELS[activeAnalysisType] : '分析中'}
              </p>
              <p className="quick-analysis-loading-text">分析中...</p>
            </div>
          )}

          {analyzeMutation.isError && (
            <div className="quick-analysis-result quick-analysis-result--error">
              <p className="quick-analysis-result-title">分析失败</p>
              <p className="quick-analysis-error-text">{analyzeMutation.error.message}</p>
            </div>
          )}

          {analyzeMutation.isSuccess && analyzeMutation.data && (
            <div className="quick-analysis-result">
              <p className="quick-analysis-result-title">
                {activeAnalysisType ? ANALYSIS_LABELS[activeAnalysisType] : analyzeMutation.data.analysis_type}
              </p>
              <div className="quick-analysis-content">
                {analyzeMutation.data.result}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
