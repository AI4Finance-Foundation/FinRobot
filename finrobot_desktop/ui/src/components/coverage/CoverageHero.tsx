// CoverageHero — a compact hero band atop the Coverage Desk (the desktop's
// first screen). Brings back the two elements analysts liked on the retired
// /stocks landing: the Spline "AI analyst" robot backdrop and the big halo
// ticker search. Kept SHORT on purpose — it sits above a dense Coverage table,
// so no hit-rate banner / recent strip / chips here (those lived in the old
// full-page landing). Submitting a ticker drills into /stocks/:ticker.

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
    <div
      data-testid="coverage-hero"
      style={{
        position: 'relative',
        overflow: 'hidden',
        padding: '28px 32px 24px',
        marginBottom: 4,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 18,
      }}
    >
      {/* Spline robot backdrop — the "AI analyst at rest" mascot. Sits behind
          the title/search, masked into the starfield, never steals a click. */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          top: -48,
          right: -56,
          width: 480,
          height: 380,
          maxWidth: '48vw',
          zIndex: 0,
          opacity: 0.62,
          pointerEvents: 'none',
          maskImage: 'radial-gradient(ellipse at 62% 45%, black 0%, black 58%, transparent 88%)',
          WebkitMaskImage:
            'radial-gradient(ellipse at 62% 45%, black 0%, black 58%, transparent 88%)',
        }}
      >
        <SplineHero variant="backdrop" />
      </div>

      {/* Title + morphing tagline */}
      <div style={{ textAlign: 'center', position: 'relative', zIndex: 2 }}>
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 40,
            letterSpacing: '6px',
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
            height: 22,
            marginTop: 6,
            fontFamily: 'var(--font-display)',
            fontSize: 12,
            letterSpacing: 1.6,
            color: 'var(--accent-cyan)',
            textShadow: 'var(--glow-cyan)',
          }}
        >
          {TAGLINE_KEYS.map((key, i) => (
            <span
              key={key}
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
              {t(key)}
            </span>
          ))}
        </div>
      </div>

      {/* Halo ticker search — drills into /stocks/:ticker */}
      <form
        onSubmit={handleSubmit}
        style={{
          position: 'relative',
          zIndex: 2,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 8,
          width: '100%',
        }}
      >
        <div className="halo-input" style={{ width: 'min(520px, 100%)', padding: 1 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 18px',
              background: 'var(--bg-input, rgba(10,10,24,0.7))',
              borderRadius: 'var(--radius-md)',
            }}
          >
            <span style={{ color: 'var(--text-muted)', fontSize: 14 }} aria-hidden>
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
    </div>
  )
}
