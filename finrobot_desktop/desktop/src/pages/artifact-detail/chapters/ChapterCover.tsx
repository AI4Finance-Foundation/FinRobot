// Chapter 00 — Cover page. Single hero block with verdict / target /
// tagline / artifact metadata. See layout invariants;
// we render it as the entry section so PDF exports get a proper cover.

import type { ConfidenceTier } from '../../../utils/verdict'
import type { DcfShape, ThesisShape, ValuationMethodShape } from './types'
import { ReverseDcfHeadline } from './ReverseDcfHeadline'
import { ConfidenceChip } from '../../../components/ConfidenceChip'
import { TargetRange } from '../../../components/TargetRange'
import { verdictLabel, verdictTone, normalizeConfidence } from '../../../utils/verdict'
import { formatCurrency, formatDate } from '../../../utils/format'
import { METHOD_LABEL } from '../../../components/charts/FootballField'
import { useI18n } from '../../../i18n'
import type { Locale } from '../../../i18n'

interface ChapterCoverProps {
  ticker: string
  thesis: ThesisShape | null
  createdAt: string | null
  artifactId: string
  reportType: string
  versionNumber: number | null
  totalVersions: number
  /** Output-contract withhold reason (the first `[CONTRACT/Cn]` evidence string).
   * When the point target is withheld, shown as a one-liner with a jump to the
   * audit banner — so "why was the target withheld" is answered at a glance, not
   * buried. Null when not withheld, or when the withhold came from an upstream
   * gate with no contract evidence (the audit banner still explains those). */
  withheldReason?: string | null
  /** Reverse-DCF inputs for the withheld-target headline (the verdict, not a
   * probe). The cash-flow ceiling MUST come from the dcf method mid
   * (valuation_synthesis), never dcf.implied_price — that is null when the
   * target is withheld. Null on reports with a target or legacy artifacts. */
  marketImplied?: DcfShape['market_implied'] | null
  dcfMethod?: ValuationMethodShape | null
  currentPrice?: number | null
  quoteCurrency?: string
  /** Confidence dial (valuation_synthesis). Drives the tier chip + the
   * TargetRange band width. Defaults to 'low' on legacy artifacts. */
  confidence?: ConfidenceTier | string | null
  targetLow?: number | null
  targetHigh?: number | null
  anchorMethod?: string | null
  /** Valuation methods (valuation_synthesis.methods) — drives the readable
   * price-target-basis readout that replaces the raw dev string on the cover.
   * Empty/legacy → the readout falls back to the verbatim basis string. */
  methods?: ValuationMethodShape[]
  /** Method names the engine flagged as cross-method outliers (>30% from the
   * median). Consumed verbatim — the cover NEVER recomputes dispersion. */
  outlierMethods?: string[]
  /** Standing street-context line (the backend's street_range_disclosure fact
   * line), relocated here from the ⚠ compute-warnings pile to sit beside the
   * target it qualifies. Renders whenever the sell-side distribution was fetched;
   * the out-of-consensus clause rides the same line when the target sits entirely
   * outside the band. null only when the sell-side fetch failed / no data exists. */
  streetContext?: string | null
}

