// TickerHero — identity strip at the top of the workspace.
//
// Job: breadcrumb back to landing + ticker glyph + LIVE pill + morph
// tagline + current price / day-change.
//
// What it does NOT do: anything related to running research. The "run"
// / "rerun" buttons used to live here, but they duplicated the AIZone's
// cold-state CTA + hot-state rerun action. After the dual-zone dashboard
// landed, the hero kept showing redundant controls — surfaced by user as
// "这个东西也不该留在这了". All run-related affordances now live in AIZone
// (data-testid="run-analysis-trigger" moved with them so tests still pin
// on the canonical trigger).

import { Link } from 'react-router-dom'
import { useTickerPrice } from '../hooks/useTickerData'
import { useI18n } from '../i18n'

interface Props {
  ticker: string
}

export function TickerHero({ ticker }: Props): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)
  const { locale } = useI18n()

  const current = price?.current_price
  const changePct = price?.change_pct
  const changeAbs = price?.change ?? undefined
  const isUp = typeof changePct === 'number' && changePct >= 0

  return (
    <header
      data-testid="ticker-hero"
      style={{
        position: 'relative',
        padding: '16px 32px 14px',
        background: 'linear-gradient(180deg, rgba(15,15,34,0.4) 0%, transparent 100%)',
        borderBottom: '1px solid var(--border-faint)',
      }}
    >
      <div style={{ maxWidth: 1280, margin: '0 auto', minWidth: 0 }}>
        <Breadcrumb ticker={ticker} locale={locale} />

        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 18,
            flexWrap: 'wrap',
            marginTop: 10,
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 36,
              letterSpacing: 3,
              color: 'var(--text-primary)',
              lineHeight: 1,
              textShadow: '0 0 18px rgba(59,130,246,0.3)',
            }}
          >
            {ticker}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              padding: '3px 8px',
              border: '1px solid var(--border-soft)',
              borderRadius: 5,
              letterSpacing: '0.06em',
            }}
          >
            <span className="cosmic-pulse-dot" style={{ marginRight: 6 }} />
            LIVE · {formatExchange(price?.exchange)}
          </span>

          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 26,
              fontWeight: 500,
              letterSpacing: '-0.5px',
              color: 'var(--text-primary)',
              fontVariantNumeric: 'tabular-nums',
              marginLeft: 12,
            }}
          >
            {typeof current === 'number' ? `$${current.toFixed(2)}` : '—'}
          </span>
          {typeof changePct === 'number' && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                color: isUp ? 'var(--success)' : 'var(--danger)',
                padding: '3px 9px',
                background: isUp ? 'rgba(22,163,74,0.12)' : 'rgba(220,38,38,0.12)',
                border: `1px solid ${isUp ? 'rgba(22,163,74,0.32)' : 'rgba(220,38,38,0.32)'}`,
                borderRadius: 6,
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
      </div>
    </header>
  )
}

// ── Breadcrumb ─────────────────────────────────────────────────────────────
function Breadcrumb({ ticker, locale }: { ticker: string; locale: 'zh' | 'en' }): React.ReactElement {
  const linkStyle: React.CSSProperties = { color: 'inherit', textDecoration: 'none' }
  const stocksLabel = locale === 'en' ? 'Stocks' : '股票'
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        fontFamily: 'var(--font-mono)',
        fontSize: 10.5,
        color: 'var(--text-muted)',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
      }}
    >
      <Link to="/stocks" style={linkStyle}>
        FINAGENT
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <Link to="/stocks" style={linkStyle}>
        {stocksLabel}
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <span style={{ color: 'var(--accent-cyan)' }}>{ticker}</span>
    </div>
  )
}

/**
 * yfinance returns "NasdaqGS" / "NYQ" / "AMEX" raw codes — pretty-print
 * them for the LIVE pill. Falls back to a generic "美股" so non-US tickers
 * (which we don't really support yet) don't show a confusing code.
 */
function formatExchange(raw: string | null | undefined): string {
  if (!raw) return '美股'
  const lower = raw.toLowerCase()
  if (lower.includes('nasdaq') || lower === 'nms' || lower === 'ngm' || lower === 'ncm') return 'NASDAQ'
  if (lower.includes('nyse') || lower === 'nyq' || lower === 'nys') return 'NYSE'
  if (lower.includes('amex') || lower === 'pcx' || lower === 'ase') return 'AMEX'
  if (lower.includes('otc')) return 'OTC'
  return raw.toUpperCase()
}

