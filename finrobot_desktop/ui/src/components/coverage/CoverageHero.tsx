// CoverageHero — the robot-backed ticker search used by the Research homepage.
// Submitting a ticker drills into /stocks/:ticker.

import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SplineHero } from '../SplineHero'
import { isValidTicker, sanitizeTickerInput } from '../../utils/ticker'
import { useI18n, tSync } from '../../i18n'

const TAGLINE_KEYS = [
  'landing.hero.tagline1',
  'landing.hero.tagline2',
  'landing.hero.tagline3',
  'landing.hero.tagline4',
] as const

const HOT_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD']

const TRACE_STEPS = [
  { step: '01', label: 'MARKET', code: 'provider.fetch_quote' },
  { step: '02', label: 'FILINGS', code: 'extractor.sec_10k' },
  { step: '03', label: 'TTM', code: 'normalize.financials' },
  { step: '04', label: 'DCF', code: 'compute.dcf_price' },
  { step: '05', label: 'THESIS', code: 'agent.research_lead' },
]

const CHAPTER_MARKERS = Array.from({ length: 13 }, (_v, i) => String(i + 1).padStart(2, '0'))

export function CoverageHero(): React.ReactElement {
  const navigate = useNavigate()
  const { t } = useI18n()

  const [inputValue, setInputValue] = useState('')
  const [inputError, setInputError] = useState('')

  const handleInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(sanitizeTickerInput(e.target.value))
    setInputError('')
  }, [])

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      const sym = inputValue.trim().toUpperCase()
      if (!sym) return
      if (!isValidTicker(sym)) {
        setInputError(tSync('landing.hero.invalidTicker'))
        return
      }
      navigate(`/stocks/${sym}`)
    },
    [inputValue, navigate],
  )

  return (
    <section
      data-testid="coverage-hero"
      style={{
        position: 'relative',
        height: '100%',
        minHeight: 620,
        overflow: 'hidden',
        padding: '32px 36px 28px',
      }}
    >
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(90deg, var(--border-faint) 1px, transparent 1px), linear-gradient(180deg, var(--border-faint) 1px, transparent 1px)',
          backgroundSize: '72px 72px',
          opacity: 0.42,
          pointerEvents: 'none',
        }}
      />
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(ellipse at 74% 42%, var(--primary-soft) 0%, transparent 38%), linear-gradient(180deg, transparent 0%, var(--bg-void) 88%)',
          pointerEvents: 'none',
        }}
      />

      <div
        aria-hidden
        style={{
          position: 'absolute',
          top: 0,
          right: -28,
          bottom: -18,
          width: 600,
          maxWidth: '58%',
          zIndex: 1,
          opacity: 0.86,
          pointerEvents: 'none',
          maskImage: 'radial-gradient(ellipse at 58% 48%, black 0%, black 66%, transparent 92%)',
          WebkitMaskImage:
            'radial-gradient(ellipse at 58% 48%, black 0%, black 66%, transparent 92%)',
        }}
      >
        <SplineHero variant="backdrop" />
      </div>

      <div
        style={{
          position: 'relative',
          zIndex: 3,
          width: 690,
          maxWidth: '66%',
          marginTop: 72,
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 14,
            color: 'var(--accent-cyan)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            textTransform: 'uppercase',
          }}
        >
          <span
            className="cosmic-pulse-dot"
            style={{ background: 'var(--accent-cyan)', boxShadow: 'var(--glow-cyan)' }}
            aria-hidden
          />
          {t('landing.hero.cockpitLabel')}
        </div>

        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 56,
            letterSpacing: '8px',
            background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            color: 'transparent',
            textShadow: 'var(--glow-blue)',
          }}
        >
          FINROBOT
        </div>
        <div
          aria-hidden
          style={{
            position: 'relative',
            height: 24,
            marginTop: 8,
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            letterSpacing: 2,
            color: 'var(--accent-cyan)',
            textShadow: 'var(--glow-cyan)',
          }}
        >
          <span
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-start',
              opacity: 0.32,
            }}
          >
            {t(TAGLINE_KEYS[3])}
          </span>
          {TAGLINE_KEYS.map((key, i) => (
            <span
              key={key}
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-start',
                animation: 'cosmic-morph 12s ease-in-out infinite',
                animationDelay: `${i * 3}s`,
                opacity: 0,
              }}
            >
              {t(key)}
            </span>
          ))}
        </div>

        <form
          onSubmit={handleSubmit}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
            width: '100%',
            marginTop: 30,
          }}
        >
          <div className="halo-input" style={{ width: '100%', padding: 1 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 14,
                minHeight: 74,
                padding: '12px 18px 12px 22px',
                background: 'var(--bg-input)',
                borderRadius: 'var(--radius-md)',
                boxShadow: 'var(--glow-blue-soft)',
              }}
            >
              <span style={{ color: 'var(--text-muted)', fontSize: 18 }} aria-hidden>
                ⌕
              </span>
              <input
                type="text"
                value={inputValue}
                onChange={handleInput}
                placeholder={t('landing.hero.searchPlaceholder')}
                maxLength={12}
                aria-label="Ticker symbol"
                aria-describedby={inputError ? 'coverage-hero-ticker-error' : undefined}
                style={{
                  flex: 1,
                  minWidth: 0,
                  fontSize: 20,
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 700,
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
                  minWidth: 112,
                  padding: '13px 20px',
                  fontSize: 12,
                  opacity: inputValue.trim() ? 1 : 0.4,
                  cursor: inputValue.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                {t('landing.hero.analyze')}
              </button>
            </div>
          </div>
          {inputError && (
            <div
              id="coverage-hero-ticker-error"
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
        </form>

        <div style={{ marginTop: 18 }}>
          <div
            style={{
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-display)',
              fontSize: 11,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              marginBottom: 10,
            }}
          >
            {t('coverage.starter.quickPick')}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {HOT_TICKERS.map((tk) => (
              <button
                key={tk}
                type="button"
                className="coverage-hover-btn"
                onClick={() => navigate(`/stocks/${tk}`)}
                aria-label={t('coverage.starter.researchTicker', { ticker: tk })}
                style={{
                  padding: '7px 16px',
                  borderRadius: 'var(--radius-pill)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 13,
                  cursor: 'pointer',
                  background: 'var(--bg-card-overlay)',
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border-soft)',
                }}
              >
                {tk}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 36,
          right: 36,
          bottom: 28,
          zIndex: 3,
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 620px) 340px',
          gap: 18,
          justifyContent: 'space-between',
          alignItems: 'stretch',
        }}
      >
        <TraceConsole title={t('landing.hero.traceRail')} />
        <ChapterMatrix title={t('landing.hero.chapterMatrix')} />
      </div>
    </section>
  )
}

