// CoverageHero — the robot-backed ticker search used by the Research homepage.
// Submitting a ticker drills into /stocks/:ticker.
//
// Layout: a three-band "cinematic console" —
//   BAND 1  status rail   — morphing value-prop tagline + AI·online (brand
//                           wordmark stays in the global TitleBar, not repeated)
//   BAND 2  command core  — Spline robot spotlight behind a single glowing
//                           search bar + hot-ticker pills (the one action)
//   BAND 3  proof deck    — "what runs when you hit Analyze": function trace
//                           (no fake prices), every-number-traceable, IC debate
// The robot is centered (translateX(-50%)) and confined to BAND 2 so it stays
// the luminous subject and is never hidden behind the right chat panel.

import { Fragment, useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SplineHero } from '../SplineHero'
import { isValidTicker, sanitizeTickerInput } from '../../utils/ticker'
import { useI18n, tSync } from '../../i18n'

const HOT_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD']

// Deterministic pipeline trace shown in the proof deck. The `code` strings are
// REAL function identifiers from the compute layer — the credibility flex is
// "every number is computed by code you can name", so we show the method path,
// never a price. Code identifiers stay English (they ARE code); the human-
// readable stage label is localized so the zh homepage reads as Chinese.
const TRACE_STEPS = [
  { step: '01', labelKey: 'landing.hero.trace.market', code: 'provider.fetch_quote' },
  { step: '02', labelKey: 'landing.hero.trace.filings', code: 'extractor.sec_10k' },
  { step: '03', labelKey: 'landing.hero.trace.ttm', code: 'normalize.financials' },
  { step: '04', labelKey: 'landing.hero.trace.dcf', code: 'compute.dcf_price' },
  { step: '05', labelKey: 'landing.hero.trace.thesis', code: 'agent.research_lead' },
]

