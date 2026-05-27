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
    bg: 'rgba(22, 163, 74, 0.18)',
    fg: 'var(--success)',
    border: 'rgba(22, 163, 74, 0.55)',
  },
  HOLD: {
    bg: 'rgba(217, 119, 6, 0.18)',
    fg: 'var(--warning)',
    border: 'rgba(217, 119, 6, 0.55)',
  },
  SELL: {
    bg: 'rgba(220, 38, 38, 0.18)',
    fg: 'var(--danger)',
    border: 'rgba(220, 38, 38, 0.55)',
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
  const { locale } = useI18n()
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
          'radial-gradient(ellipse 70% 60% at 50% 30%, rgba(139, 92, 246, 0.14), transparent 70%), linear-gradient(160deg, rgba(15, 15, 34, 0.95), rgba(10, 10, 24, 0.6))',
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
          FINAGENT {locale === 'en' ? 'EQUITY RESEARCH' : '股票研报'}
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

        {target !== null && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-muted)',
                letterSpacing: '0.08em',
              }}
            >
              {locale === 'en' ? '12-MONTH TARGET' : '12 个月目标价'}
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
        {locale === 'en' ? 'TYPE' : '类型'} {reportType.toUpperCase()}
        {versionNumber !== null && (
          <>
            {' · '}
            {locale === 'en'
              ? `v${versionNumber}${totalVersions > 1 ? ` of ${totalVersions}` : ''}`
              : `第 v${versionNumber} 版${totalVersions > 1 ? ` · 共 ${totalVersions} 份` : ''}`}
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
