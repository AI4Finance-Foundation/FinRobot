// Chapter 05 — Recent News & Events. The LLM `news_summary` leads as the
// "结论先行" takeaway (the AI-narrative card); below it the SOURCED EVENT FEED
// renders catalyst_analysis.events as chronological evidence — what was
// reported, when, by whom, with what sentiment. This is the traceability moat:
// every item carries its real `published` date and a source chip linking to
// the provider (SEC filing or the finnhub API endpoint, labelled honestly —
// never a fabricated "read article" claim).
//
// Distinct from the Catalysts chapter (ch 09): that chapter shows only the
// AGGREGATE signal (net direction + category mix) and re-lists NO events, so
// THIS feed is the single home for the itemized record — no probability column
// here or there (a per-event probability was a hardcoded constant = fake
// precision). No aggregate sentiment gauge in this feed; the gauge lives once in
// the Catalysts chapter, computed on de-duplicated events upstream.

import type { CSSProperties } from 'react'

import { Chapter, Narrative, SubChapter } from './ChapterBase'
import type { CatalystAnalysisShape, CatalystEventShape, ThesisShape } from './types'
import { useI18n, type Locale } from '../../../i18n'
import { formatSourceDate } from '../../../utils/format'
import { ImpactMeter } from '../../../components/ImpactMeter'
import { MarkdownLite } from '../../../components/MarkdownLite'

interface ChapterNewsProps {
  thesis: ThesisShape | null
  catalysts: CatalystAnalysisShape | null
}

export function ChapterNews({ thesis, catalysts }: ChapterNewsProps): React.ReactElement {
  const { t, locale } = useI18n()
  const summary = thesis?.news_summary ?? null
  const events = sortFeed(catalysts?.events ?? [])

  return (
    <Chapter id="news">
      {summary ? (
        <Narrative>
          <MarkdownLite text={summary} />
        </Narrative>
      ) : (
        <p style={mutedNote}>{t('chapter.news.empty')}</p>
      )}

      <SubChapter heading={t('chapter.news.feed.heading')}>
        {events.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {events.map((e, i) => (
              <FeedRow
                key={`${e.published ?? 'undated'}-${e.category}-${i}-${e.headline.slice(0, 24)}`}
                event={e}
                locale={locale}
                t={t}
              />
            ))}
          </div>
        ) : (
          <p style={mutedNote}>{t('chapter.news.feed.empty')}</p>
        )}
      </SubChapter>

      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-dim)',
          marginTop: 10,
          letterSpacing: '0.04em',
        }}
      >
        {t('chapter.news.snapshotNote')}
      </p>
    </Chapter>
  )
}

// Chronological feed: newest `published` first; events with no date sort last
// (a missing date can't claim a position in the timeline). Stable for equal
// dates (kept in original order) via a presence-first comparator.
function sortFeed(events: CatalystEventShape[]): CatalystEventShape[] {
  return [...events].sort((a, b) => {
    const da = a.published ?? null
    const db = b.published ?? null
    if (da && db) return da < db ? 1 : da > db ? -1 : 0
    if (da) return -1
    if (db) return 1
    return 0
  })
}

type Translator = (key: string, params?: Record<string, string | number>) => string

function FeedRow({
  event,
  locale,
  t,
}: {
  event: CatalystEventShape
  locale: Locale
  t: Translator
}): React.ReactElement {
  // 涨绿跌红 — the per-item sentiment lives on a NON-text channel (left border)
  // so it's scannable without colour-coding the prose. Same tone mapping the
  // Catalysts chapter uses (positive→success / negative→danger / neutral→warning).
  const border =
    event.sentiment === 'positive'
      ? 'var(--success)'
      : event.sentiment === 'negative'
        ? 'var(--danger)'
        : 'var(--warning)'

  const src = deriveSource(event.url)

  return (
    <div
      data-testid="news-feed-row"
      data-sentiment={event.sentiment}
      style={{
        padding: '10px 14px',
        background: 'var(--bg-card-50)',
        borderLeft: `2px solid ${border}`,
        borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
        fontSize: 12.5,
        color: 'var(--text-secondary)',
        lineHeight: 1.55,
      }}
    >
      <div style={{ fontFamily: 'var(--font-body)' }}>{event.headline}</div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 8,
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-muted)',
          marginTop: 6,
        }}
      >
        <SourceChip name={src.name} url={event.url ?? null} t={t} />
        {event.published && <span>{formatSourceDate(event.published, locale)}</span>}
        <CategoryChip category={event.category} />
        <ImpactMeter score={event.impact_score} />
      </div>
    </div>
  )
}

// Honest source provider derived from the url domain. finnhub.io URLs are API
// endpoints (NOT article pages) and SEC URLs are real filings — so the chip is
// a neutral "source" affordance (external-link glyph), never a "read article"
// claim we can't honour. Unknown domains surface as the bare hostname.
function deriveSource(url: string | null | undefined): { name: string } {
  if (!url) return { name: '' }
  let host = ''
  try {
    host = new URL(url).hostname.toLowerCase()
  } catch {
    return { name: url }
  }
  if (host === 'finnhub.io' || host.endsWith('.finnhub.io')) return { name: 'Finnhub' }
  if (host === 'sec.gov' || host.endsWith('.sec.gov')) return { name: 'SEC EDGAR' }
  return { name: host.replace(/^www\./, '') }
}

function SourceChip({
  name,
  url,
  t,
}: {
  name: string
  url: string | null
  t: Translator
}): React.ReactElement | null {
  // No url → source-less row (degrade: render nothing rather than a dead chip).
  if (!url || !name) return null
  const glyph = (
    <svg width="9" height="9" viewBox="0 0 12 12" aria-hidden style={{ flexShrink: 0 }}>
      {/* External-link glyph — a "source" affordance, NOT a "read article" claim.
          Hand-drawn inline SVG per cosmic spec §6.5 (simple icon). */}
      <path
        d="M4.5 2.5H2.5V9.5H9.5V7.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M7 2.5H9.5V5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M9.5 2.5L5.5 6.5" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  )
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={t('chapter.news.feed.sourceTooltip', { source: name })}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 7px',
        borderRadius: 999,
        background: 'color-mix(in srgb, var(--accent-cyan) 12%, transparent)',
        color: 'var(--accent-cyan)',
        textDecoration: 'none',
        letterSpacing: '0.04em',
      }}
    >
      <span>{name}</span>
      {glyph}
    </a>
  )
}

// Maps the raw category to a subtle cosmic accent so categories are glanceable
// without minting new tokens. Anything unmapped falls back to a neutral tint.
const CATEGORY_ACCENT: Record<string, string> = {
  management: 'var(--secondary)',
  product_launch: 'var(--accent-cyan)',
  acquisition: 'var(--accent-cyan)',
  market: 'var(--primary)',
  regulatory: 'var(--accent-amber)',
  legal: 'var(--accent-amber)',
  financial: 'var(--accent-pink)',
  earnings: 'var(--accent-pink)',
}

function CategoryChip({ category }: { category: string }): React.ReactElement {
  const accent = CATEGORY_ACCENT[category.toLowerCase()] ?? 'var(--text-muted)'
  return (
    <span
      style={{
        padding: '2px 7px',
        borderRadius: 999,
        background: `color-mix(in srgb, ${accent} 14%, transparent)`,
        color: accent,
        letterSpacing: '0.04em',
      }}
    >
      {titleCase(category)}
    </span>
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

const mutedNote: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'var(--bg-card-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  lineHeight: 1.7,
}
