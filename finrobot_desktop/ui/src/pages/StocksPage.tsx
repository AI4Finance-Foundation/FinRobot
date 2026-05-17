/**
 * StocksPage — the main stock analysis workstation.
 *
 * Routes:
 *   /stocks           → empty state (no ticker)
 *   /stocks/:ticker   → full analysis view
 *
 * Layout (per UI_DESIGN.md §3.1):
 *   StockHeader  — ticker, price, change, market cap, watchlist button
 *   VerbToolbar  — 6 verb-action buttons (DCF / LBO / Comps / Catalysts / IC Memo / Ask AI)
 *   Tab bar      — 6 tabs: 估值 / 财务 / 同业 / 走势 / 新闻 / 历史
 *   Tab content  — existing view components reused unchanged
 *
 * Behaviour:
 *  - Switching ticker cancels inflight requests via AbortController
 *  - Empty state shows recent 10 tickers from localStorage
 *  - Invalid ticker format rejected client-side (no request sent)
 *  - Each tab's loading / error state is independent
 *  - 1-6 keyboard shortcuts switch tabs; Cmd+R refetches current ticker
 */

import {
  useEffect,
  useCallback,
  useRef,
  useMemo,
  useState,
  useId,
} from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQueryClient, useMutation } from '@tanstack/react-query'

// Stores
import { useAppStore } from '../stores/appStore'
import { useStocksStore, isValidTicker, type StocksTab, type ToolName } from '../stores/stocksStore'
import { useI18n } from '../i18n'
import { useUiStore } from '../stores/uiStore'

// Hooks
import { useTickerPrice } from '../hooks/useTickerData'
import { useRunStream } from '../hooks/useRunStream'

// Components
import { ErrorBoundary } from '../components/ErrorBoundary'
import VerbToolbar from '../components/VerbToolbar'
import WarningBanner from '../components/WarningBanner'
import ToastContainer from '../components/Toast'
import AnalysisProgress from '../components/AnalysisProgress'
import { WhyMovingPopover } from '../components/WhyMovingPopover'

// Tab views
import OverviewTab from '../views/OverviewTab'
import ValuationTab from '../views/ValuationTab'
import FinancialsTab from '../views/FinancialsTab'
import PeersTab from '../views/PeersTab'
import PerformanceTab from '../views/PerformanceTab'
import NewsTab from '../views/NewsTab'
import HistoryTab from '../views/HistoryTab'

// Utils
import { fmtPrice, fmtUsd } from '../utils/formatters'
import { BASE_URL } from '../api/client'

// ── Tab configuration ─────────────────────────────────────────────────────────

interface TabConfig {
  key: StocksTab
  label: string
  shortcut: string  // 1-6
}

// Overview first (landing tab), then data tabs, then analysis tabs.
const TABS: TabConfig[] = [
  { key: 'overview',    label: 'tab.overview',    shortcut: '1' },
  { key: 'financials',  label: 'tab.financials',  shortcut: '2' },
  { key: 'performance', label: 'tab.performance', shortcut: '3' },
  { key: 'news',        label: 'tab.news',        shortcut: '4' },
  { key: 'valuation',   label: 'tab.valuation',   shortcut: '5' },
  { key: 'comps',       label: 'tab.comps',       shortcut: '6' },
  { key: 'history',     label: 'tab.history',     shortcut: '7' },
  { key: 'research',    label: 'tab.research',    shortcut: '8' },
]

// Quick-access tickers for empty state
const QUICK_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META', 'GOOGL', 'BRKB']

// ── StockHeader ───────────────────────────────────────────────────────────────

interface StockHeaderNewProps {
  ticker: string
}

