// TickerHero — identity strip at the top of the workspace.
//
// Job: breadcrumb back to landing + ticker glyph + freshness pill + morph
// tagline + current price / day-change.
//
// What it does NOT do: anything related to running research. All run/rerun
// affordances live in AIZone (cold-state CTA + hot-state rerun, the canonical
// data-testid="run-analysis-trigger") — the hero stays a pure identity strip.

import { useTickerPrice, useTickerFinancials } from '../hooks/useTickerData'
import { formatAge, freshnessColor, freshnessTier } from '../utils/format'
import { useI18n, tSync } from '../i18n'
import { WORKSPACE_FRAME_MAX_WIDTH } from './workspace/layout'

interface Props {
  ticker: string
}

export function TickerHero({ ticker }: Props): React.ReactElement {
  const { data: price, isPending: priceLoading } = useTickerPrice(ticker)
  // Company name + industry for the identity sub-line. React Query dedupes this
  // onto MarketDataZone's existing useTickerFinancials call (same key) — no
  // extra request. Both fields are best-effort: the sub-line omits itself when
  // absent (never an empty placeholder, never an error).
  const { data: fin } = useTickerFinancials(ticker)
  const { t } = useI18n()

  const companyName = price?.company_name ?? fin?.company_name ?? null
  // Industry is the more specific label; fall back to the broader sector.
  const industry = fin?.market?.industry ?? fin?.market?.sector ?? null

  const current = price?.current_price
  const changePct = price?.change_pct
  const changeAbs = price?.change ?? undefined
  const isUp = typeof changePct === 'number' && changePct >= 0

  const ageSeconds = price?.fetched_at
    ? (Date.now() - new Date(price.fetched_at).getTime()) / 1000
    : Infinity // 没有 fetched_at = 视为陈旧（不 fail-safe 回 fresh）
  const tier = freshnessTier(ageSeconds)
  const tierLabel = t(`marketdata.tier.${tier}`)
  const ageText = formatAge(price?.fetched_at)

  // Whether current_price is a live intraday quote or a session CLOSE is the
  // backend's call (session_state), computed in the EXCHANGE's timezone — never
  // re-derived here. The client's "today" is the viewer's local date, which
  // runs ahead of US market time; deriving session state from it mislabels a
  // live US quote as a prior-day close whenever the session runs past the
  // viewer's local midnight (e.g. China 00:00–04:00 = ET 12:00–16:00). When
  // closed, current_price is the close of the `as_of` session → say
  // "收盘 · MM-DD" instead of a fetch-time "near-real-time" claim (audit B).
  const asOf = price?.as_of ?? null
  const isClosed = price?.session_state === 'closed'
  // No quote yet — initial load, or the ~2s cold-start window where the
  // engine-warmup 503 leaves `price` undefined — is a NOT-YET state, not a
  // stale quote. Render a neutral muted pill, never the red pulsing "stale · —"
  // the Infinity-age default (no fetched_at) would otherwise produce: cold-start
  // must never read as an error (and the sibling price card shows the calm
  // "engine starting" state, so a red hero pill would also be inconsistent).
  const quotePending = priceLoading || !price
  const pillDotColor = quotePending
    ? 'var(--text-dim)'
    : isClosed
      ? 'var(--warning)'
      : freshnessColor(ageSeconds)
  // slice(5, 10) bounds to MM-DD even if as_of ever carries a time component.
  const pillLabel = quotePending
    ? '—'
    : isClosed && asOf
      ? t('workspace.hero.closedAsOf', { date: asOf.slice(5, 10) })
      : `${tierLabel} · ${ageText}`

  return (
    <header
      data-testid="ticker-hero"
      style={{
        position: 'relative',
        // Horizontal padding lives on the inner box (matching <main> below)
        // so the ticker glyph's left edge aligns with the MarketDataZone
        // card edge; the full-width strip keeps its gradient + border.
        padding: '16px 0 14px',
        background: 'var(--gradient-hero-strip)',
        borderBottom: '1px solid var(--border-faint)',
      }}
    >
      <div
        style={{
          maxWidth: WORKSPACE_FRAME_MAX_WIDTH,
          margin: '0 auto',
          padding: '0 32px',
          minWidth: 0,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 18,
            flexWrap: 'wrap',
          }}
        >
          {/* Identity stack: ticker glyph + (company name · industry) sub-line.
              The sub-line is muted/secondary and omits itself entirely when both
              fields are absent — no empty row, no error state. No alignSelf so the
              stack's first baseline (the ticker) stays on the row baseline, keeping
              the price aligned to the ticker exactly as before. */}
          <span
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 3,
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 36,
                letterSpacing: 3,
                color: 'var(--text-primary)',
                lineHeight: 1,
                textShadow: 'var(--glow-blue-soft)',
              }}
            >
              {ticker}
            </span>
            {(companyName || industry) && (
              <span
                data-testid="ticker-hero-identity"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 7,
                  fontFamily: 'var(--font-body)',
                  fontSize: 12.5,
                  color: 'var(--text-muted)',
                  lineHeight: 1.2,
                }}
              >
                {companyName && (
                  <span style={{ color: 'var(--text-secondary)' }}>{companyName}</span>
                )}
                {companyName && industry && <span style={{ color: 'var(--text-dim)' }}>·</span>}
                {industry && <span>{industry}</span>}
              </span>
            )}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              padding: '3px 8px',
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--radius-pill)',
              letterSpacing: '0.06em',
            }}
          >
            <span
              // Closed market → static dot (the close won't move); only a live
              // session pulses. Avoids a >1s persistent animation over a settled
              // value (cosmic spec) and the "looks live" lie.
              className={isClosed || quotePending ? 'cosmic-dot-static' : 'cosmic-pulse-dot'}
              style={{ marginRight: 6, background: pillDotColor }}
            />
            {pillLabel} · {formatExchange(price?.exchange)}
          </span>

          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 26,
              fontWeight: 500,
              letterSpacing: 0,
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
                background: isUp ? 'var(--success-soft)' : 'var(--danger-soft)',
                border: `1px solid ${isUp ? 'var(--success-glow-soft)' : 'var(--danger-glow-soft)'}`,
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

/**
 * yfinance returns "NasdaqGS" / "NYQ" / "AMEX" raw codes — pretty-print
 * them for the freshness pill. Falls back to a generic "美股" so non-US tickers
 * (which we don't really support yet) don't show a confusing code.
 */
function formatExchange(raw: string | null | undefined): string {
  if (!raw) return tSync('workspace.hero.usMarket')
  const lower = raw.toLowerCase()
  if (lower.includes('nasdaq') || lower === 'nms' || lower === 'ngm' || lower === 'ncm')
    return 'NASDAQ'
  if (lower.includes('nyse') || lower === 'nyq' || lower === 'nys') return 'NYSE'
  if (lower.includes('amex') || lower === 'pcx' || lower === 'ase') return 'AMEX'
  if (lower.includes('otc')) return 'OTC'
  return raw.toUpperCase()
}