const CONVICTION_FILLED = 4 // illustrative Bull/Bear conviction (4 of 5 segments)
const CONVICTION_SCORE = 72

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
    (e: React.FormEvent<HTMLFormElement>) => {
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
        display: 'grid',
        gridTemplateRows: '52px 1fr auto',
      }}
    >
      {/* ── Atmosphere (z0) — faint grid + centered floor-glow + bottom vignette ── */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(90deg, var(--border-faint) 1px, transparent 1px), linear-gradient(180deg, var(--border-faint) 1px, transparent 1px)',
          backgroundSize: '76px 76px',
          opacity: 0.3,
          pointerEvents: 'none',
        }}
      />
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(ellipse 46% 40% at 50% 40%, var(--primary-soft) 0%, transparent 70%), linear-gradient(180deg, transparent 52%, var(--bg-void) 100%)',
          pointerEvents: 'none',
        }}
      />

      {/* ── Spline robot spotlight (z1) — centered, confined to the command band ── */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          top: 36,
          bottom: 196,
          left: '50%',
          transform: 'translateX(-50%)',
          width: 'min(540px, 58%)',
          zIndex: 1,
          opacity: 0.8,
          pointerEvents: 'none',
          // Spotlight biased to the upper body so the robot PRESIDES over the
          // search bar (head/torso) and its legs fade out before the pills/deck
          // rather than bleeding through them.
          maskImage:
            'radial-gradient(ellipse 56% 56% at 50% 39%, black 0%, black 48%, transparent 80%)',
          WebkitMaskImage:
            'radial-gradient(ellipse 56% 56% at 50% 39%, black 0%, black 48%, transparent 80%)',
        }}
      >
        <SplineHero variant="backdrop" />
      </div>

      {/* ── BAND 1 · status rail — a single clean value-prop line ────────────── */}
      {/* Brand wordmark stays in the global TitleBar (not repeated here). One
          static tagline (no morphing stack → no ghost-overlap), with a cyan
          accent dot. No "AI online" badge: the assistant is on-demand, not a
          live process, so a liveness claim would be dishonest. */}
      <div
        style={{
          position: 'relative',
          zIndex: 4,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '0 36px',
          borderBottom: '1px solid var(--border-faint)',
          background: 'var(--bg-card-overlay)',
          backdropFilter: 'blur(14px)',
        }}
      >
        <span
          className="cosmic-pulse-dot"
          style={{
            background: 'var(--accent-cyan)',
            boxShadow: 'var(--glow-cyan)',
            flexShrink: 0,
          }}
          aria-hidden
        />
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 16,
            letterSpacing: 2,
            color: 'var(--text-secondary)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {t('landing.hero.tagline4')}
        </span>
      </div>

      {/* ── BAND 2 · command core ────────────────────────────────────────────── */}
      <div
        style={{
          position: 'relative',
          zIndex: 3,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 36px',
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 22,
            color: 'var(--accent-cyan)',
            fontFamily: 'var(--font-display)',
            fontSize: 11,
            letterSpacing: '0.12em',
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

        <form
          onSubmit={handleSubmit}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 10,
            width: 'min(640px, 100%)',
          }}
        >
          <div className="halo-input" style={{ width: '100%', padding: 1 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 14,
                minHeight: 76,
                padding: '12px 16px 12px 22px',
                background: 'var(--bg-input)',
                borderRadius: 'var(--radius-md)',
                boxShadow: 'var(--glow-blue)',
              }}
            >
              <span
                style={{
                  color: 'var(--accent-cyan)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 18,
                  textShadow: 'var(--glow-cyan)',
                }}
                aria-hidden
              >
                {'>'}
              </span>
              <input
                type="text"
                value={inputValue}
                onChange={handleInput}
                placeholder={t('landing.hero.searchPlaceholder')}
                maxLength={12}
                aria-label={t('landing.hero.tickerAria')}
                aria-describedby={inputError ? 'coverage-hero-ticker-error' : undefined}
                style={{
                  flex: 1,
                  minWidth: 0,
                  fontSize: 18,
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
                aria-label={t('landing.hero.analyze')}
                className="btn-shimmer"
                style={{
                  minWidth: 120,
                  padding: '13px 22px',
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

        <div style={{ marginTop: 22, display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            style={{
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-display)',
              fontSize: 10,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
            }}
          >
            {t('coverage.starter.quickPick')}
          </span>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {HOT_TICKERS.map((tk, i) => (
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
                  animation: 'cosmic-pull-up 0.32s ease both',
                  animationDelay: `${i * 0.04}s`,
                }}
              >
                {tk}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── BAND 3 · proof deck ──────────────────────────────────────────────── */}
      <ProofDeck
        deckCaption={t('landing.hero.deckCaption')}
        traceTitle={t('landing.hero.traceRail')}
        reportNode={t('landing.hero.reportNode')}
        traceableLabel={t('landing.hero.traceableLabel')}
        sourcedNote={t('landing.hero.sourcedNote')}
        icDebate={t('landing.hero.icDebate')}
        bull={t('landing.hero.bull')}
        bear={t('landing.hero.bear')}
      />
    </section>
  )
}

interface ProofDeckProps {
  deckCaption: string
  traceTitle: string
  reportNode: string
  traceableLabel: string
  sourcedNote: string
  icDebate: string
  bull: string
  bear: string
}

function ProofDeck(props: ProofDeckProps): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      style={{
        position: 'relative',
        zIndex: 3,
        margin: '0 36px 24px',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        background: 'var(--bg-card-overlay)',
        backdropFilter: 'blur(14px)',
        overflow: 'hidden',
      }}
    >
      {/* caption strip — ties the deck to the search above it */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '10px 18px',
          borderBottom: '1px solid var(--border-faint)',
          color: 'var(--accent-cyan)',
          fontFamily: 'var(--font-display)',
          fontSize: 11,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
        }}
      >
        <span aria-hidden>▸</span>
        {props.deckCaption}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 0.9fr) minmax(0, 1.3fr)',
        }}
      >
        {/* Cell 1 — function trace as a clean vertical pipeline log: step + the
            localized stage label, then the REAL compute function (full, never
            truncated), aligned in two columns down a cyan pipeline spine. */}
        <div style={{ padding: '14px 18px', minHeight: 124 }}>
          <CellLabel>{props.traceTitle}</CellLabel>
          <div
            style={{
              marginTop: 12,
              display: 'grid',
              gridTemplateColumns: 'max-content 1fr',
              columnGap: 16,
              rowGap: 8,
              paddingLeft: 12,
              borderLeft: '2px solid var(--accent-cyan)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
            }}
          >
            {TRACE_STEPS.map((item) => (
              <Fragment key={item.code}>
                <span style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                  <span style={{ color: 'var(--accent-cyan)' }}>{item.step}</span>{' '}
                  {t(item.labelKey)}
                </span>
                <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  {item.code}
                </span>
              </Fragment>
            ))}
          </div>
          <div
            style={{
              marginTop: 12,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
            }}
          >
            <span aria-hidden style={{ color: 'var(--accent-cyan)' }}>
              →
            </span>
            {props.reportNode}
          </div>
        </div>

        {/* Cell 2 — every number traceable (SourcedNumber), no fake price */}
        <div
          style={{
            padding: '14px 18px',
            minHeight: 124,
            borderLeft: '1px solid var(--border-faint)',
          }}
        >
          <CellLabel>{props.traceableLabel}</CellLabel>
          <div
            style={{
              marginTop: 14,
              fontFamily: 'var(--font-display)',
              fontSize: 34,
              lineHeight: 1,
              color: 'var(--text-primary)',
              textShadow: 'var(--glow-cyan)',
            }}
          >
            100%
          </div>
          <div
            style={{
              marginTop: 10,
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              lineHeight: 1.5,
            }}
          >
            {props.sourcedNote}
          </div>
        </div>

        {/* Cell 3 — Bull/Bear IC debate + conviction */}
        <div
          style={{
            padding: '14px 18px',
            minHeight: 124,
            borderLeft: '1px solid var(--border-faint)',
          }}
        >
          <CellLabel>{props.icDebate}</CellLabel>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 14 }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 28,
                lineHeight: 1,
                color: 'var(--text-primary)',
              }}
            >
              {CONVICTION_SCORE}
            </span>
            <span style={{ display: 'flex', gap: 4 }} aria-hidden>
              {Array.from({ length: 5 }, (_v, i) => (
                <span
                  key={i}
                  style={{
                    width: 18,
                    height: 8,
                    borderRadius: 2,
                    background: i < CONVICTION_FILLED ? 'var(--primary)' : 'var(--border-soft)',
                    boxShadow: i < CONVICTION_FILLED ? 'var(--glow-blue-soft)' : 'none',
                  }}
                />
              ))}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
            <ConvictionTag color="var(--success)">{props.bull}</ConvictionTag>
            <ConvictionTag color="var(--danger)">{props.bear}</ConvictionTag>
          </div>
        </div>
      </div>
    </div>
  )
}

function CellLabel({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <span
      style={{
        color: 'var(--accent-cyan)',
        fontFamily: 'var(--font-display)',
        fontSize: 11,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
      }}
    >
      {children}
    </span>
  )
}

function ConvictionTag({
  color,
  children,
}: {
  color: string
  children: React.ReactNode
}): React.ReactElement {
  return (
    <span
      style={{
        padding: '3px 10px',
        borderRadius: 'var(--radius-pill)',
        border: `1px solid ${color}`,
        color,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
      }}
    >
      {children}
    </span>
  )
}