function StockHeaderNew({ ticker }: StockHeaderNewProps) {
  const { data, isLoading, isError, refetch } = useTickerPrice(ticker)
  const { watchlist, toggleWatchlist } = useStocksStore()
  const isWatched = watchlist.has(ticker)
  const { t } = useI18n()

  const change = data?.change ?? 0
  const changeColor = change >= 0 ? 'var(--positive)' : 'var(--negative)'
  const changePct = data?.change_pct ?? 0

  if (isError && !data) {
    return (
      <div
        className="stock-header"
        role="alert"
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0' }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            fontSize: '1.4rem',
            color: 'var(--accent)',
            letterSpacing: '0.04em',
          }}
        >
          {ticker}
        </span>
        <span style={{ color: 'var(--negative)', fontSize: '0.88rem' }}>
          {t('stock.error.title')}
        </span>
        <button
          onClick={() => refetch()}
          style={{
            padding: '4px 12px',
            fontSize: '0.87rem',
            border: '1px solid var(--border)',
            borderRadius: 4,
            background: 'var(--surface)',
            color: 'var(--text-primary)',
            cursor: 'pointer',
          }}
        >
          {t('stock.error.retry')}
        </button>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div
        className="stock-header"
        aria-busy="true"
        aria-label="Loading stock data"
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0' }}
      >
        <div className="skeleton" style={{ width: 80, height: 28, borderRadius: 4 }} />
        <div className="skeleton" style={{ width: 120, height: 20, borderRadius: 4 }} />
        <div className="skeleton" style={{ width: 80, height: 16, borderRadius: 4 }} />
      </div>
    )
  }

  const companyName = data?.company_name ?? ''
  const truncatedName =
    companyName.length > 40 ? companyName.slice(0, 40) + '…' : companyName

  return (
    <div
      className="stock-header"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 0',
        flexWrap: 'wrap',
      }}
    >
      {/* Ticker */}
      <span
        className="stock-ticker"
        style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 700,
          fontSize: '1.7rem',
          color: 'var(--accent)',
          letterSpacing: '0.04em',
          lineHeight: 1,
        }}
      >
        {ticker}
      </span>

      {/* Company name — truncated with full name in title */}
      {truncatedName && (
        <span
          style={{
            fontSize: '0.88rem',
            color: 'var(--text-secondary)',
            maxWidth: 260,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={companyName}
        >
          {truncatedName}
        </span>
      )}

      {/* Price — show — placeholder when missing to keep layout stable */}
      <span
        className="stock-price"
        style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
          fontSize: '1.1rem',
          color: data?.current_price != null ? 'var(--text-primary)' : 'var(--text-muted)',
        }}
      >
        {data?.current_price != null ? fmtPrice(data.current_price) : t('common.notAvailable')}
      </span>

      {/* Change */}
      {data?.change != null ? (
        <span
          className="stock-change"
          style={{ color: changeColor, fontSize: '0.88rem', fontFamily: 'var(--font-mono)' }}
        >
          {change >= 0 ? '+' : ''}{change.toFixed(2)} ({changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%)
        </span>
      ) : (
        <span style={{ fontSize: '0.88rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {t('common.notAvailable')}
        </span>
      )}

      {/* Why moving? — one-click LLM explanation */}
      <WhyMovingPopover ticker={ticker}>
        {({ onClick, ariaExpanded }) => (
          <button
            onClick={onClick}
            aria-label={`查看 ${ticker} 今日动向解释`}
            aria-expanded={ariaExpanded}
            title="为啥动？— 让 FinAgent 一句话解释"
            style={{
              padding: '3px 9px',
              fontSize: '0.75rem',
              border: '1px solid var(--border)',
              borderRadius: 4,
              background: 'var(--accent-dim)',
              color: 'var(--accent)',
              cursor: 'pointer',
              fontFamily: 'var(--font-ui)',
              fontWeight: 500,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              whiteSpace: 'nowrap',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--accent)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
          >
            💡 为啥动
          </button>
        )}
      </WhyMovingPopover>

      {/* Market cap */}
      <span style={{ fontSize: '0.87rem', color: 'var(--text-muted)' }}>
        {t('stock.marketcap')}{' '}
        {data?.market_cap != null ? fmtUsd(data.market_cap) : t('common.notAvailable')}
      </span>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Watchlist button */}
      <button
        onClick={() => toggleWatchlist(ticker)}
        aria-label={isWatched ? t('stock.watchlist.remove') : t('stock.watchlist.add')}
        aria-pressed={isWatched}
        style={{
          padding: '4px 12px',
          fontSize: '0.87rem',
          fontWeight: 500,
          border: `1px solid ${isWatched ? 'var(--accent)' : 'var(--border)'}`,
          borderRadius: 4,
          background: isWatched ? 'var(--accent-dim)' : 'transparent',
          color: isWatched ? 'var(--accent)' : 'var(--text-muted)',
          cursor: 'pointer',
          transition: 'all 0.15s',
          whiteSpace: 'nowrap',
        }}
      >
        {isWatched ? t('stock.watchlist.remove') : t('stock.watchlist.add')}
      </button>
    </div>
  )
}

// ── StocksTabBar ──────────────────────────────────────────────────────────────

interface StocksTabBarProps {
  activeTab: StocksTab
  onTabChange: (tab: StocksTab) => void
}

function StocksTabBar({ activeTab, onTabChange }: StocksTabBarProps) {
  const { t } = useI18n()
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLButtonElement>, tab: StocksTab) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onTabChange(tab)
      }
    },
    [onTabChange],
  )

  return (
    <div
      role="tablist"
      aria-label="Analysis sections"
      className="tab-bar"
      style={{ display: 'flex', gap: 2 }}
    >
      {TABS.map((tab) => {
        const label = t(tab.label)
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={activeTab === tab.key}
            aria-controls={`tabpanel-${tab.key}`}
            id={`tab-${tab.key}`}
            className={`tab-btn${activeTab === tab.key ? ' active' : ''}`}
            onClick={() => onTabChange(tab.key)}
            onKeyDown={(e) => handleKeyDown(e, tab.key)}
            title={`${label} (${tab.shortcut})`}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}

// ── RAG Q&A types ─────────────────────────────────────────────────────────────

interface AskCitation {
  text: string
  score: number
  source?: string
}

interface AskResponse {
  answer: string
  citations: AskCitation[]
  chunk_count: number
}

// ── ResearchTab (RAG Q&A) ─────────────────────────────────────────────────────

interface ResearchTabProps {
  ticker: string
}

function ResearchTab({ ticker }: ResearchTabProps) {
  const [question, setQuestion] = useState('')
  const inputId = useId()
  const { t } = useI18n()

  const askMutation = useMutation<AskResponse, Error, { question: string }>({
    mutationFn: async ({ question: q }) => {
      const resp = await fetch(`${BASE_URL}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, question: q, top_k: 5 }),
      })
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }
      return resp.json() as Promise<AskResponse>
    },
  })

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      const q = question.trim()
      if (!q) return
      askMutation.mutate({ question: q })
    },
    [question, askMutation],
  )

  return (
    <div className="tab-content research-tab">
      <section className="chart-section">
        <h3 className="section-title">{t('research.heading')}</h3>

        {/* Input form */}
        <form
          onSubmit={handleSubmit}
          style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}
        >
          <label htmlFor={inputId} style={{ display: 'none' }}>
            {t('research.placeholder')}
          </label>
          <input
            id={inputId}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t('research.placeholder')}
            disabled={askMutation.isPending}
            style={{
              flex: 1,
              padding: '7px 12px',
              fontSize: '0.85rem',
              fontFamily: 'var(--font-sans)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              background: 'var(--surface)',
              color: 'var(--text-primary)',
              outline: 'none',
              opacity: askMutation.isPending ? 0.6 : 1,
            }}
          />
          <button
            type="submit"
            disabled={!question.trim() || askMutation.isPending}
            style={{
              padding: '7px 16px',
              fontSize: '0.87rem',
              fontWeight: 500,
              border: '1px solid var(--accent)',
              borderRadius: 4,
              background: askMutation.isPending ? 'var(--border)' : 'var(--accent-dim)',
              color: 'var(--accent)',
              cursor: !question.trim() || askMutation.isPending ? 'not-allowed' : 'pointer',
              opacity: !question.trim() ? 0.5 : 1,
              whiteSpace: 'nowrap',
            }}
          >
            {askMutation.isPending ? t('common.loading') : t('research.ask')}
          </button>
        </form>

        {/* Error */}
        {askMutation.isError && (
          <div
            role="alert"
            style={{
              padding: '10px 14px',
              borderRadius: 4,
              background: 'var(--negative-bg)',
              color: 'var(--negative)',
              fontSize: '0.87rem',
              border: '1px solid var(--negative)',
            }}
          >
            {t('research.error')}
          </div>
        )}

        {/* Empty state */}
        {!askMutation.data && !askMutation.isPending && !askMutation.isError && (
          <div className="empty-state-card">
            <p style={{ margin: 0 }}>{t('research.empty')}</p>
          </div>
        )}

        {/* Answer */}
        {askMutation.data && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 16,
            }}
          >
            {/* Answer text */}
            <div
              style={{
                padding: '14px 16px',
                borderRadius: 6,
                background: 'var(--elevated)',
                border: '1px solid var(--border-subtle)',
                fontSize: '0.88rem',
                color: 'var(--text-primary)',
                lineHeight: 1.65,
                whiteSpace: 'pre-wrap',
              }}
            >
              {askMutation.data.answer}
            </div>

            {/* Citations */}
            {askMutation.data.citations.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div
                  style={{
                    fontSize: '0.87rem',
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                  }}
                >
                  {t('research.citations')}
                </div>
                {askMutation.data.citations.map((cit, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 4,
                      background: 'var(--surface)',
                      border: '1px solid var(--border)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 6,
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: 8,
                      }}
                    >
                      <span
                        style={{
                          fontSize: '0.87rem',
                          color: 'var(--text-muted)',
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        #{idx + 1}
                        {cit.source ? ` · ${cit.source}` : ''}
                      </span>
                      <span
                        style={{
                          fontSize: '0.87rem',
                          color: 'var(--text-muted)',
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        {t('research.relevance')} {(cit.score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <p
                      style={{
                        margin: 0,
                        fontSize: '0.87rem',
                        color: 'var(--text-secondary)',
                        lineHeight: 1.55,
                      }}
                    >
                      {cit.text}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {/* Source attribution */}
            <div
              style={{
                fontSize: '0.87rem',
                color: 'var(--text-muted)',
                fontStyle: 'italic',
              }}
            >
              {t('research.source')}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

interface EmptyStateProps {
  onTickerSelect: (ticker: string) => void
}

function EmptyState({ onTickerSelect }: EmptyStateProps) {
  const recentTickers = useStocksStore((s) => s.recentTickers)
  const [inputValue, setInputValue] = useState('')
  const [inputError, setInputError] = useState('')
  const navigate = useNavigate()
  const { t } = useI18n()

  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value.toUpperCase().replace(/[^A-Z0-9.\-]/g, '')
      setInputValue(val)
      setInputError('')
    },
    [],
  )

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      const sym = inputValue.trim().toUpperCase()
      if (!sym) return
      if (!isValidTicker(sym)) {
        setInputError(t('stocks.empty.invalid'))
        return
      }
      navigate(`/stocks/${sym}`)
    },
    [inputValue, navigate, t],
  )

  const tickers = recentTickers.length > 0 ? recentTickers : QUICK_TICKERS

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        gap: 24,
        background: 'var(--bg-0)',
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 20,
          fontWeight: 700,
          color: 'var(--text-primary)',
          letterSpacing: '-0.02em',
          marginBottom: 8,
        }}>
          个股分析
        </div>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          letterSpacing: '0.03em',
        }}>
          输入股票代码开始分析
        </div>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <div style={{ position: 'relative' }}>
          <input
            type="text"
            value={inputValue}
            onChange={handleInput}
            placeholder="AAPL"
            maxLength={12}
            aria-label="Ticker symbol"
            aria-describedby={inputError ? 'ticker-error' : undefined}
            style={{
              padding: '10px 14px',
              fontSize: 14,
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              border: `1px solid ${inputError ? 'var(--negative)' : 'var(--border-hover)'}`,
              borderRadius: 6,
              background: 'var(--bg-2)',
              color: 'var(--text-primary)',
              width: 160,
              outline: 'none',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          />
          {inputError && (
            <div
              id="ticker-error"
              role="alert"
              style={{
                position: 'absolute', top: '100%', left: 0, marginTop: 4,
                fontSize: 11, color: 'var(--negative)', whiteSpace: 'nowrap',
              }}
            >
              {inputError}
            </div>
          )}
        </div>
        <button
          type="submit"
          disabled={!inputValue.trim()}
          aria-label="Load ticker"
          style={{
            padding: '10px 20px',
            fontSize: 11,
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            border: `1px solid ${inputValue.trim() ? 'var(--accent)' : 'var(--border)'}`,
            borderRadius: 6,
            background: inputValue.trim() ? 'var(--accent)' : 'var(--bg-2)',
            color: inputValue.trim() ? 'var(--bg-0)' : 'var(--text-muted)',
            cursor: inputValue.trim() ? 'pointer' : 'not-allowed',
          }}
        >
          分析
        </button>
      </form>

      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          marginBottom: 10,
        }}>
          {recentTickers.length > 0 ? '最近' : '热门'}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', maxWidth: 360 }}>
          {tickers.slice(0, 8).map((tk) => (
            <button
              key={tk}
              onClick={() => onTickerSelect(tk)}
              aria-label={`Load ${tk}`}
              style={{
                padding: '5px 12px',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                fontWeight: 600,
                color: 'var(--text-secondary)',
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                borderRadius: 4,
                cursor: 'pointer',
                letterSpacing: '0.03em',
              }}
            >
              {tk}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main StocksPage ───────────────────────────────────────────────────────────

export function StocksPage() {
  const { ticker: rawTicker } = useParams<{ ticker?: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Normalise ticker from URL
  const ticker = rawTicker?.toUpperCase() ?? ''

  // Local stores
  const { activeTab, setActiveTab, setCurrentTicker } = useStocksStore()
  const appStore = useAppStore()
  const warnings = appStore.warnings
  const setAiPanelOpen = useUiStore((s) => s.setAiPanelOpen)

  // ── Full analysis pipeline state ──
  const runStream = useRunStream()
  const [fullAnalysisActive, setFullAnalysisActive] = useState(false)
  const [fullAnalysisRunId, setFullAnalysisRunId] = useState<string | null>(null)

  const isFullAnalysisRunning = fullAnalysisActive && (runStream.status === 'running' || runStream.status === 'idle')

  const handleFullAnalysis = useCallback(async () => {
    if (!ticker) return
    setFullAnalysisActive(true)
    try {
      const id = await runStream.startRun('research', ticker)
      setFullAnalysisRunId(id)
    } catch {
      setFullAnalysisActive(false)
    }
  }, [ticker, runStream])

  // When full analysis completes, fetch result and store it
  useEffect(() => {
    if (!fullAnalysisActive) return
    if (runStream.status === 'completed' && fullAnalysisRunId) {
      // Result will be fetched when user clicks "view report" or auto-fetch
      // For now, just keep the overlay showing the completion state
    }
    if (runStream.status === 'failed') {
      // Keep overlay to show error; user can dismiss
    }
  }, [runStream.status, fullAnalysisActive, fullAnalysisRunId])

  const handleViewReport = useCallback(async () => {
    // Fetch the run result and store it in appStore
    if (fullAnalysisRunId) {
      try {
        const resp = await fetch(`${BASE_URL}/api/runs/${fullAnalysisRunId}`)
        if (resp.ok) {
          const detail = await resp.json()
          const structured = detail.result?.structured
          if (structured) {
            // Extract research thesis
            if (structured.thesis) {
              appStore.setResearchResult(structured.thesis)
            }
            // Extract DCF
            const dcfCalc = structured.financial_modeling
            if (dcfCalc) {
              appStore.setDcfResult(dcfCalc, 'research')
            }
          }
        }
      } catch {
        // silently ignore fetch errors
      }
    }
    setFullAnalysisActive(false)
    setActiveTab('overview')
  }, [fullAnalysisRunId, appStore, setActiveTab])

  // AbortController ref — cancelled on ticker change
  const abortRef = useRef<AbortController | null>(null)

  // Sync URL ticker → stores
  useEffect(() => {
    // Cancel previous ticker's in-flight requests
    if (abortRef.current) {
      abortRef.current.abort()
    }
    abortRef.current = new AbortController()

    if (ticker) {
      setCurrentTicker(ticker)
      // Also sync to the legacy appStore so existing chart hooks keep working
      appStore.setTicker(ticker)
      appStore.setPhase('data_ready')
    } else {
      setCurrentTicker('')
    }

    return () => {
      abortRef.current?.abort()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  // Navigate to a ticker
  const handleTickerSelect = useCallback(
    (t: string) => {
      if (!isValidTicker(t)) return
      navigate(`/stocks/${t.toUpperCase()}`)
    },
    [navigate],
  )

  // Cmd+R — refetch current ticker
  const handleGlobalKeyDown = useCallback(
    (e: globalThis.KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      // 1-6 switch tabs
      const tabIndex = parseInt(e.key, 10) - 1
      if (!e.metaKey && !e.ctrlKey && tabIndex >= 0 && tabIndex < TABS.length) {
        e.preventDefault()
        setActiveTab(TABS[tabIndex].key)
        return
      }

      // Cmd+R / Ctrl+R — refetch
      if ((e.metaKey || e.ctrlKey) && e.key === 'r') {
        e.preventDefault()
        if (ticker) {
          void queryClient.invalidateQueries({ queryKey: ['ticker-price', ticker] })
          void queryClient.invalidateQueries({ queryKey: ['ticker-financials', ticker] })
        }
      }
    },
    [ticker, setActiveTab, queryClient],
  )

  useEffect(() => {
    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [handleGlobalKeyDown])

  // Tab content renderer
  const tabContent = useMemo(() => {
    if (!ticker) return null

    switch (activeTab) {
      case 'overview':
        return <OverviewTab />
      case 'financials':
        return <FinancialsTab />
      case 'performance':
        return <PerformanceTab />
      case 'news':
        return <NewsTab />
      case 'valuation':
        return <ValuationTab />
      case 'comps':
        return <PeersTab />
      case 'history':
        return <HistoryTab ticker={ticker} />
      case 'research':
        return <ResearchTab ticker={ticker} />
      default:
        return null
    }
  }, [ticker, activeTab])

  // ── Render ──────────────────────────────────────────────────────────────────

  // No ticker selected — show empty state
  if (!ticker) {
    return (
      <div
        style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
      >
        <EmptyState onTickerSelect={handleTickerSelect} />
        <ToastContainer />
      </div>
    )
  }

  // Invalid ticker format — reject immediately
  if (!isValidTicker(ticker)) {
    return (
      <div
        style={{
          padding: 'var(--sp-8)',
          color: 'var(--negative)',
          fontSize: '0.9rem',
        }}
        role="alert"
      >
        股票代码格式无效：<strong>{ticker}</strong>
        <br />
        <button
          onClick={() => navigate('/stocks')}
          style={{
            marginTop: 'var(--sp-3)',
            background: 'none',
            border: 'none',
            color: 'var(--accent)',
            cursor: 'pointer',
            textDecoration: 'underline',
          }}
        >
          返回搜索
        </button>
      </div>
    )
  }

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* ── Header section ── */}
      <div
        style={{
          padding: '0 var(--sp-5)',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}
      >
        {/* Stock header: ticker + price + change + market cap + watchlist */}
        <ErrorBoundary>
          <StockHeaderNew ticker={ticker} />
        </ErrorBoundary>

        {/* Warnings */}
        {warnings.length > 0 && (
          <ErrorBoundary>
            <WarningBanner warnings={warnings} />
          </ErrorBoundary>
        )}

        {/* Verb toolbar */}
        <ErrorBoundary>
          <VerbToolbar
            ticker={ticker}
            onAskAi={() => setAiPanelOpen(true)}
            onFullAnalysis={handleFullAnalysis}
            fullAnalysisRunning={isFullAnalysisRunning}
            onToolComplete={(tool: ToolName) => {
              // Switch to relevant tab after tool completes
              const tabMap: Record<ToolName, StocksTab> = {
                research:   'overview',
                dcf:        'valuation',
                lbo:        'valuation',
                comps:      'comps',
                catalysts:  'news',
                'ic-memo':  'history',
                ddm:        'valuation',
                earnings:   'financials',
                'ask-ai':   activeTab,
              }
              setActiveTab(tabMap[tool])
            }}
          />
        </ErrorBoundary>

        {/* Thin divider between actions and navigation */}
        <div style={{ height: 1, background: 'var(--border-subtle)', margin: '4px 0 0' }} />

        {/* Tab bar */}
        <StocksTabBar activeTab={activeTab} onTabChange={setActiveTab} />
      </div>

      {/* ── Tab content / Analysis progress overlay ── */}
      {fullAnalysisActive ? (
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: 'var(--sp-4) var(--sp-5)',
          }}
        >
          <AnalysisProgress
            ticker={ticker}
            steps={runStream.steps}
            progress={runStream.progress}
            status={runStream.status}
            error={runStream.error}
            onViewReport={handleViewReport}
          />
        </div>
      ) : (
        <div
          id={`tabpanel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`tab-${activeTab}`}
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: 'var(--sp-4) var(--sp-5)',
          }}
        >
          <ErrorBoundary>
            {tabContent}
          </ErrorBoundary>
        </div>
      )}

      <ToastContainer />
    </div>
  )
}
