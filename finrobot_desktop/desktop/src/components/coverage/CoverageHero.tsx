// CoverageHero — the robot-backed ticker search used by the Research homepage.
// Submitting a ticker drills into /stocks/:ticker.
//
// Layout: a three-band "cinematic console" —
//   BAND 1  status rail   — morphing value-prop tagline + AI·online (brand
//                           wordmark stays in the global TitleBar, not repeated)
//   BAND 2  command core  — Spline robot spotlight behind a single glowing
//                           search bar + hot-ticker pills (the one action)
//   BAND 3  pipeline flow — "what runs when you hit Analyze": the REAL 8-stage
//                           research pipeline as a left→right metro line, ending
//                           in the report; one traceability guarantee beneath
// The robot is centered (translateX(-50%)) and confined to BAND 2 so it stays
// the luminous subject and is never hidden behind the right chat panel.

import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SplineHero } from '../SplineHero'
import { isValidTicker, sanitizeTickerInput } from '../../utils/ticker'
import { useI18n, tSync } from '../../i18n'

const HOT_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD']

// The REAL equity-research pipeline stages, in execution order — mirrors
// finrobot/engine/pipelines/equity_research.py create_*_pipeline().steps
// (data_collection · catalyst_analysis · peer_analysis · financial_modeling ·
//  ownership_governance_analysis · technical_analysis · thesis · report).
// Shown as a left→right flow so "按下分析后会跑什么" is literally true, not a
// decorative placeholder. The last stage (the report) is the highlighted output.
const STAGE_KEYS = [
  'landing.hero.stage.data',
  'landing.hero.stage.catalyst',
  'landing.hero.stage.peers',
  'landing.hero.stage.model',
  'landing.hero.stage.ownership',
  'landing.hero.stage.technical',
  'landing.hero.stage.thesis',
  'landing.hero.stage.report',
] as const

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

      {/* ── BAND 3 · pipeline flow — the real 8-stage research pipeline ────────── */}
      <PipelineFlow
        caption={t('landing.hero.deckCaption')}
        stages={STAGE_KEYS.map((k) => t(k))}
        traceable={t('landing.hero.traceableLabel')}
        sourcedNote={t('landing.hero.sourcedNote')}
      />
    </section>
  )
}

interface PipelineFlowProps {
  caption: string
  stages: string[]
  traceable: string
  sourcedNote: string
}

// A left→right "metro line": the real pipeline stages as connected nodes on a
// glowing rail, ending in the highlighted report (the deliverable). One quiet
// guarantee line beneath. No fabricated function names, no fake numbers.
function PipelineFlow(props: PipelineFlowProps): React.ReactElement {
  const half = `${100 / props.stages.length / 2}%`
  return (
    <div
      style={{
        position: 'relative',
        zIndex: 3,
        margin: '0 36px 26px',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        background: 'var(--bg-card-overlay)',
        backdropFilter: 'blur(14px)',
        overflow: 'hidden',
      }}
    >
      {/* caption — ties the flow to the search above it */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '11px 24px',
          borderBottom: '1px solid var(--border-faint)',
          color: 'var(--accent-cyan)',
          fontFamily: 'var(--font-display)',
          fontSize: 11,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
        }}
      >
        <span aria-hidden>▸</span>
        {props.caption}
      </div>

      {/* the rail */}
      <div style={{ position: 'relative', display: 'flex', padding: '26px 28px 22px' }}>
        <div
          aria-hidden
          style={{
            position: 'absolute',
            top: 31,
            left: `calc(28px + ${half})`,
            right: `calc(28px + ${half})`,
            height: 2,
            background: 'linear-gradient(90deg, var(--accent-cyan), var(--secondary))',
            boxShadow: 'var(--glow-cyan)',
            opacity: 0.55,
          }}
        />
        {props.stages.map((label, i) => {
          const isLast = i === props.stages.length - 1
          return (
            <div
              key={label}
              style={{
                flex: 1,
                minWidth: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 11,
                  height: 11,
                  borderRadius: '50%',
                  background: isLast ? 'var(--accent-cyan)' : 'var(--bg-void)',
                  border: '2px solid var(--accent-cyan)',
                  boxShadow: isLast ? 'var(--glow-cyan)' : 'none',
                  zIndex: 1,
                }}
              />
              <span
                style={{
                  fontFamily: 'var(--font-body)',
                  fontSize: 11,
                  fontWeight: isLast ? 600 : 400,
                  letterSpacing: '0.02em',
                  color: isLast ? 'var(--text-primary)' : 'var(--text-secondary)',
                  textAlign: 'center',
                  whiteSpace: 'nowrap',
                }}
              >
                {label}
              </span>
            </div>
          )
        })}
      </div>

      {/* guarantee line */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '11px 28px',
          borderTop: '1px solid var(--border-faint)',
          fontFamily: 'var(--font-body)',
          fontSize: 12,
          color: 'var(--text-secondary)',
        }}
      >
        <span aria-hidden style={{ color: 'var(--accent-cyan)' }}>
          ◆
        </span>
        <span style={{ color: 'var(--text-primary)' }}>{props.traceable}</span>
        <span style={{ color: 'var(--text-muted)' }}>· {props.sourcedNote}</span>
      </div>
    </div>
  )
}
