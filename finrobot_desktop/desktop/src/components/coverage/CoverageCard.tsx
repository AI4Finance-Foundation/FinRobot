// CoverageCard — one ticker in the workspace card wall. The card is a bounded
// graphite slab: identity, market snapshot, a two-by-two metric band, then the
// quality/report footer. Every number still renders through SourcedNumber
// (provenance popover + inline amber warning), 涨绿跌红, mono digits, all colors
// via design tokens.
//
// Fields (locked by the redesign spec): ticker/company · price/1D · verdict ·
// market cap · revenue TTM · EV/EBITDA-or-P/E · live upside · warning/freshness ·
// report count + latest report date. Live Upside is labelled "vs latest price"
// in the inspector; on the dense card the column header carries that meaning.

import { memo } from 'react'
import { useI18n, type Locale } from '../../i18n'
import {
  formatAge,
  formatCompactNumber,
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from '../../utils/format'
import { SourcedNumber } from '../SourcedNumber'
import { TargetGauge } from '../TargetGauge'
import type { CoverageRow, MarketImpliedNature } from '../../api/coverage'
import type { CoverageDensity } from '../../stores/coverageStore'

interface Props {
  row: CoverageRow
  density: CoverageDensity
  // Background revalidate in flight. A COLD row (no snapshot yet, price null)
  // shimmers its cells; a row that already holds a (stale) snapshot keeps showing
  // its last-known numbers with a refreshing hint — never a blank shimmer.
  marketPending?: boolean
  onOpen: (ticker: string) => void
}

// Badge text + dot ride the bright signal hue (matches the card's top hairline);
// the soft tinted bg stays the deep-token derivative. Coverage cards only — the
// report cover/right-rail verdict badges keep the deeper semantic tokens.
const VERDICT: Record<string, { color: string; bg: string }> = {
  BUY: { color: 'var(--card-buy-fg)', bg: 'var(--success-soft)' },
  HOLD: { color: 'var(--card-hold-fg)', bg: 'var(--warning-soft)' },
  SELL: { color: 'var(--card-sell-fg)', bg: 'var(--danger-soft)' },
}

// Card chroma bucket from the latest directional verdict. BUY/SELL/HOLD tint the
// slab top + carry a 1px signal hairline; everything else — NOT RUN (verdict
// null) and the legacy WITHHELD/REVIEW token — is a neutral slab with no
// hairline. Drives the `data-signal` rules in App.css (graphite-slab redesign).
type CardSignal = 'buy' | 'sell' | 'hold' | 'neutral'
function signalClass(verdict: string | null | undefined): CardSignal {
  switch ((verdict ?? '').toUpperCase()) {
    case 'BUY':
      return 'buy'
    case 'SELL':
      return 'sell'
    case 'HOLD':
      return 'hold'
    default:
      return 'neutral'
  }
}

function changeColor(v: number | null): string {
  if (v === null || v === 0) return 'var(--text-secondary)'
  return v > 0 ? 'var(--success)' : 'var(--danger)'
}

// The single most pressing line for the quality row: an in-flight run, a refresh
// reason, a data warning — else "fresh". The pill shows a TERSE label (a full
// reason sentence crammed in a pill just ellipsis-truncated to "覆盖池中但…");
// the complete detail rides in the title tooltip. Tone drives the pill color
// (cyan = ok/live, amber = attention). Never hover-only (cosmic spec).
function cardStatus(
  row: CoverageRow,
  t: (k: string) => string,
): { text: string; title: string; tone: 'ok' | 'warn' } {
  if (row.run_status === 'running' || row.run_status === 'created') {
    const running = t('coverage.running')
    return { text: running, title: running, tone: 'ok' }
  }
  // needs_refresh is already in backend precedence order (run_failed first); its
  // kind maps to a short pill label, its detail to the tooltip.
  const reason = row.needs_refresh[0]
  if (reason)
    return { text: t(`coverage.reason.${reason.kind}`), title: reason.detail, tone: 'warn' }
  if (row.warnings.length > 0)
    return { text: t('coverage.reason.warning'), title: row.warnings[0], tone: 'warn' }
  const fresh = t('coverage.card.fresh')
  return { text: fresh, title: fresh, tone: 'ok' }
}

export const CoverageCard = memo(function CoverageCard({
  row,
  density,
  marketPending = false,
  onOpen,
}: Props): React.ReactElement {
  const { t, locale } = useI18n()
  const compact = density === 'compact'
  const ccy = row.currency || 'USD'
  const verdict = row.latest_verdict ? VERDICT[row.latest_verdict] : null
  const status = cardStatus(row, t)
  const signal = signalClass(row.latest_verdict)

  // A row with no snapshot yet (price null) is genuinely cold → shimmer while
  // the revalidate runs. A row that already holds a (stale) snapshot shows its
  // last-known numbers immediately; the as-of line carries the refreshing/stale
  // hint instead of a blank shimmer.
  const isCold = row.price == null
  const showShimmer = marketPending && isCold
  // A closed market has nothing to refresh — its close won't move until the next
  // session. Never pulse "refreshing" over it (the lie that made the card read as
  // live). Only a live / undetermined session shows the in-flight affordance.
  const isClosed = row.session_state === 'closed'
  const refreshing = marketPending && !isCold && !isClosed
  const mc = (node: React.ReactNode): React.ReactNode => (showShimmer ? <Shimmer /> : node)

  // EV/EBITDA when computable, else P/E — one slot, label follows the value.
  const useEv = row.ev_ebitda != null
  const multipleLabel = useEv ? 'EV/EBITDA' : 'P/E TTM'
  const multipleValue = useEv ? row.ev_ebitda : row.pe
  const multipleSource = useEv ? row.sources?.ev_ebitda : row.sources?.pe

  const provider = row.sources?.price?.provider ?? null
  const asOf = row.price_as_of ? formatAge(row.price_as_of) : ccy
  // Closed market: show the settled session's DATE, not a live "Nh ago" age.
  // Slice the ISO date (UTC) rather than formatDate (viewer-local): a US 16:00 ET
  // close is 20:00Z, which the viewer's local tz can roll to the next calendar
  // day — exactly the local-date drift the server-side session_state avoids.
  const closeDate = row.price_as_of ? row.price_as_of.slice(0, 10) : null
  const company = row.company?.trim()
  const companyLabel =
    company && company.toUpperCase() !== row.ticker.toUpperCase() ? company : null
  const reportSummary =
    row.research_count > 0
      ? t('coverage.card.reports', {
          n: row.research_count,
          date: row.latest_at ? formatDate(row.latest_at, locale, 'short') : '—',
        })
      : row.artifact_count > 0
        ? t('coverage.card.modelOnly', { n: row.artifact_count })
        : t('coverage.card.noReports')

  // What the live price implies vs the name's stored DCF — the reverse-DCF
  // "expectations" read. Per-name classification, deliberately NOT a cross-name
  // implied-growth ranking (the flat-constant solve vs the DCF's decay schedule
  // makes a cross-name gap rank curve-steepness, not expectation stretch).
  const impliedView = impliedNatureView(row.market_implied, ccy, locale, t)

  return (
    <article
      className={`coverage-card${compact ? ' coverage-card--compact' : ''}`}
      data-ticker={row.ticker}
      data-testid={`coverage-card-${row.ticker}`}
      data-signal={signal}
      role="link"
      tabIndex={0}
      aria-label={t('coverage.card.open', { ticker: row.ticker })}
      onClick={() => onOpen(row.ticker)}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(row.ticker)
        }
      }}
    >
      <header className="coverage-card__header">
        <div className="coverage-card__identity">
          <div className="coverage-card__ticker">{row.ticker}</div>
          {companyLabel && (
            <div className="coverage-card__company" title={companyLabel}>
              {companyLabel}
            </div>
          )}
        </div>
        <div
          className="coverage-card__verdict"
          style={{
            color: verdict ? verdict.color : 'var(--text-muted)',
            background: verdict ? verdict.bg : 'var(--neutral-soft)',
            borderColor: verdict ? verdict.bg : 'var(--border-soft)',
          }}
        >
          <span className="coverage-card__verdict-dot" aria-hidden />
          {row.latest_verdict ?? t('coverage.notRun')}
        </div>
      </header>

      <section className="coverage-card__market">
        <div className="coverage-card__price-block">
          <div className="coverage-card__price">
            {mc(
              <SourcedNumber
                className="coverage-source-number"
                value={row.price}
                source={row.sources?.price ?? undefined}
                ticker={row.ticker}
                format={(v) => formatCurrency(v, ccy, locale)}
              />,
            )}
          </div>
          <div className="coverage-card__change" style={{ color: changeColor(row.change_pct_1d) }}>
            {mc(
              row.change_pct_1d == null ? (
                <span style={{ color: 'var(--text-dim)' }}>—</span>
              ) : (
                // Closed: the move belongs to the last session, not "today" —
                // label it with that session's MM-DD so "· 1D" can't misread as
                // an intraday change when the market's been shut since Friday.
                `${row.change_pct_1d > 0 ? '+' : ''}${row.change_pct_1d.toFixed(2)}% · ${
                  isClosed && closeDate ? closeDate.slice(5) : '1D'
                }`
              ),
            )}
          </div>
        </div>
        <span
          className="coverage-card__provider"
          data-refreshing={refreshing ? 'true' : undefined}
          data-session={isClosed ? 'closed' : undefined}
          // A past-TTL snapshot that isn't currently revalidating: tint the
          // as-of so the last-known age reads as "stale", not live. A closed
          // market carries its own (amber, static) treatment via data-session.
          data-stale={row.market_stale && !refreshing && !isClosed ? 'true' : undefined}
          title={provider ?? undefined}
        >
          {isClosed
            ? `${provider ? `${provider} · ` : ''}${t('coverage.card.closed', {
                date: closeDate ?? '—',
              })}`
            : provider
              ? `${provider} · ${asOf}`
              : asOf}
          {refreshing && ` · ${t('coverage.card.refreshing')}`}
        </span>
      </section>

      <div className="coverage-card__metrics">
        <Metric label={t('coverage.col.mcap')}>
          {mc(
            <SourcedNumber
              className="coverage-source-number"
              value={row.market_cap}
              source={row.sources?.market_cap ?? undefined}
              ticker={row.ticker}
              // No per-metric currency prefix: it's uniform per card and already
              // shown on the price line. Repeating "USD " here only widened the
              // value until the compact unit (B/T) clipped to a stem at narrow
              // 5-col widths — a clipped "B" reads as "I" (wrong unit).
              format={(v) => formatCompactNumber(v, locale)}
            />,
          )}
        </Metric>
        <Metric label={t('coverage.col.revttm')}>
          {mc(
            <SourcedNumber
              className="coverage-source-number"
              value={row.revenue_ttm}
              source={row.sources?.revenue_ttm ?? undefined}
              ticker={row.ticker}
              format={(v) => formatCompactNumber(v, locale)}
            />,
          )}
        </Metric>
        <Metric label={multipleLabel}>
          {mc(
            <SourcedNumber
              className="coverage-source-number"
              value={multipleValue}
              source={multipleSource ?? undefined}
              ticker={row.ticker}
              format={(v) => `${formatNumber(v, locale, 1)}×`}
            />,
          )}
        </Metric>
        <Metric label={t('coverage.col.upside')}>
          <span style={{ color: changeColor(row.upside_to_target_live) }}>
            {mc(
              <SourcedNumber
                className="coverage-source-number"
                value={row.upside_to_target_live}
                source={row.sources?.upside_to_target_live ?? undefined}
                ticker={row.ticker}
                format={(v) => formatPercent(v, locale, 1)}
              />,
            )}
          </span>
        </Metric>
      </div>

      {!showShimmer && (
        <TargetGauge
          currentPrice={row.price}
          targetPrice={row.target_price}
          upside={row.upside_to_target_live}
          source={row.sources?.upside_to_target_live ?? undefined}
          ticker={row.ticker}
          quoteCurrency={ccy}
        />
      )}

      {!showShimmer && impliedView && (
        <div
          className="coverage-card__implied"
          title={impliedView.title}
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            gap: 8,
            marginTop: 2,
            paddingTop: 8,
            borderTop: '1px solid var(--border-faint)',
          }}
        >
          <span
            style={{
              fontSize: 10,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: 'var(--text-muted)',
            }}
          >
            {t('coverage.implied.label')}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              fontWeight: 600,
              color: impliedView.tone,
            }}
          >
            {impliedView.text}
          </span>
        </div>
      )}

      <footer className="coverage-card__footer">
        <span
          className={`coverage-card__status coverage-card__status--${status.tone}`}
          title={status.title}
        >
          {status.text}
        </span>
        <span className="coverage-card__report">{reportSummary}</span>
      </footer>
    </article>
  )
})

