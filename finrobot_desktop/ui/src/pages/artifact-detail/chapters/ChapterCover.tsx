// Chapter 00 — Cover page. Single hero block with verdict / target /
// tagline / artifact metadata. FinRobot has a similar header surface;
// we render it as the entry section so PDF exports get a proper cover.

import type { ThesisShape } from './types'

interface ChapterCoverProps {
  ticker: string
  thesis: ThesisShape | null
  createdAt: string | null
  artifactId: string
  computeVersion: string | null
  reportType: string
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
  artifactId,
  computeVersion,
  reportType,
}: ChapterCoverProps): React.ReactElement {
  const verdict = (thesis?.recommendation ?? '').toUpperCase()
  const tone = VERDICT_TONE[verdict] ?? VERDICT_TONE.HOLD
  const target = thesis?.price_target ?? null

  return (
    <section
      id="cover"
      data-testid="chapter-cover"
      style={{
        margin: '24px 0 56px',
        padding: '56px 32px',
        background:
          'radial-gradient(ellipse 70% 50% at 50% 30%, rgba(139, 92, 246, 0.18), transparent 70%), linear-gradient(160deg, rgba(15, 15, 34, 0.95), rgba(10, 10, 24, 0.6))',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        position: 'relative',
        scrollMarginTop: 84,
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: 20,
          left: 32,
          fontFamily: 'var(--font-display)',
          fontSize: 11,
          color: 'var(--text-muted)',
          letterSpacing: '0.3em',
        }}
      >
        FINAGENT EQUITY RESEARCH
      </span>
      <span
        style={{
          position: 'absolute',
          top: 20,
          right: 32,
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
        }}
      >
        {createdAt ? new Date(createdAt).toLocaleString('zh-CN') : 'REPORT'}
      </span>

      <div
        style={{
          marginTop: 32,
          fontFamily: 'var(--font-display)',
          fontSize: 96,
          letterSpacing: 8,
          color: 'var(--text-primary)',
          textShadow: '0 0 40px rgba(59, 130, 246, 0.45)',
          lineHeight: 1,
        }}
      >
        {ticker}
      </div>

      <div
        style={{
          marginTop: 22,
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          letterSpacing: '0.08em',
        }}
      >
        TYPE {reportType.toUpperCase()} · ARTIFACT {artifactId.slice(0, 12)}
        {computeVersion && <> · {computeVersion}</>}
      </div>

      {(verdict || target !== null) && (
        <div
          style={{
            marginTop: 36,
            display: 'flex',
            alignItems: 'center',
            gap: 28,
            flexWrap: 'wrap',
          }}
        >
          {verdict && (
            <span
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 56,
                letterSpacing: 8,
                padding: '6px 32px',
                background: tone.bg,
                color: tone.fg,
                border: `2px solid ${tone.border}`,
                borderRadius: 8,
                boxShadow: `0 0 32px ${tone.bg}`,
              }}
            >
              {verdict}
            </span>
          )}
          {target !== null && (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  letterSpacing: '0.1em',
                  textTransform: 'uppercase',
                }}
              >
                12-MONTH TARGET
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 48,
                  fontWeight: 500,
                  color: 'var(--text-primary)',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                ${target.toFixed(2)}
              </span>
              {thesis?.price_target_basis && (
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: 'var(--text-muted)',
                  }}
                >
                  {thesis.price_target_basis}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {thesis?.tagline && (
        <p
          style={{
            marginTop: 26,
            fontFamily: 'var(--font-body)',
            fontSize: 17,
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

      <div
        style={{
          marginTop: 24,
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-dim)',
          letterSpacing: '0.1em',
        }}
      >
        PREPARED BY FINAGENT · DETERMINISTIC COMPUTE + LLM NARRATIVE
      </div>
    </section>
  )
}
