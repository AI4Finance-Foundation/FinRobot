// Chapter 01 — Investment Thesis. The full ARGUMENT, not a single-sided wall:
//   narrative + key takeaways → bull / bear case (catalysts vs risks) → the
//   valuation bridge (per-method mids + anchor — a SUMMARY of the football field
//   in the Valuation chapter) → the market-implied reverse-DCF (what the price
//   bakes in vs our cash-flow model).
//
// Rating / target / conviction / target band live ONCE on the cover (ChapterCover)
// — not restated here (that was a same-screen duplicate of the cover hero). Every
// number on this chapter reads from the SAME deriveReportData output the cover and
// Valuation chapter consume (valuation_synthesis.methods / dcf.market_implied),
// never a second fetch — so the summary here can't disagree with the full chart.

import { Chapter, Narrative } from './ChapterBase'
import { MarkdownLite } from '../../../components/MarkdownLite'
import { BulletList } from './BulletList'
import { ReverseDcfHeadline } from './ReverseDcfHeadline'
import { METHOD_LABEL, compsPeLabel } from '../../../components/charts/FootballField'
import type { DcfShape, ThesisShape, ValuationSynthesisShape } from './types'
import { formatCurrency } from '../../../utils/format'
import { useI18n, type Locale } from '../../../i18n'

function tr(zh: string, en: string, locale: Locale): string {
  return locale === 'en' ? en : zh
}

interface ChapterThesisProps {
  thesis: ThesisShape | null
  // Valuation bridge + market-implied inputs — the SAME frozen objects the cover
  // and Valuation chapter render, so the summary here can never disagree with the
  // full football field (one source, no live re-fetch).
  valuationSynthesis: ValuationSynthesisShape | null
  dcf: DcfShape | null
  quoteCurrency: string
}