function Metric({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}): React.ReactElement {
  return (
    <div className="coverage-card__metric">
      <span className="coverage-card__metric-label">{label}</span>
      <span className="coverage-card__metric-value">{children}</span>
    </div>
  )
}

// The card's reverse-DCF "expectations" line. Returns null when there's nothing
// honest to say (no DCF, or fundamental with no solved growth). option_value /
// near_ceiling are the load-bearing signals; fundamental is per-name context.
function impliedNatureView(
  nat: MarketImpliedNature | null,
  ccy: string,
  locale: Locale,
  t: (k: string, p?: Record<string, string | number>) => string,
): { text: string; title: string; tone: string } | null {
  if (!nat) return null
  if (nat.kind === 'option_value') {
    const ceiling = nat.growth_ceiling != null ? formatPercent(nat.growth_ceiling, locale, 0) : '—'
    const price = nat.ceiling_price != null ? formatCurrency(nat.ceiling_price, ccy, locale) : '—'
    return {
      text: t('coverage.implied.optionValue'),
      title: t('coverage.implied.optionValueTitle', { ceiling, price }),
      tone: 'var(--danger)',
    }
  }
  if (nat.kind === 'near_ceiling') {
    return {
      text: t('coverage.implied.nearCeiling'),
      title: t('coverage.implied.nearCeilingTitle'),
      tone: 'var(--warning)',
    }
  }
  // fundamental — only informative when an implied growth actually solved (the
  // below-bracket-floor edge leaves it null; render nothing rather than "—").
  if (nat.implied_growth == null) return null
  const g = formatPercent(nat.implied_growth, locale, 1)
  return {
    text: t('coverage.implied.fundamental', { g }),
    title: t('coverage.implied.fundamentalTitle', { g, n: nat.horizon_years }),
    tone: 'var(--text-secondary)',
  }
}

function Shimmer(): React.ReactElement {
  return (
    <span
      className="skeleton"
      role="img"
      aria-label="loading"
      style={{ display: 'inline-block', width: 44, height: 11, verticalAlign: 'middle' }}
    />
  )
}