export function ChapterCover({
  ticker,
  thesis,
  createdAt,
  artifactId: _artifactId,
  reportType,
  versionNumber,
  totalVersions,
  withheldReason = null,
  marketImplied = null,
  dcfMethod = null,
  currentPrice = null,
  quoteCurrency = 'USD',
  confidence = null,
  targetLow = null,
  targetHigh = null,
  anchorMethod = null,
  methods = [],
  outlierMethods = [],
  streetContext = null,
}: ChapterCoverProps): React.ReactElement {
  const { locale, t } = useI18n()
  const verdict = (thesis?.recommendation ?? '').toUpperCase()
  const tone = verdictTone(verdict)
  const target = thesis?.price_target ?? null
  const tier = normalizeConfidence(typeof confidence === 'string' ? confidence : null)
  // Point target honestly withheld — gate on target===null (verdict-independent).
  const targetWithheld = !!verdict && target === null
  // Withheld-target headline = the reverse-DCF gap (verdict-grade visual). Only
  // when the point is withheld AND frozen market_implied data exists to draw it.
  const showReverseDcf = targetWithheld && marketImplied != null

  return (
    <section
      id="cover"
      data-testid="chapter-cover"
      style={{
        margin: '8px 0 0',
        position: 'relative',
        scrollMarginTop: 84,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          marginBottom: 24,
        }}
      >
        <span>FINROBOT {t('chapter.cover.equityResearch')}</span>
        <span>{createdAt ? formatDate(createdAt, locale, 'datetime') : ''}</span>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          flexWrap: 'wrap',
        }}
      >
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 52,
            fontWeight: 600,
            letterSpacing: '-1px',
            color: 'var(--text-primary)',
            lineHeight: 1,
          }}
        >
          {ticker}
        </div>

        {verdict && (
          <span
            data-testid="cover-verdict"
            data-verdict={verdict}
            data-confidence={tier}
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 16,
              fontWeight: 600,
              letterSpacing: '0.18em',
              padding: '7px 16px',
              background: tone.bg,
              color: tone.fg,
              border: `1px solid ${tone.border}`,
              borderRadius: 7,
            }}
          >
            {verdictLabel(verdict)}
          </span>
        )}

        {/* Confidence tier — a NON-hue channel beside the directional badge. */}
        {verdict && <ConfidenceChip tier={tier} />}

        {/* TargetRange: live tick + point tick (AT the anchor) + the confidence-
            scaled band. In the withheld state the point tick is dropped — the
            rating still stands on direction, only the precise number is held.
            SUPPRESSED when the reverse-DCF gap headline renders below: that
            headline already carries the live price (ruler), the cash-flow band
            (anchor) and the gap — a second band+live-tick here was the cover's
            worst duplication (live price drawn 3-4×). One price axis, one place. */}
        {(target !== null || targetWithheld) && !showReverseDcf && (
          <TargetRange
            point={target}
            low={targetLow}
            high={targetHigh}
            currentPrice={currentPrice}
            confidence={tier}
            quoteCurrency={quoteCurrency}
            anchorMethod={anchorMethod}
          />
        )}
      </div>

      {showReverseDcf && marketImplied && (
        <ReverseDcfHeadline
          marketImplied={marketImplied}
          dcfMethod={dcfMethod}
          currentPrice={currentPrice}
          quoteCurrency={quoteCurrency}
        />
      )}

      {/* Price-target basis — how the target was built (e.g. "dcf $189 · comps_pe
          $193 · ev_ebitda $265, weighted"). Promoted from the 10px mono metadata
          footer (where it sat beside the version string) to a labelled line right
          under the target hero — the provenance of the headline number is a
          first-class citizen, not a footnote. */}
      {thesis?.price_target_basis &&
        (target !== null && !targetWithheld && methods.length > 0 ? (
          // Normal case: render a clean, scannable readout from the structured
          // methods — the raw `price_target_basis` dev string ("dcf=$189(wt=0.85),
          // …→$210. Range […]") reads as developer-ese on the cover. The verbatim
          // string still serves the LLM prompt / contract / non-normal fallback.
          <PriceTargetReadout
            methods={methods}
            outlierMethods={outlierMethods}
            target={target}
            low={targetLow}
            high={targetHigh}
            currentPrice={currentPrice}
            quoteCurrency={quoteCurrency}
            locale={locale}
          />
        ) : (
          // Withheld / fairly-valued / legacy: keep the verbatim basis — it carries
          // the carefully-worded edge-case reasoning the readout can't reconstruct.
          <div style={{ marginTop: 16, maxWidth: 760 }}>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10.5,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
                marginBottom: 5,
              }}
            >
              {locale === 'en' ? 'Price Target Basis' : '目标定价依据'}
            </div>
            <p
              style={{
                margin: 0,
                fontFamily: 'var(--font-body)',
                fontSize: 12.5,
                lineHeight: 1.6,
                color: 'var(--text-secondary)',
              }}
            >
              {thesis.price_target_basis}
            </p>
          </div>
        ))}

      {/* Standing street-context line, beside the target it qualifies — relocated
          from the ⚠ compute-warnings pile (batch 1a), widened 2026-07-09 (BACKLOG
          A9/B1) from an out-of-band-only disclosure to always render whenever the
          sell-side distribution is available. Calm / muted, NOT amber: it is
          context on an already-disclosed fact, not a defect. The prose is
          self-labelling ("Street context: …") and carries no new number. */}
      {streetContext && (
        <p
          data-testid="cover-street-context"
          style={{
            margin: '12px 0 0',
            maxWidth: 760,
            paddingLeft: 11,
            borderLeft: '2px solid var(--border-soft)',
            fontFamily: 'var(--font-body)',
            fontSize: 12,
            lineHeight: 1.55,
            color: 'var(--text-muted)',
          }}
        >
          {streetContext}
        </p>
      )}

      {targetWithheld && withheldReason && (
        <a
          href="#report-audit-banner"
          data-testid="cover-withheld-reason"
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 9,
            marginTop: 16,
            padding: '11px 14px',
            maxWidth: 760,
            background: 'color-mix(in srgb, var(--warning) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--warning) 34%, transparent)',
            borderRadius: 'var(--radius-sm)',
            textDecoration: 'none',
          }}
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--warning)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
            style={{ flexShrink: 0, marginTop: 1 }}
          >
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <span
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 12.5,
              lineHeight: 1.55,
              color: 'var(--text-secondary)',
            }}
          >
            {withheldReason}
            <span style={{ color: 'var(--warning)', whiteSpace: 'nowrap', fontWeight: 500 }}>
              {' ↓'}
            </span>
          </span>
        </a>
      )}

      <div
        data-testid="cover-meta"
        style={{
          marginTop: 12,
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          letterSpacing: '0.06em',
        }}
      >
        {t('chapter.cover.typeLabel')} {reportType.replace(/_/g, ' ').toUpperCase()}
        {versionNumber !== null && (
          <>
            {' · '}
            {totalVersions > 1
              ? t('chapter.cover.versionOfTotal', { version: versionNumber, total: totalVersions })
              : t('chapter.cover.version', { version: versionNumber })}
          </>
        )}
      </div>
    </section>
  )
}

