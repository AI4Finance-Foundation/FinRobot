// Ticker workspace hero — cosmic redesign (spec §3.2 + 5.4).
//
// Layout: left 60% (breadcrumb / symbol / price / actions) + right 40%
// (SplineHero AI Analyst). Replaces the v5 slim 110px sticky bar; the
// hero now scrolls with content. PipelineProgressPanel takes over the
// "current status" duty that the sticky bar used to provide.

import { useEffect, useRef, useState } from 'react'
import { useTickerPrice } from '../hooks/useTickerData'
import { useV5ArtifactTimeline } from '../hooks/useV5Artifacts'
import { useStocksStore } from '../stores/stocksStore'
import { useRunStreamStore, selectRunByTicker } from '../stores/runStreamStore'
import { useToastStore } from '../stores/toastStore'
import { SplineHero } from '../components/SplineHero'
import { RunAnalysisDropdown } from './RunAnalysisDropdown'

const ARTIFACT_TYPE_TO_PIPELINE: Record<string, string> = {
  equity_research: 'research',
  ic_memo: 'ic-memo',
  earnings_analysis: 'earnings',
  dcf: 'dcf',
  lbo: 'lbo',
  ddm: 'ddm',
  comps: 'comps',
}

const TAGLINES = [
  '确定性计算 · LLM 叙事',
  'NUMBER FIRST · NARRATIVE SECOND',
  '每一个数字 · 都能追溯到函数调用',
  'AI ANALYST · 持续工作中',
] as const

function StarIcon({ filled, size = 14 }: { filled?: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? '#F59E0B' : 'none'} stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  )
}

function RefreshIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  )
}

function ChevronDownIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

interface Props {
  ticker: string
}