export function ChapterThesis({
  thesis,
  valuationSynthesis,
  dcf,
  quoteCurrency,
}: ChapterThesisProps): React.ReactElement {
  const { t, locale } = useI18n()
  if (!thesis) {
    return (
      <Chapter id="thesis">
        <Narrative>
          <p>{t('chapter.thesis.empty')}</p>
        </Narrative>
      </Chapter>
    )
  }

  const takeaways = thesis.key_takeaways ?? []
  const narrative = thesis.narrative ?? ''
  const catalysts = thesis.catalysts ?? []
  const risks = thesis.risks ?? []
  const methods = valuationSynthesis?.methods ?? []
  const anchor = valuationSynthesis?.anchor_method ?? null
  const currentPrice = valuationSynthesis?.current_price ?? null
  const marketImplied = dcf?.market_implied ?? null
  // Reverse-DCF lives on the cover ONLY when the point target is withheld; when a
  // target shipped the cover suppresses it (one price axis, one place), so it
  // surfaces HERE instead. Gate on the same signal the cover uses (recommendation
  // present + null target) so the two never both render it.
  const targetWithheld = !!thesis.recommendation && thesis.price_target == null
  const showMarketImplied = !targetWithheld && marketImplied != null

  const fmt = (v: number): string =>
    formatCurrency(v, quoteCurrency, locale, Math.abs(v) >= 100 ? 0 : 2)

  return (
    <Chapter id="thesis">
      {/* The opening summary is LLM prose: it sometimes ships markdown (**bold**,
          section labels) and \n\n paragraph breaks. A bare <p> literalises the
          markers (raw "**" leaks) and collapses the breaks into one dense wall —
          so render through MarkdownLite (parses emphasis, keeps paragraphs) inside
          the same editorial Narrative frame every other chapter's prose uses
          (14.5px + "+ AI NARRATIVE" provenance kicker, the LLM-vs-deterministic
          boundary). */}
      {narrative && (
        <Narrative>
          <MarkdownLite text={narrative} />
        </Narrative>
      )}

      {/* Momentum-divergence hedge (BACKLOG A2/P1-1) — only present when the
          verdict strongly disagreed with the stock's own trailing-1y price
          action (BUY on a >15% pullback / SELL on a >30% rally); null on an
          ordinary, non-divergent call, so this section simply does not render
          for most theses. Same Narrative/MarkdownLite register as the primary
          narrative above — this is a continuation of the argument, not a
          separate data panel. */}
      {thesis.momentum_divergence_note && (
        <>
          <h4 style={heading}>{tr('市场逆向信号', 'What the Market Is Pricing In', locale)}</h4>
          <Narrative>
            <MarkdownLite text={thesis.momentum_divergence_note} />
          </Narrative>
        </>
      )}

      {takeaways.length > 0 && (
        <>
          <h4 style={heading}>{t('chapter.thesis.keyTakeaways')}</h4>
          <ul
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              padding: 0,
              margin: 0,
              listStyle: 'none',
            }}
          >
            {takeaways.map((tk, i) => (
              <li
                key={`takeaway-${i}-${tk.slice(0, 24)}`}
                style={{
                  position: 'relative',
                  paddingLeft: 28,
                  fontSize: 14,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.65,
                }}
              >
                <span
                  style={{
                    position: 'absolute',
                    left: 6,
                    top: 6,
                    width: 0,
                    height: 0,
                    color: 'var(--secondary)',
                    fontSize: 9,
                    textShadow: '0 0 6px var(--secondary)',
                  }}
                >
                  ◆
                </span>
                {tk}
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Bull / bear case — the thesis is an ARGUMENT with two sides. catalysts and
          risks are thesis-level qualitative string[]; the Catalysts chapter carries
          the dated, structured events (different caliber, no double-booking). */}
      {(catalysts.length > 0 || risks.length > 0) && (
        <>
          <h4 style={heading}>{tr('多空论证', 'Bull / Bear Case', locale)}</h4>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
              gap: 16,
            }}
          >
            {catalysts.length > 0 && (
              <div>
                <div style={colHeading('var(--success)')}>
                  ↑ {tr('看多逻辑', 'Bull Case', locale)}
                </div>
                <BulletList items={catalysts} tone="positive" />
              </div>
            )}
            {risks.length > 0 && (
              <div>
                <div style={colHeading('var(--danger)')}>
                  ↓ {tr('看空逻辑', 'Bear Case', locale)}
                </div>
                <BulletList items={risks} tone="negative" />
              </div>
            )}
          </div>
        </>
      )}

      {/* Valuation bridge — per-method mids + the anchor: a SUMMARY of the Valuation
          chapter's football field (same valuation_synthesis.methods). Not the full
          chart — method · mid · range · upside, anchor highlighted, with a jump to
          the full bridge. No per-method weight (the schema carries none). */}
      {methods.length > 0 && (
        <>
          <h4 style={heading}>{tr('估值依据', 'Valuation Bridge', locale)}</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {methods.map((m) => {
              const isAnchor = m.name === anchor
              // comps_pe carries a caliber (core / forward / trailing) the football
              // field labels via compsPeLabel — reuse it so the summary and the full
              // bridge name the SAME method identically (core P/E vs a bare P/E read
              // as two methods otherwise). Other methods use the shared METHOD_LABEL.
              const label =
                m.name === 'comps_pe'
                  ? compsPeLabel(m.source).label
                  : (METHOD_LABEL[m.name] ?? m.name.toUpperCase())
              const upside =
                currentPrice != null && currentPrice > 0
                  ? ((m.mid - currentPrice) / currentPrice) * 100
                  : null
              const up = upside != null && upside >= 0
              return (
                <div key={m.name} style={bridgeRow(isAnchor)}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 11.5,
                        letterSpacing: '0.04em',
                        textTransform: 'uppercase',
                        color: 'var(--text-primary)',
                      }}
                    >
                      {label}
                    </span>
                    {isAnchor && <span style={anchorBadge}>{tr('锚', 'anchor', locale)}</span>}
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'baseline',
                      gap: 10,
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent-cyan)' }}>
                      {fmt(m.mid)}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      {fmt(m.low)}–{fmt(m.high)}
                    </span>
                    {upside != null && (
                      <span
                        style={{
                          fontSize: 11,
                          color: up ? 'var(--success)' : 'var(--danger)',
                        }}
                      >
                        {up ? '+' : ''}
                        {upside.toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          <a href="#valuation" style={bridgeLink}>
            {tr('完整估值桥', 'Full valuation bridge', locale)} →
          </a>
        </>
      )}

      {/* Market-implied reverse-DCF — the growth/WACC the price bakes in vs our
          cash-flow model. The SAME ReverseDcfHeadline the cover uses for withheld
          targets; here it surfaces when a target shipped (the cover suppressed it to
          keep one price axis). dcfMethod from the same methods array (one source);
          the component returns null when the data can't draw the contrast. */}
      {showMarketImplied && marketImplied && (
        <>
          <h4 style={heading}>{tr('市场隐含', 'Market-Implied', locale)}</h4>
          <ReverseDcfHeadline
            marketImplied={marketImplied}
            dcfMethod={methods.find((m) => m.name === 'dcf') ?? null}
            currentPrice={currentPrice}
            quoteCurrency={quoteCurrency}
          />
        </>
      )}
    </Chapter>
  )
}

const heading: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 12.5,
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
  color: 'var(--text-primary)',
  margin: '22px 0 10px',
}

function colHeading(color: string): React.CSSProperties {
  return {
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color,
    marginBottom: 8,
  }
}

function bridgeRow(isAnchor: boolean): React.CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    padding: '9px 12px',
    borderRadius: 'var(--radius-sm)',
    background: isAnchor
      ? 'color-mix(in srgb, var(--primary) 9%, transparent)'
      : 'var(--bg-card-50)',
    borderLeft: isAnchor ? '2px solid var(--primary)' : '2px solid transparent',
  }
}

const anchorBadge: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--primary)',
  border: '1px solid color-mix(in srgb, var(--primary) 45%, transparent)',
  borderRadius: 999,
  padding: '1px 6px',
}

const bridgeLink: React.CSSProperties = {
  display: 'inline-block',
  marginTop: 10,
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  letterSpacing: '0.04em',
  color: 'var(--secondary)',
  textDecoration: 'none',
}
