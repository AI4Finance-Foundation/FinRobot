// Chapter 07 — Key Catalysts. Three groups mirroring the standard
// Positive / Risks / Events-to-Monitor split. Pulls structured catalyst
// events from the catalyst_analysis pipeline step.

import { Chapter, SubChapter } from './ChapterBase'
import type { CatalystAnalysisShape, CatalystEventShape, ThesisShape } from './types'
import { useI18n } from '../../../i18n'
import { ImpactMeter } from '../../../components/ImpactMeter'

interface ChapterCatalystsProps {
  catalysts: CatalystAnalysisShape | null
  thesis: ThesisShape | null
}

export function ChapterCatalysts({ catalysts, thesis }: ChapterCatalystsProps): React.ReactElement {
  const { t } = useI18n()
  const top_positive = catalysts?.top_positive ?? []
  const top_negative = catalysts?.top_negative ?? []
  const thesisCatalysts = thesis?.catalysts ?? []
  const thesisRisks = thesis?.risks ?? []

  // Events to monitor: union of high-impact future events without strong sentiment skew
  const monitor = (catalysts?.events ?? []).filter(
    (e) => e.sentiment === 'neutral' && e.impact_score >= 3,
  )

  return (
    <Chapter id="catalysts">
      <SubChapter heading={`↑ ${t('chapter.catalysts.positiveHeading')}`}>
        {top_positive.length > 0 ? (
          <CatalystList items={top_positive} tone="positive" />
        ) : thesisCatalysts.length > 0 ? (
          <BulletList items={thesisCatalysts} tone="positive" />
        ) : (
          <p style={mutedNote}>{t('chapter.catalysts.emptyPositive')}</p>
        )}
      </SubChapter>

      <SubChapter heading={`↓ ${t('chapter.catalysts.riskHeading')}`}>
        {top_negative.length > 0 ? (
          <CatalystList items={top_negative} tone="negative" />
        ) : thesisRisks.length > 0 ? (
          <BulletList items={thesisRisks} tone="negative" />
        ) : (
          <p style={mutedNote}>{t('chapter.catalysts.emptyRisks')}</p>
        )}
      </SubChapter>

      <SubChapter heading={`◆ ${t('chapter.catalysts.monitorHeading')}`}>
        {monitor.length > 0 ? (
          <CatalystList items={monitor} tone="neutral" />
        ) : (
          <p style={mutedNote}>{t('chapter.catalysts.emptyMonitor')}</p>
        )}
      </SubChapter>

      {catalysts?.overall_sentiment && catalysts.net_sentiment !== undefined && (
        <p
          style={{
            marginTop: 18,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          {t('chapter.catalysts.overallSentiment')}:{' '}
          <strong
            style={{
              color:
                catalysts.overall_sentiment === 'bullish'
                  ? 'var(--success)'
                  : catalysts.overall_sentiment === 'bearish'
                    ? 'var(--danger)'
                    : 'var(--warning)',
            }}
          >
            {catalysts.overall_sentiment.toUpperCase()}
          </strong>
          {' · '}
          {t('chapter.catalysts.netSentiment')}{' '}
          <span style={{ color: 'var(--accent-cyan)' }}>
            {catalysts.net_sentiment >= 0 ? '+' : ''}
            {catalysts.net_sentiment.toFixed(2)}
          </span>
        </p>
      )}
    </Chapter>
  )
}

function CatalystList({
  items,
  tone,
}: {
  items: CatalystEventShape[]
  tone: 'positive' | 'negative' | 'neutral'
}): React.ReactElement {
  const { t } = useI18n()
  const border =
    tone === 'positive'
      ? 'var(--success)'
      : tone === 'negative'
        ? 'var(--danger)'
        : 'var(--warning)'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((e, i) => (
        <div
          key={`${tone}-${e.category}-${i}-${e.headline.slice(0, 24)}`}
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
          {e.headline}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: 6,
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-muted)',
              marginTop: 4,
            }}
          >
            <span>
              {t('chapter.catalysts.metaCategory')} {e.category}
            </span>
            <span>·</span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              {t('chapter.catalysts.metaImpact')} <ImpactMeter score={e.impact_score} />
            </span>
            <span>·</span>
            <span>
              {t('chapter.catalysts.metaProbability')} {(e.probability * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

function BulletList({
  items,
  tone,
}: {
  items: string[]
  tone: 'positive' | 'negative' | 'neutral'
}): React.ReactElement {
  const border =
    tone === 'positive'
      ? 'var(--success)'
      : tone === 'negative'
        ? 'var(--danger)'
        : 'var(--warning)'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((t, i) => (
        <div
          key={`${tone}-${i}-${t.slice(0, 24)}`}
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
          {t}
        </div>
      ))}
    </div>
  )
}

const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'var(--bg-card-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
