// Left rail for the equity_research report — the single navigation flank.
//
// Replaces the old split of a left TOC + a right Version Timeline rail (which
// squeezed the reading column between two sidebars). Now one sticky rail holds:
//   • an identity card (ticker · verdict · company · 12-mo target + spot · confidence)
//   • a CONTENTS | VERSIONS tab switch
//       - CONTENTS: the 13-chapter table of contents with scroll-spy highlight
//       - VERSIONS: the version-history timeline (was the right rail)
// The report body reclaims the full width to the right.

import { useEffect, useState } from 'react'
import type { ArtifactSummaryV5 } from '../../../types/v5'
import { useI18n } from '../../../i18n'
import { formatCurrency } from '../../../utils/format'
import {
  verdictLabel,
  verdictTone,
  normalizeConfidence,
  type ConfidenceTier,
} from '../../../utils/verdict'
import { ConfidenceChip } from '../../../components/ConfidenceChip'
import { VersionTimelineList } from './ReportRightRail'

export interface LeftRailTOCEntry {
  id: string
  num: string
  title: string
}

interface ReportLeftRailProps {
  ticker: string
  companyName?: string | null
  verdict?: string | null
  snapshotPrice?: number | null
  /** Point withheld because price is inside the fair-value band → "Fairly Valued"
   *  (confident HOLD), not a generic "WITHHELD". From deriveReportData. */
  fairlyValued?: boolean
  confidence?: ConfidenceTier | string | null
  quoteCurrency?: string
  entries: LeftRailTOCEntry[]
  currentArtifactId: string
  timeline: ArtifactSummaryV5[]
  reportType: string
}

