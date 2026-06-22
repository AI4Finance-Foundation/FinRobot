// Chapter 00 — Cover page. Single hero block with verdict / target /
// tagline / artifact metadata. See layout invariants;
// we render it as the entry section so PDF exports get a proper cover.

import type { ConfidenceTier } from '../../../utils/verdict'
import type { DcfShape, ThesisShape, ValuationMethodShape } from './types'
import { ReverseDcfHeadline } from './ReverseDcfHeadline'
import { ConfidenceChip } from '../../../components/ConfidenceChip'
import { TargetRange } from '../../../components/TargetRange'
import { verdictLabel, verdictTone, normalizeConfidence } from '../../../utils/verdict'
import { formatDate } from '../../../utils/format'
import { useI18n } from '../../../i18n'

interface ChapterCoverProps {
  ticker: string
  thesis: ThesisShape | null
  createdAt: string | null
  artifactId: string
  computeVersion: string | null
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
}

export function ChapterCover({
  ticker,
  thesis,
  createdAt,
  artifactId: _artifactId,
  computeVersion,
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
          fontSize: 9.5,
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
      {thesis?.price_target_basis && (
        <div style={{ marginTop: 16, maxWidth: 760 }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9.5,
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
        style={{
          marginTop: 12,
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          letterSpacing: '0.06em',
        }}
      >
        {t('chapter.cover.typeLabel')} {reportType.toUpperCase()}
        {versionNumber !== null && (
          <>
            {' · '}
            {totalVersions > 1
              ? t('chapter.cover.versionOfTotal', { version: versionNumber, total: totalVersions })
              : t('chapter.cover.version', { version: versionNumber })}
          </>
        )}
        {computeVersion && <> · {computeVersion}</>}
      </div>

      {thesis?.tagline && (
        <p
          style={{
            marginTop: 18,
            marginBottom: 0,
            fontFamily: 'var(--font-body)',
            fontSize: 14.5,
            fontStyle: 'italic',
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
            maxWidth: 720,
          }}
        >
          "{thesis.tagline}"
        </p>
      )}
    </section>
  )
}
