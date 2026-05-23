// StocksLandingHero — search-first landing hero per spec §2.2.
//
// Replaces the bare-bones v5 landing. Layout (top to bottom):
//   1. Cosmic title block (Audiowide FINAGENT + morph tagline)
//   2. Halo-bordered ticker search input with quick chips
//   3. Hit-rate banner (30d / 90d / all switcher)
//   4. Recent-research strip (horizontal scroll)
//
// Stage A backend gave us /api/dashboard/hit-rate and /api/dashboard/
// recent-research; both hooks fail gracefully (empty state) when there are
// no artifacts yet — no fake numbers.

import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { isValidTicker } from '../../stores/stocksStore'
import { HitRateBanner } from './HitRateBanner'
import { RecentResearchStrip } from './RecentResearchStrip'
import { HotTickerChips } from './HotTickerChips'
import { DashboardSkeleton } from './DashboardSkeleton'
import { SplineHero } from '../../components/SplineHero'
import { useQuotesWarmed } from '../../hooks/useQuotesWarmed'

const TAGLINES = [
  '确定性计算 · LLM 叙事',
  'NUMBER FIRST · NARRATIVE SECOND',
  'AI ANALYST · 持续工作中',
  '每一个数字 · 都能追溯到函数调用',
] as const

export function StocksLandingHero(): React.ReactElement {
  const navigate = useNavigate()

  const [inputValue, setInputValue] = useState('')
  const [inputError, setInputError] = useState('')

  // While the lifespan QuoteCache warmup is still running the dashboard
  // endpoints (hit-rate, recent-research) would fall through to a cold
  // yfinance fetch and block ~2-4s. Skeleton until backend reports the
  // warmup is done.
  const { data: warmStatus } = useQuotesWarmed()
  const dashboardReady = warmStatus?.warmed ?? false

  const handleInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value.toUpperCase().replace(/[^A-Z0-9.-]/g, '')
    setInputValue(val)
    setInputError('')
  }, [])

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      const sym = inputValue.trim().toUpperCase()
      if (!sym) return
      if (!isValidTicker(sym)) {
        setInputError('代码格式不对 · 用 1-12 个字母 / 数字 / .-')
        return
      }
      navigate(`/stocks/${sym}`)
    },
    [inputValue, navigate],
  )

  return (
    <div
      data-testid="stocks-landing"
      style={{
        position: 'relative',
        zIndex: 1,
        minHeight: '100%',
        padding: '64px 32px 96px',
        maxWidth: 1280,
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 56,
      }}
    >
      {/* Backdrop Spline robot — sits behind the title block as the
          "AI Analyst at rest" mascot. pointer-events:none so the title
          and search input always win the click. */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          top: -40,
          right: -120,
          width: 640,
          height: 520,
          maxWidth: '60vw',
          zIndex: 0,
          opacity: 0.55,
          pointerEvents: 'none',
          maskImage:
            'radial-gradient(ellipse at 60% 45%, black 0%, black 60%, transparent 90%)',
          WebkitMaskImage:
            'radial-gradient(ellipse at 60% 45%, black 0%, black 60%, transparent 90%)',
        }}
      >
        <SplineHero variant="backdrop" />
      </div>

      {/* Title block */}
      <div style={{ textAlign: 'center', position: 'relative', zIndex: 2 }}>
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 64,
            letterSpacing: '8px',
            background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            color: 'transparent',
            textShadow: 'var(--glow-blue)',
          }}
        >
          FINAGENT
        </div>
        <div
          aria-hidden
          style={{
            position: 'relative',
            height: 26,
            marginTop: 8,
            fontFamily: 'var(--font-display)',
            fontSize: 14,
            letterSpacing: 1.8,
            color: 'var(--accent-cyan)',
            textShadow: 'var(--glow-cyan)',
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
                justifyContent: 'center',
                animation: 'cosmic-morph 12s ease-in-out infinite',
                animationDelay: `${i * 3}s`,
                opacity: 0,
              }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>

      {/* Search box */}
      <form
        onSubmit={handleSubmit}
        style={{
          position: 'relative',
          zIndex: 2,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 18,
        }}
      >
        <div
          className="halo-input"
          style={{
            width: 'min(560px, 100%)',
            padding: 1,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 18px',
              background: 'rgba(10,10,24,0.7)',
              borderRadius: 'var(--radius-md)',
            }}
          >
            <span style={{ color: 'var(--text-muted)', fontSize: 14 }} aria-hidden>⌕</span>
            <input
              type="text"
              value={inputValue}
              onChange={handleInput}
              placeholder="输入股票代码 · AAPL / NVDA / TSLA"
              maxLength={12}
              aria-label="Ticker symbol"
              aria-describedby={inputError ? 'ticker-error' : undefined}
              style={{
                flex: 1,
                fontSize: 16,
                fontFamily: 'var(--font-mono)',
                fontWeight: 600,
                background: 'transparent',
                color: 'var(--text-primary)',
                border: 'none',
                outline: 'none',
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
              }}
            />
            <button
              type="submit"
              disabled={!inputValue.trim()}
              aria-label="Load ticker"
              className="btn-shimmer"
              style={{
                padding: '8px 18px',
                fontSize: 11,
                opacity: inputValue.trim() ? 1 : 0.4,
                cursor: inputValue.trim() ? 'pointer' : 'not-allowed',
              }}
            >
              分析
            </button>
          </div>
        </div>
        {inputError && (
          <div
            id="ticker-error"
            role="alert"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--danger)',
            }}
          >
            {inputError}
          </div>
        )}
        <HotTickerChips />
      </form>

      {/* Dashboard surfaces (hit-rate + recent research) depend on cached
          quotes; skeleton until the lifespan warmup finishes so we never
          trigger a cold yfinance fetch from inside a user-facing request. */}
      {dashboardReady ? (
        <>
          <HitRateBanner />
          <RecentResearchStrip />
        </>
      ) : (
        <DashboardSkeleton />
      )}
    </div>
  )
}
