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

const TAGLINES = [
  '确定性计算 · LLM 叙事',
  'NUMBER FIRST · NARRATIVE SECOND',
  '每一个数字 · 都能追溯到函数调用',
  'AI ANALYST · 持续工作中',
] as const

interface Props {
  ticker: string
}

export function TickerHero({ ticker }: Props): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)

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
          maxWidth: 1280,
          margin: '0 auto',
          minWidth: 0,
        }}
      >
        {/* Single-column hero — Spline 3D moved to /stocks landing only */}
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
                LIVE · {formatExchange(price?.exchange)}
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

          {/* Run / rerun actions intentionally removed — see file header.
              The single canonical entry point is AIZone's cold-state
              「立即跑 AI 研报」 button (data-testid run-analysis-trigger). */}
        </div>

      </div>
    </header>
  )
}

// ── Breadcrumb ─────────────────────────────────────────────────────────────
function Breadcrumb({ ticker }: { ticker: string }): React.ReactElement {
  const linkStyle: React.CSSProperties = { color: 'inherit', textDecoration: 'none' }
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
      <Link to="/stocks" style={linkStyle}>
        FINAGENT
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <Link to="/stocks" style={linkStyle}>
        Stocks
      </Link>
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