// Readable replacement for the raw `price_target_basis` dev string on the cover.
// Renders the SAME provenance an analyst wants — which methods, what each says,
// the blend, the range, and where the live price sits relative to it — but as a
// scannable readout instead of "dcf=$189(wt=0.85), …→$210. Range […]". Pure
// presentation: every number is passed in pre-computed (methods / target / band /
// outlier flags come straight from valuation_synthesis), nothing is recomputed or
// fabricated. Full method weights / ranges / football field live in the Valuation
// chapter (deep-linked), so the cover shows the gist, not the spreadsheet.
function PriceTargetReadout({
  methods,
  outlierMethods,
  target,
  low,
  high,
  currentPrice,
  quoteCurrency,
  locale,
}: {
  methods: ValuationMethodShape[]
  outlierMethods: string[]
  target: number
  low: number | null
  high: number | null
  currentPrice: number | null
  quoteCurrency: string
  locale: Locale
}): React.ReactElement {
  const en = locale === 'en'
  const cur = (n: number): string => formatCurrency(n, quoteCurrency, locale, 0)
  // Ascending by mid so dispersion reads left→right — a tight cluster then any
  // high outlier sits visibly at the end.
  const sorted = [...methods].sort((a, b) => a.mid - b.mid)
  const outlierSet = new Set(outlierMethods)

  // Honest live-vs-range position — the gap IS the signal. Deterministic from the
  // numbers (no judgement, no fabrication): above the whole band = no margin of
  // safety (bearish/red), below = margin of safety (green), inside = neutral.
  let position: { text: string; tone: string } | null = null
  if (currentPrice !== null && low !== null && high !== null) {
    if (currentPrice > high) {
      position = {
        text: en
          ? `Live ${cur(currentPrice)} sits above the entire range — no margin of safety`
          : `现价 ${cur(currentPrice)} 高于整个区间上沿,无安全边际`,
        tone: 'var(--danger)',
      }
    } else if (currentPrice < low) {
      position = {
        text: en
          ? `Live ${cur(currentPrice)} sits below the entire range — margin of safety`
          : `现价 ${cur(currentPrice)} 低于整个区间下沿,有安全边际`,
        tone: 'var(--success)',
      }
    } else {
      position = {
        text: en
          ? `Live ${cur(currentPrice)} sits within the range`
          : `现价 ${cur(currentPrice)} 落在区间内`,
        tone: 'var(--text-muted)',
      }
    }
  }

  return (
    <div style={{ marginTop: 16, maxWidth: 760 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          gap: 12,
          marginBottom: 8,
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--text-muted)',
          }}
        >
          {en ? 'Price Target Basis' : '目标定价依据'}
        </span>
        <a
          href="#valuation"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '0.08em',
            color: 'var(--primary)',
            textDecoration: 'none',
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          {en ? 'Full valuation ↓' : '详见估值章 ↓'}
        </a>
      </div>

      {/* method values — mono, dispersion visible; the engine-flagged outlier is
          dimmed + tagged (read from outlier_methods, never recomputed here) */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'baseline',
          gap: '4px 14px',
          fontFamily: 'var(--font-mono)',
          fontSize: 13.5,
        }}
      >
        {sorted.map((m) => {
          const isOutlier = outlierSet.has(m.name)
          return (
            <span key={m.name} style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6 }}>
              <span style={{ color: 'var(--text-muted)' }}>
                {METHOD_LABEL[m.name] ?? m.name.toUpperCase()}
              </span>
              <span
                style={{
                  color: isOutlier ? 'var(--text-dim)' : 'var(--text-primary)',
                  fontWeight: 500,
                }}
              >
                {cur(m.mid)}
              </span>
              {isOutlier && (
                <span
                  style={{
                    fontSize: 9.5,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    color: 'var(--warning)',
                  }}
                >
                  {en ? 'outlier' : '离群'}
                </span>
              )}
            </span>
          )
        })}
      </div>

      <div
        style={{
          marginTop: 8,
          fontFamily: 'var(--font-mono)',
          fontSize: 12.5,
          color: 'var(--text-muted)',
        }}
        title={
          en
            ? 'Weights = data quality, not prediction accuracy'
            : '权重 = 各方法数据质量,非预测准确度'
        }
      >
        {en ? 'Data-quality weighted' : '按数据质量加权'}
        {' → '}
        <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
          {en ? 'Target' : '目标'} {cur(target)}
        </span>
        {low !== null && high !== null && (
          <span style={{ color: 'var(--text-dim)' }}>
            {`  ·  ${en ? 'Range' : '区间'} ${cur(low)}–${cur(high)}`}
          </span>
        )}
      </div>

      {position && (
        <div
          style={{
            marginTop: 6,
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: position.tone,
          }}
        >
          {position.text}
        </div>
      )}
    </div>
  )
}
