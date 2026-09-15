// CoverageHero — the research cockpit that fronts the Research homepage
// (FinRobot.html reference). Submitting a ticker drills into /stocks/:ticker.
//
// Layout, top → bottom:
//   eyebrow      — "AI 研究驾驶舱" with cyan side rules
//   robot stage  — our SplineHero robot, centered, presiding over…
//   command console — the single glowing ticker input + Analyze CTA
//   popular chips + subcopy
//   capability dock — five flush modules describing the real engine surface
//
// The robot is OUR SplineHero (not a CSS-drawn figure); it sits behind the
// console as the luminous subject. No "Engine Online / Data Feed · LIVE" pills
// and no avatar — those were dropped per the design and because a liveness
// claim would be dishonest (the assistant is on-demand).

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SplineHero } from '../SplineHero'
import { TickerSuggestions } from './TickerSuggestions'
import { useTickerSearch } from '../../hooks/useTickerSearch'
import { isValidTicker, sanitizeTickerInput } from '../../utils/ticker'
import { useI18n, tSync } from '../../i18n'

const SUGGESTIONS_ID = 'ticker-suggestions-list'

const HOT_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD']

// Floating cyan motes drifting up across the cockpit (design `.ambient .mote`).
// Positions/timing are randomized once per mount (useMemo) so the field looks
// organic without re-shuffling on every render.
function CockpitMotes(): React.ReactElement {
  const motes = useMemo(
    () =>
      Array.from({ length: 20 }, () => ({
        left: Math.random() * 100,
        top: 24 + Math.random() * 62,
        size: 1.4 + Math.random() * 2.2,
        dur: 9 + Math.random() * 12,
        delay: -Math.random() * 16,
      })),
    [],
  )
  return (
    <div
      aria-hidden
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 1,
        pointerEvents: 'none',
        overflow: 'hidden',
      }}
    >
      {motes.map((m, i) => (
        <span
          key={i}
          className="cockpit-mote"
          style={{
            left: `${m.left}%`,
            top: `${m.top}%`,
            width: m.size,
            height: m.size,
            animationDuration: `${m.dur}s`,
            animationDelay: `${m.delay}s`,
          }}
        />
      ))}
    </div>
  )
}

// The five capability modules in the bottom dock. Each maps to a real engine
// surface (compute/operators: dcf · ddm · lbo · multiples · monte_carlo ·
// sniper · ownership · catalyst · signal). Copy lives
// in i18n (landing.dock.*); `meta` is a mono tag kept as a Latin identifier in
// both locales (like ticker / DCF).
const MODULES = [
  { key: 'research', glyph: 'cap-g1', meta: 'Research' },
  { key: 'valuation', glyph: 'cap-g2', meta: 'Valuation' },
  { key: 'provenance', glyph: 'cap-g3', meta: 'Provenance' },
  { key: 'signals', glyph: 'cap-g4', meta: 'Signals' },
  { key: 'quant', glyph: 'cap-g5', meta: 'Quant' },
] as const