function TraceConsole({ title }: { title: string }): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${TRACE_STEPS.length}, minmax(0, 1fr))`,
        gap: 0,
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        background: 'var(--bg-card-overlay)',
        backdropFilter: 'blur(14px)',
        overflow: 'hidden',
      }}
    >
      {TRACE_STEPS.map((item, index) => (
        <div
          key={item.code}
          style={{
            position: 'relative',
            padding: '14px 16px 16px',
            minHeight: 94,
            borderLeft: index === 0 ? 'none' : '1px solid var(--border-faint)',
          }}
        >
          {index === 0 && (
            <div
              style={{
                color: 'var(--accent-cyan)',
                fontFamily: 'var(--font-display)',
                fontSize: 11,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                marginBottom: 10,
              }}
            >
              {title}
            </div>
          )}
          {index !== 0 && <div style={{ height: 23, marginBottom: 10 }} />}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
            }}
          >
            <span style={{ color: 'var(--accent-cyan)' }}>{item.step}</span>
            <span>{item.label}</span>
          </div>
          <div
            style={{
              marginTop: 10,
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {item.code}
          </div>
          <div
            aria-hidden
            style={{
              position: 'absolute',
              left: 16,
              right: 16,
              bottom: 12,
              height: 2,
              background:
                index === TRACE_STEPS.length - 1
                  ? 'var(--accent-cyan)'
                  : 'linear-gradient(90deg, var(--accent-cyan), var(--border-soft))',
              boxShadow: 'var(--glow-cyan)',
            }}
          />
        </div>
      ))}
    </div>
  )
}

function ChapterMatrix({ title }: { title: string }): React.ReactElement {
  return (
    <div
      style={{
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        background: 'var(--bg-card-overlay)',
        backdropFilter: 'blur(14px)',
        padding: 16,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          gap: 12,
          marginBottom: 12,
        }}
      >
        <span
          style={{
            color: 'var(--accent-cyan)',
            fontFamily: 'var(--font-display)',
            fontSize: 11,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
          }}
        >
          {title}
        </span>
        <span
          style={{
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-display)',
            fontSize: 28,
            lineHeight: 1,
          }}
        >
          13
        </span>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(7, 1fr)',
          gap: 7,
        }}
      >
        {CHAPTER_MARKERS.map((n) => (
          <span
            key={n}
            style={{
              height: 28,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-soft)',
              background: 'var(--primary-soft)',
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
            }}
          >
            {n}
          </span>
        ))}
      </div>
    </div>
  )
}
