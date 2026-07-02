// Chapter 09 — Catalyst Signal. The AGGREGATE directional read of the recent
// catalyst/news flow: overall sentiment direction, net sentiment score, and the
// category mix (where the flow is concentrated). It deliberately does NOT
// re-list individual events — those are itemized ONCE, with their sources and
// dates, in Recent News & Events (ch 08). Forward-looking bull/bear catalysts
// live ONCE in the Investment Thesis (ch 02). Each fact therefore appears in
// exactly one chapter.
//
// This replaced the old Positive / Risks / Events-to-Monitor buckets, which
// re-rendered the SAME catalyst_analysis.events the news feed already carried
// (an analyst read the same headlines twice), swept past 8-K filings into a
// forward-looking "events to monitor" list (a category error — those are
// historical, not upcoming), and printed a per-event probability column that was
// a hardcoded constant (0.7 for news, 1.0 for 8-Ks) = fake precision. The
// aggregate read here uses only computed, traceable quantities: net_sentiment is
// summarized upstream on DE-DUPLICATED events (cluster_near_duplicates runs
// before summarize_catalyst_outlook), and category_breakdown is a pure count.

import type { CSSProperties } from 'react'

import { Chapter, SubChapter } from './ChapterBase'
import type { CatalystAnalysisShape } from './types'
import { useI18n } from '../../../i18n'

interface ChapterCatalystsProps {
  catalysts: CatalystAnalysisShape | null
}

type Translator = (key: string, params?: Record<string, string | number>) => string

export function ChapterCatalysts({ catalysts }: ChapterCatalystsProps): React.ReactElement {
  const { t } = useI18n()
  const events = catalysts?.events ?? []
  const breakdown = catalysts?.category_breakdown ?? {}
  const hasSignal = events.length > 0

  return (
    <Chapter id="catalysts">
      {hasSignal ? (
        <>
          <SubChapter heading={t('chapter.catalysts.directionalHeading')}>
            <DirectionalRead
              overall={catalysts?.overall_sentiment}
              net={catalysts?.net_sentiment}
              count={events.length}
              t={t}
            />
          </SubChapter>

          {Object.keys(breakdown).length > 0 && (
            <SubChapter heading={t('chapter.catalysts.categoryHeading')}>
              <CategoryMix breakdown={breakdown} />
            </SubChapter>
          )}

          <p style={crossRefNote}>{t('chapter.catalysts.crossRef')}</p>
        </>
      ) : (
        <p style={mutedNote}>{t('chapter.catalysts.empty')}</p>
      )}
    </Chapter>
  )
}

// The directional read: the net catalyst signal over the event set. 涨绿跌红 —
// the sentiment token carries direction on a colour channel; net_sentiment is a
// computed mean (impact × sign, clamped [-5, 5]) so it is a real, traceable
// figure, not a fabricated point.
function DirectionalRead({
  overall,
  net,
  count,
  t,
}: {
  overall: string | undefined
  net: number | undefined
  count: number
  t: Translator
}): React.ReactElement {
  const tone =
    overall === 'bullish'
      ? 'var(--success)'
      : overall === 'bearish'
        ? 'var(--danger)'
        : 'var(--warning)'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', gap: 12 }}>
        <span
          data-testid="catalyst-direction"
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: '0.02em',
            color: tone,
          }}
        >
          {overall ? overall.toUpperCase() : '—'}
        </span>
        {net !== undefined && (
          <span
            style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--text-muted)' }}
          >
            {t('chapter.catalysts.netSentiment')}{' '}
            <span style={{ color: 'var(--accent-cyan)' }}>
              {net >= 0 ? '+' : ''}
              {net.toFixed(2)}
            </span>
          </span>
        )}
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
        {t('chapter.catalysts.eventCount', { count })}
      </span>
    </div>
  )
}

// Category mix: where the recent catalyst flow is concentrated. A pure count per
// category from category_breakdown — no headlines re-listed (they live in the
// news feed). Accents mirror the News feed's CategoryChip so a category reads the
// same colour in both chapters; unmapped categories fall back to neutral.
const CATEGORY_ACCENT: Record<string, string> = {
  management: 'var(--secondary)',
  product_launch: 'var(--accent-cyan)',
  acquisition: 'var(--accent-cyan)',
  market: 'var(--primary)',
  regulatory: 'var(--accent-amber)',
  earnings: 'var(--accent-pink)',
}

function CategoryMix({ breakdown }: { breakdown: Record<string, number> }): React.ReactElement {
  const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1])
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {entries.map(([category, count]) => {
        const accent = CATEGORY_ACCENT[category.toLowerCase()] ?? 'var(--text-muted)'
        return (
          <span
            key={category}
            data-testid="catalyst-category"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              borderRadius: 999,
              background: `color-mix(in srgb, ${accent} 14%, transparent)`,
              color: accent,
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              letterSpacing: '0.04em',
            }}
          >
            {titleCase(category)}
            <strong style={{ fontVariantNumeric: 'tabular-nums' }}>{count}</strong>
          </span>
        )
      })}
    </div>
  )
}

// "product_launch" → "Product Launch". Source-faithful: underscores → spaces,
// each word capitalised. Locale-invariant (the raw categories are English keys).
function titleCase(raw: string): string {
  return raw
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

const crossRefNote: CSSProperties = {
  marginTop: 18,
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  color: 'var(--text-dim)',
  lineHeight: 1.7,
  letterSpacing: '0.02em',
}

const mutedNote: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'var(--bg-card-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
