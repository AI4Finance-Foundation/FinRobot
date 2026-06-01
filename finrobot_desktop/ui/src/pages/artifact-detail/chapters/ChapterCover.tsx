// Chapter 00 — Cover page. Single hero block with verdict / target /
// tagline / artifact metadata. See layout invariants;
// we render it as the entry section so PDF exports get a proper cover.

import type { ThesisShape } from './types'
import { verdictLabel } from '../../../utils/verdict'
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
}

const VERDICT_TONE: Record<string, { bg: string; fg: string; border: string }> = {
  BUY: {
    bg: 'var(--success-soft)',
    fg: 'var(--success)',
    border: 'color-mix(in srgb, var(--success) 55%, transparent)',
  },
  HOLD: {
    bg: 'var(--warning-soft)',
    fg: 'var(--warning)',
    border: 'color-mix(in srgb, var(--warning) 55%, transparent)',
  },
  SELL: {
    bg: 'var(--danger-soft)',
    fg: 'var(--danger)',
    border: 'color-mix(in srgb, var(--danger) 55%, transparent)',
  },
  // Data-health-gate verdict — neutral slate, deliberately NOT 涨绿跌红:
  // REVIEW makes no directional call, so colouring it like a buy/sell would
  // misrepresent the (withheld) conclusion.
  REVIEW: {
    bg: 'var(--neutral-soft)',
    fg: 'var(--text-secondary)',
    border: 'var(--neutral-edge)',
  },
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
}: ChapterCoverProps): React.ReactElement {
  const { locale, t } = useI18n()
  const verdict = (thesis?.recommendation ?? '').toUpperCase()
  const tone = VERDICT_TONE[verdict] ?? VERDICT_TONE.HOLD
  const target = thesis?.price_target ?? null

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
            textShadow: '0 0 28px rgba(59, 130, 246, 0.4)',
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
            textShadow: '0 0 12px rgba(34, 211, 238, 0.2)',
          }}
        >
          "{thesis.tagline}"
        </p>
      )}
    </section>
  )
}