export function ReportLeftRail({
  ticker,
  companyName = null,
  verdict = null,
  snapshotPrice = null,
  fairlyValued = false,
  confidence = null,
  quoteCurrency = 'USD',
  entries,
  currentArtifactId,
  timeline,
  reportType,
}: ReportLeftRailProps): React.ReactElement {
  const { locale, t } = useI18n()
  const [tab, setTab] = useState<'contents' | 'versions'>('contents')
  const [activeId, setActiveId] = useState<string>(entries[0]?.id ?? '')

  const sameTypeCount = timeline.filter((a) => a.type === reportType).length
  const verdictText = (verdict ?? '').toUpperCase()
  const tone = verdictText ? verdictTone(verdictText) : null
  const tier = normalizeConfidence(typeof confidence === 'string' ? confidence : null)

  // Identity-card headline = the CURRENT version's 12-mo TARGET, read from the
  // SAME timeline entry (`target_price`) the version rows render — so the card can
  // never disagree with its own v-row. Previously this card showed snapshotPrice
  // (the spot the target was computed against) as a bare, unlabelled number, which
  // read as contradicting the target shown in the v-rows + the report body. Spot
  // is kept as a small labelled caption for context.
  const targetPrice = timeline.find((a) => a.id === currentArtifactId)?.target_price ?? null

  // Scroll-spy: highlight the chapter currently under the reader. Root is the
  // real scroll container (#main-scroll), same as the old TOC — the window
  // never scrolls (body is overflow:hidden).
  useEffect(() => {
    if (entries.length === 0) return
    const scrollEl = document.getElementById('main-scroll')
    const observer = new IntersectionObserver(
      (rows) => {
        rows.forEach((row) => {
          if (row.isIntersecting) setActiveId(row.target.id)
        })
      },
      { root: scrollEl ?? null, rootMargin: '-30% 0px -60% 0px' },
    )
    entries.forEach((e) => {
      const el = document.getElementById(e.id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [entries])

  return (
    <aside
      data-testid="report-left-rail"
      style={{
        position: 'sticky',
        top: 64,
        alignSelf: 'start',
        maxHeight: 'calc(100vh - 80px)',
        display: 'flex',
        flexDirection: 'column',
        paddingTop: 18,
        minHeight: 0,
      }}
    >
      {/* identity card */}
      <div
        style={{
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          background: 'var(--bg-card)',
          padding: '14px 15px',
          marginBottom: 18,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 3 }}>
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 19,
              fontWeight: 600,
              letterSpacing: '0.5px',
              color: 'var(--text-primary)',
            }}
          >
            {ticker}
          </span>
          {verdictText && tone && (
            <span
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: '0.16em',
                padding: '3px 9px',
                borderRadius: 6,
                background: tone.bg,
                color: tone.fg,
                border: `1px solid ${tone.border}`,
              }}
            >
              {verdictLabel(verdictText)}
            </span>
          )}
        </div>
        {companyName && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 11 }}>
            {companyName}
          </div>
        )}
        {typeof targetPrice === 'number' ? (
          <>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 17,
                fontWeight: 600,
                color: 'var(--text-primary)',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {formatCurrency(targetPrice, quoteCurrency, locale, 2)}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10.5,
                color: 'var(--text-muted)',
                marginTop: 2,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {t('report.leftRail.targetLabel')}
              {typeof snapshotPrice === 'number' &&
                ` · ${t('report.leftRail.spotLabel')} ${formatCurrency(snapshotPrice, quoteCurrency, locale, 2)}`}
            </div>
          </>
        ) : (
          // No point target. Two very different meanings — show the RIGHT one:
          //   • fairlyValued → price sits inside the fair-value range → "Fairly Valued"
          //     (a confident HOLD conclusion, NOT a failure). Same label the chips
          //     use (targetRange.fairValueLabel).
          //   • otherwise → genuine withhold (M&A / single-method) → "WITHHELD",
          //     mirroring the version row.
          // Spot stays as a small labelled caption: context, never the headline.
          <>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 15,
                fontWeight: 600,
                letterSpacing: '0.04em',
                color: fairlyValued ? 'var(--text-secondary)' : 'var(--text-muted)',
              }}
            >
              {fairlyValued ? t('targetRange.fairValueLabel') : verdictLabel('WITHHELD', locale)}
            </div>
            {typeof snapshotPrice === 'number' && (
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10.5,
                  color: 'var(--text-muted)',
                  marginTop: 2,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {t('report.leftRail.spotLabel')}{' '}
                {formatCurrency(snapshotPrice, quoteCurrency, locale, 2)}
              </div>
            )}
          </>
        )}
        {verdictText && (
          <div style={{ marginTop: 10 }}>
            <ConfidenceChip tier={tier} />
          </div>
        )}
      </div>

      {/* tab switch */}
      <div
        style={{
          display: 'flex',
          gap: 20,
          borderBottom: '1px solid var(--border-soft)',
          marginBottom: 12,
        }}
      >
        <RailTab active={tab === 'contents'} onClick={() => setTab('contents')}>
          {t('report.toc.heading')}
        </RailTab>
        <RailTab active={tab === 'versions'} onClick={() => setTab('versions')}>
          {t('report.timeline.versionCount', { count: sameTypeCount })}
        </RailTab>
      </div>

      {/* tab body — scrolls within the sticky rail */}
      <div style={{ overflowY: 'auto', minHeight: 0, paddingRight: 4, paddingBottom: 12 }}>
        {tab === 'contents' ? (
          <nav>
            {entries.map((entry) => {
              const isActive = entry.id === activeId
              return (
                <a
                  key={entry.id}
                  href={`#${entry.id}`}
                  data-testid={`toc-${entry.id}`}
                  data-active={isActive ? 'true' : 'false'}
                  style={{
                    display: 'flex',
                    gap: 9,
                    alignItems: 'baseline',
                    padding: '6px 0',
                    textDecoration: 'none',
                    fontFamily: 'var(--font-body)',
                    fontSize: 12,
                    lineHeight: 1.3,
                    color: isActive ? 'var(--text-primary)' : 'var(--text-muted)',
                    transition: 'color 0.16s',
                  }}
                >
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10,
                      color: isActive ? 'var(--secondary)' : 'var(--text-dim)',
                      width: 16,
                      flexShrink: 0,
                    }}
                  >
                    {entry.num}
                  </span>
                  {entry.title}
                </a>
              )
            })}
          </nav>
        ) : (
          <VersionTimelineList
            ticker={ticker}
            currentArtifactId={currentArtifactId}
            timeline={timeline}
            reportType={reportType}
          />
        )}
      </div>
    </aside>
  )
}

function RailTab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: active ? 'var(--secondary)' : 'var(--text-muted)',
        background: 'transparent',
        border: 'none',
        borderBottom: `1.5px solid ${active ? 'var(--secondary)' : 'transparent'}`,
        padding: '4px 0 9px',
        marginBottom: -1,
        cursor: 'pointer',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </button>
  )
}