export function TickerHero({ ticker }: Props): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)
  const watchlist = useStocksStore((s) => s.watchlist)
  const toggleWatchlist = useStocksStore((s) => s.toggleWatchlist)
  const isWatched = watchlist.has(ticker)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownWrapperRef = useRef<HTMLDivElement>(null)

  const runState = useRunStreamStore(selectRunByTicker(ticker))
  const startRun = useRunStreamStore((s) => s.startRun)
  const addToast = useToastStore((s) => s.addToast)
  const { data: artifactTimeline } = useV5ArtifactTimeline(ticker)
  const lastArtifactType = artifactTimeline?.[0]?.type
  const fallbackPipeline = lastArtifactType
    ? ARTIFACT_TYPE_TO_PIPELINE[lastArtifactType] ?? 'research'
    : 'research'
  const lastPipeline = runState?.pipelineType ?? fallbackPipeline
  const rerunBusy = runState?.status === 'running'

  useEffect(() => {
    if (!dropdownOpen) return
    function onDocMouseDown(e: MouseEvent) {
      if (!dropdownWrapperRef.current) return
      if (e.target instanceof Node && dropdownWrapperRef.current.contains(e.target)) return
      setDropdownOpen(false)
    }
    document.addEventListener('mousedown', onDocMouseDown)
    return () => document.removeEventListener('mousedown', onDocMouseDown)
  }, [dropdownOpen])

  async function handleRerun(): Promise<void> {
    if (rerunBusy) return
    try {
      const runId = await startRun(lastPipeline, ticker)
      addToast({
        type: 'success',
        title: `${ticker} ${lastPipeline} 已重跑`,
        description: `run_id: ${runId.slice(0, 12)} · 顶部进度面板会逐步更新`,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      addToast({ type: 'error', title: `${ticker} 重跑失败`, description: msg })
    }
  }

  const current = price?.current_price
  const changePct = price?.change_pct
  const changeAbs = price?.change ?? undefined
  const isUp = typeof changePct === 'number' && changePct >= 0

  return (
    <header
      data-testid="ticker-hero"
      style={{
        position: 'relative',
        padding: '32px 32px 24px',
        background: 'linear-gradient(180deg, rgba(15,15,34,0.4) 0%, transparent 100%)',
        borderBottom: '1px solid var(--border-faint)',
      }}
    >
      <div
        style={{
          maxWidth: 1600,
          margin: '0 auto',
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)',
          gap: 32,
          alignItems: 'stretch',
          minHeight: 460,
        }}
      >
        {/* Left 60% — symbol / price / actions */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, minWidth: 0 }}>
          <Breadcrumb ticker={ticker} />

          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, flexWrap: 'wrap' }}>
              <span
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 80,
                  letterSpacing: 6,
                  color: 'var(--text-primary)',
                  lineHeight: 1,
                  textShadow: '0 0 30px rgba(59,130,246,0.35)',
                }}
              >
                {ticker}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  color: 'var(--text-muted)',
                  padding: '4px 10px',
                  border: '1px solid var(--border-soft)',
                  borderRadius: 6,
                  letterSpacing: '0.08em',
                }}
              >
                <span className="cosmic-pulse-dot" style={{ marginRight: 6 }} />
                LIVE · NASDAQ
              </span>
            </div>
            <MorphTagline />
          </div>

          {/* Price block */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 18, flexWrap: 'wrap' }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 56,
                fontWeight: 500,
                letterSpacing: '-1px',
                color: 'var(--text-primary)',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {typeof current === 'number' ? `$${current.toFixed(2)}` : '—'}
            </span>
            {typeof changePct === 'number' && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 17,
                  color: isUp ? 'var(--success)' : 'var(--danger)',
                  padding: '6px 12px',
                  background: isUp ? 'rgba(22,163,74,0.12)' : 'rgba(220,38,38,0.12)',
                  border: `1px solid ${isUp ? 'rgba(22,163,74,0.32)' : 'rgba(220,38,38,0.32)'}`,
                  borderRadius: 8,
                  boxShadow: `0 0 16px ${isUp ? 'var(--success-glow)' : 'var(--danger-glow)'}`,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {isUp ? '↑' : '↓'}{' '}
                {typeof changeAbs === 'number' && (
                  <>
                    {isUp ? '+' : ''}
                    {changeAbs.toFixed(2)} ·{' '}
                  </>
                )}
                {isUp ? '+' : ''}
                {changePct.toFixed(2)}%
              </span>
            )}
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 4 }}>
            <div ref={dropdownWrapperRef} style={{ position: 'relative' }}>
              <button
                type="button"
                data-testid="run-analysis-trigger"
                className="btn-shimmer"
                onClick={() => setDropdownOpen((v) => !v)}
              >
                运行完整分析
                <ChevronDownIcon size={14} />
              </button>
              {dropdownOpen && (
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 'calc(100% + 6px)',
                    zIndex: 50,
                  }}
                >
                  <RunAnalysisDropdown
                    ticker={ticker}
                    onLaunched={() => setDropdownOpen(false)}
                  />
                </div>
              )}
            </div>

            <button
              type="button"
              data-testid="watchlist-toggle"
              onClick={() => toggleWatchlist(ticker)}
              style={ghostBtnStyle(isWatched)}
              title={isWatched ? '从自选股移除' : '加入自选股'}
            >
              <StarIcon filled={isWatched} size={14} />
              {isWatched ? '已加入自选' : '加入自选'}
            </button>

            <button
              type="button"
              data-testid="rerun-latest"
              onClick={handleRerun}
              disabled={rerunBusy}
              style={{ ...ghostBtnStyle(false), opacity: rerunBusy ? 0.45 : 1, cursor: rerunBusy ? 'not-allowed' : 'pointer' }}
              title={rerunBusy ? '当前还有分析在跑' : `重跑：${lastPipeline}`}
            >
              <RefreshIcon size={13} /> {rerunBusy ? '正在跑' : `重跑 ${lastPipeline}`}
            </button>
          </div>
        </div>

        {/* Right 40% — Spline AI Analyst */}
        <div style={{ position: 'relative', minHeight: 420 }}>
          <SplineHero variant="hero" />
        </div>
      </div>
    </header>
  )
}

// ── Breadcrumb ─────────────────────────────────────────────────────────────
function Breadcrumb({ ticker }: { ticker: string }): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-muted)',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
      }}
    >
      <span>FINAGENT</span>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <span>Stocks</span>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <span style={{ color: 'var(--accent-cyan)' }}>{ticker}</span>
    </div>
  )
}

// ── Morph tagline (4-phrase cycle) ────────────────────────────────────────
function MorphTagline(): React.ReactElement {
  return (
    <div
      aria-hidden
      style={{
        position: 'relative',
        height: 28,
        marginTop: 12,
        maxWidth: 560,
        overflow: 'hidden',
        fontFamily: 'var(--font-display)',
        fontSize: 15,
        letterSpacing: 1.6,
        color: 'var(--accent-cyan)',
        textShadow: '0 0 12px rgba(34,211,238,0.5)',
      }}
    >
      {TAGLINES.map((t, i) => (
        <span
          key={t}
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            animation: `cosmic-morph 12s ease-in-out infinite`,
            animationDelay: `${i * 3}s`,
            opacity: 0,
          }}
        >
          {t}
        </span>
      ))}
    </div>
  )
}

function ghostBtnStyle(highlighted: boolean): React.CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    padding: '11px 18px',
    background: highlighted ? 'rgba(245,158,11,0.10)' : 'rgba(15,15,34,0.6)',
    color: highlighted ? '#F59E0B' : 'var(--text-secondary)',
    border: `1px solid ${highlighted ? 'rgba(245,158,11,0.32)' : 'var(--border-soft)'}`,
    borderRadius: 10,
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    cursor: 'pointer',
    transition: 'all 0.2s',
  }
}