export function CoverageHero(): React.ReactElement {
  const navigate = useNavigate()
  const { t } = useI18n()

  const [inputValue, setInputValue] = useState('')
  const [inputError, setInputError] = useState('')
  const [focused, setFocused] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [dismissed, setDismissed] = useState(false)

  const results = useTickerSearch(inputValue)
  const hasInput = inputValue.trim().length > 0
  const open = focused && hasInput && !dismissed && results.length > 0

  // A fresh result set clears any prior highlight, so Enter submits the typed
  // ticker (even an ETF not in the index) unless the user arrows/hovers onto a
  // suggestion — suggestions augment, they never hijack a deliberate Enter.
  useEffect(() => {
    setActiveIndex(-1)
  }, [results])

  const handleInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(sanitizeTickerInput(e.target.value))
    setInputError('')
    setDismissed(false)
  }, [])

  const selectSuggestion = useCallback(
    (symbol: string) => {
      navigate(`/stocks/${symbol}`)
    },
    [navigate],
  )

  const handleSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault()
      if (open && activeIndex >= 0 && results[activeIndex]) {
        selectSuggestion(results[activeIndex].symbol)
        return
      }
      const sym = inputValue.trim().toUpperCase()
      if (!sym) return
      if (!isValidTicker(sym)) {
        setInputError(tSync('landing.hero.invalidTicker'))
        return
      }
      navigate(`/stocks/${sym}`)
    },
    [open, activeIndex, results, selectSuggestion, inputValue, navigate],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Escape') {
        setDismissed(true)
        setActiveIndex(-1)
        return
      }
      if (!open) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIndex((i) => Math.min(i + 1, results.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIndex((i) => (i <= 0 ? -1 : i - 1))
      }
    },
    [open, results.length],
  )

  return (
    <section
      data-testid="coverage-hero"
      style={{
        position: 'relative',
        height: '100%',
        minHeight: 600,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* The luminous cockpit background (glow + HUD grid + edge vignette) is
          painted at the shell level (AppShell `.cockpit-bg`) so it sits behind
          the title/status bars too. Here we only add the drifting motes. */}
      <CockpitMotes />

      {/* ── Cockpit center: eyebrow + robot stage (robot + console group) ── */}
      <div
        style={{
          position: 'relative',
          zIndex: 3,
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          padding: '12px 24px 0',
          // Nudge the whole cockpit up a touch so the search console sits a bit
          // higher and the autocomplete dropdown has more room to open below it.
          transform: 'translateY(-80px)',
        }}
      >
        <div className="cockpit-eyebrow">{t('landing.hero.cockpitLabel')}</div>

        {/* Robot stage — SplineHero presides; the console group (subcopy line +
            ticker input + popular row) sits at its base, embraced by the robot. */}
        <div
          style={{
            position: 'relative',
            width: 'min(820px, 98%)',
            height: 'clamp(400px, 50vh, 540px)',
          }}
        >
          <div
            aria-hidden
            style={{
              position: 'absolute',
              left: '50%',
              top: 0,
              // Robot is ~doubled: a much wider/taller box; the Spline scene
              // scales to fill it. It may spill past the stage sides (clipped by
              // the section) — that's fine, the mask fades the edges anyway.
              transform: 'translateX(-50%)',
              width: 'min(960px, 130%)',
              bottom: 64,
              zIndex: 0,
              opacity: 1,
              pointerEvents: 'none',
              // Bias the spotlight to the head/torso so the robot presides over
              // the console and its legs fade before the dock below.
              maskImage:
                'radial-gradient(ellipse 70% 70% at 50% 44%, black 0%, black 58%, transparent 86%)',
              WebkitMaskImage:
                'radial-gradient(ellipse 70% 70% at 50% 44%, black 0%, black 58%, transparent 86%)',
            }}
          >
            <SplineHero variant="backdrop" />
          </div>

          {/* Console group: subcopy (above) · ticker input · popular row (below),
              a tight stack sitting in the robot's cradle. */}
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 8,
              zIndex: 2,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 12,
            }}
          >
            {/* Subcopy — above the input, left-aligned to the input's left edge. */}
            <p
              style={{
                margin: 0,
                width: '100%',
                textAlign: 'left',
                fontFamily: 'var(--font-body)',
                fontSize: 13.5,
                color: 'var(--text-secondary)',
              }}
            >
              {t('landing.hero.subcopy')}
              <span
                style={{
                  color: 'var(--accent-cyan)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              >
                {'  ·  '}
                {t('landing.hero.subcopyAccent')}
              </span>
            </p>

            {/* Ticker input — the one action (no console-hint line above it). */}
            <form onSubmit={handleSubmit} style={{ width: '100%' }}>
              <div style={{ position: 'relative', width: '100%' }}>
                <div className={`halo-input${focused ? ' focused' : ''}`} style={{ padding: 1 }}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 14,
                      minHeight: 72,
                      padding: '12px 14px 12px 20px',
                      background: 'var(--bg-input)',
                      borderRadius: 'var(--radius-md)',
                      boxShadow: 'var(--glow-blue)',
                    }}
                  >
                    <span
                      style={{
                        color: 'var(--accent-cyan)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 16,
                        fontWeight: 600,
                        textShadow: 'var(--glow-cyan)',
                        flexShrink: 0,
                      }}
                      aria-hidden
                    >
                      {'▸ TICKER'}
                    </span>
                    <input
                      type="text"
                      value={inputValue}
                      onChange={handleInput}
                      onFocus={() => setFocused(true)}
                      onBlur={() => setFocused(false)}
                      onKeyDown={handleKeyDown}
                      role="combobox"
                      aria-expanded={open}
                      aria-controls={SUGGESTIONS_ID}
                      aria-autocomplete="list"
                      aria-activedescendant={
                        open && activeIndex >= 0 ? `ticker-opt-${activeIndex}` : undefined
                      }
                      placeholder={t('landing.hero.searchPlaceholder')}
                      maxLength={12}
                      spellCheck={false}
                      aria-label={t('landing.hero.tickerAria')}
                      aria-describedby={inputError ? 'coverage-hero-ticker-error' : undefined}
                      style={{
                        flex: 1,
                        minWidth: 0,
                        fontSize: 22,
                        fontFamily: 'var(--font-mono)',
                        fontWeight: 700,
                        background: 'transparent',
                        color: 'var(--text-primary)',
                        border: 'none',
                        outline: 'none',
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                      }}
                    />
                    <button
                      type="submit"
                      disabled={!hasInput}
                      aria-label={t('landing.hero.analyze')}
                      className="btn-shimmer"
                      style={{
                        flexShrink: 0,
                        minWidth: 116,
                        padding: '13px 22px',
                        fontSize: 12,
                        opacity: hasInput ? 1 : 0.4,
                        cursor: hasInput ? 'pointer' : 'not-allowed',
                      }}
                    >
                      {t('landing.hero.analyze')}
                    </button>
                  </div>
                </div>
                {open && (
                  <TickerSuggestions
                    results={results}
                    activeIndex={activeIndex}
                    query={inputValue}
                    labelId={SUGGESTIONS_ID}
                    onSelect={selectSuggestion}
                    onHover={setActiveIndex}
                  />
                )}
              </div>

              {inputError && (
                <div
                  id="coverage-hero-ticker-error"
                  role="alert"
                  style={{
                    marginTop: 8,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: 'var(--danger)',
                    paddingLeft: 4,
                  }}
                >
                  {inputError}
                </div>
              )}
            </form>

            {/* Popular tickers — tight under the input. */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                flexWrap: 'wrap',
                justifyContent: 'center',
              }}
            >
              <span
                style={{
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  letterSpacing: '0.16em',
                  textTransform: 'uppercase',
                }}
              >
                {t('landing.hero.popular')}
              </span>
              {HOT_TICKERS.map((tk, i) => (
                <button
                  key={tk}
                  type="button"
                  className="coverage-hover-btn"
                  onClick={() => navigate(`/stocks/${tk}`)}
                  aria-label={t('coverage.starter.researchTicker', { ticker: tk })}
                  style={{
                    padding: '7px 14px',
                    borderRadius: 'var(--radius-pill)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 13,
                    fontWeight: 500,
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
      </div>

      {/* ── Capability dock (lifted off the bottom edge) ── */}
      {/* zIndex 2 (below the cockpit-center's zIndex 3) so the autocomplete
          dropdown — which lives in the cockpit-center subtree and extends down
          over this dock — paints ON TOP of it instead of being covered. */}
      <div style={{ position: 'relative', zIndex: 2, padding: '0 26px 44px' }}>
        <div className="capability-dock">
          {MODULES.map((m) => (
            <div key={m.key} className={`capability-module ${m.glyph}`}>
              <div className="cap-top">
                <span className="cap-glyph" aria-hidden />
                <span className="cap-name">{t(`landing.dock.${m.key}.name`)}</span>
              </div>
              <span className="cap-desc">{t(`landing.dock.${m.key}.desc`)}</span>
              <span className="cap-meta">{m.meta}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
