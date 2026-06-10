// Chapter 00 — Cover page. Single hero block with verdict / target /
// tagline / artifact metadata. See layout invariants;
// we render it as the entry section so PDF exports get a proper cover.

import type { DcfShape, ThesisShape, ValuationMethodShape } from './types'
import { ReverseDcfHeadline } from './ReverseDcfHeadline'
import { verdictLabel, verdictTone } from '../../../utils/verdict'
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
   * When present on a REVIEW cover, shown as a one-liner with a jump to the audit
   * banner — so "why was the target withheld" is answered at a glance, not buried.
   * Null when not withheld, or when the REVIEW came from an upstream gate with no
   * contract evidence (the audit banner still explains those below). */
  withheldReason?: string | null
  /** Reverse-DCF inputs for the REVIEW headline (the verdict, not a probe). The
   * cash-flow ceiling MUST come from the dcf method mid (valuation_synthesis),
   * never dcf.implied_price — that is null in REVIEW state. Null on non-REVIEW
   * reports or legacy artifacts; the headline simply isn't rendered then. */
  marketImplied?: DcfShape['market_implied'] | null
  dcfMethod?: ValuationMethodShape | null
  currentPrice?: number | null
  quoteCurrency?: string
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
}: ChapterCoverProps): React.ReactElement {
  const { locale, t } = useI18n()
  const verdict = (thesis?.recommendation ?? '').toUpperCase()
  const tone = verdictTone(verdict)
  const target = thesis?.price_target ?? null
  // REVIEW headline = the reverse-DCF gap (verdict-grade visual). Only on a
  // genuine withheld REVIEW (no target) with frozen market_implied data.
  const showReverseDcf = verdict === 'REVIEW' && target === null && marketImplied != null

  return (
    <section
      id="cover"
      data-testid="chapter-cover"
      style={{
        margin: '12px 0 28px',
        padding: '28px 28px 24px',
        background:
          'radial-gradient(ellipse 70% 60% at 50% 30%, color-mix(in srgb, var(--secondary) 14%, transparent), transparent 70%), linear-gradient(160deg, color-mix(in srgb, var(--bg-card) 95%, transparent), color-mix(in srgb, var(--bg-deep) 60%, transparent))',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
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
          letterSpacing: '0.08em',
          marginBottom: 14,
        }}
      >
        <span style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.3em' }}>
          FINROBOT {t('chapter.cover.equityResearch')}
        </span>
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
            fontSize: 56,
            letterSpacing: 5,
            color: 'var(--text-primary)',
            textShadow: '0 0 28px color-mix(in srgb, var(--primary) 40%, transparent)',
            lineHeight: 1,
          }}
        >
          {ticker}
        </div>

        {verdict && (
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 28,
              letterSpacing: 4,
              padding: '4px 18px',
              background: tone.bg,
              color: tone.fg,
              border: `1.5px solid ${tone.border}`,
              borderRadius: 6,
              boxShadow: `0 0 18px ${tone.bg}`,
            }}
          >
            {verdictLabel(verdict)}
          </span>
        )}

        {target !== null ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-muted)',
                letterSpacing: '0.08em',
              }}
            >
              {t('chapter.cover.twelveMonthTarget')}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 26,
                fontWeight: 500,
                color: 'var(--text-primary)',
                fontVariantNumeric: 'tabular-nums',
                lineHeight: 1.1,
              }}
            >
              ${target.toFixed(2)}
            </span>
          </div>
        ) : (
          verdict === 'REVIEW' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--text-muted)',
                  letterSpacing: '0.08em',
                }}
              >
                {t('chapter.cover.twelveMonthTarget')}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 18,
                  fontWeight: 500,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.1,
                }}
              >
                {t('chapter.cover.targetWithheld')}
              </span>
            </div>
          )
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

      {verdict === 'REVIEW' && withheldReason && (
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
        {thesis?.price_target_basis && <> · {thesis.price_target_basis}</>}
      </div>

      {thesis?.tagline && (
        <p
          style={{
            marginTop: 14,
            marginBottom: 0,
            fontFamily: 'var(--font-body)',
            fontSize: 14,
            fontStyle: 'italic',
            color: 'var(--accent-cyan)',
            lineHeight: 1.5,
            maxWidth: 720,
            textShadow: '0 0 12px var(--accent-cyan-glow-soft)',
          }}
        >
          "{thesis.tagline}"
        </p>
      )}
    </section>
  )
}
