// Chapter 01 — Investment Thesis. Surfaces recommendation + price target
// rationale + key_takeaways. Maps —'s investment_overview_agent +
// major_takeaways_agent output.

import type { ConfidenceTier } from '../../../utils/verdict'
import { Chapter, Narrative } from './ChapterBase'
import type { ThesisShape } from './types'
import { ConfidenceChip } from '../../../components/ConfidenceChip'
import { TargetRange } from '../../../components/TargetRange'
import { verdictLabel, verdictTone, normalizeConfidence } from '../../../utils/verdict'
import { useI18n } from '../../../i18n'

interface ChapterThesisProps {
  thesis: ThesisShape | null
  /** Confidence dial (valuation_synthesis) → tier chip + TargetRange band width.
   * Defaults to 'low' on legacy artifacts (normalizeConfidence). */
  confidence?: ConfidenceTier | string | null
  targetLow?: number | null
  targetHigh?: number | null
  anchorMethod?: string | null
  currentPrice?: number | null
  quoteCurrency?: string
}

export function ChapterThesis({
  thesis,
  confidence = null,
  targetLow = null,
  targetHigh = null,
  anchorMethod = null,
  currentPrice = null,
  quoteCurrency = 'USD',
}: ChapterThesisProps): React.ReactElement {
  const { t } = useI18n()
  if (!thesis) {
    return (
      <Chapter id="thesis">
        <Narrative>
          <p>{t('chapter.thesis.empty')}</p>
        </Narrative>
      </Chapter>
    )
  }

  const verdict = (thesis.recommendation ?? '').toUpperCase()
  const tone = verdictTone(verdict)
  const target = thesis.price_target ?? null
  const tier = normalizeConfidence(typeof confidence === 'string' ? confidence : null)
  // Point target honestly withheld — gate on target===null (verdict-independent).
  // The directional verdict still stands; only the precise number is held.
  const targetWithheld = !!verdict && target === null
  const takeaways = thesis.key_takeaways ?? []
  const narrative = thesis.narrative ?? ''

  return (
    <Chapter id="thesis">
      {(verdict || target !== null) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            flexWrap: 'wrap',
            marginBottom: 16,
            fontFamily: 'var(--font-mono)',
          }}
        >
          {verdict && (
            <span
              data-testid="thesis-verdict"
              data-verdict={verdict}
              data-confidence={tier}
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 18,
                letterSpacing: '3px',
                padding: '4px 14px',
                borderRadius: 6,
                background: tone.bg,
                color: tone.fg,
                border: `1px solid ${tone.border}`,
              }}
            >
              {verdictLabel(verdict)}
            </span>
          )}
          {/* Confidence tier — a NON-hue channel beside the directional badge. */}
          {verdict && <ConfidenceChip tier={tier} />}
          {/* TargetRange: live tick + point tick (AT the anchor) + the confidence-
              scaled band. In the withheld state the point tick is dropped — the
              rating still stands on direction, only the precise number is held. */}
          {(target !== null || targetWithheld) && (
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
          {/* Withheld with no band to draw → TargetRange renders nothing
              (resolveBand needs the point or an explicit low/high). Keep a plain
              text restatement so the verdict header never silently drops the
              "target withheld" state on those artifacts. */}
          {targetWithheld && targetLow === null && targetHigh === null && (
            <span style={{ fontSize: 18, color: 'var(--text-secondary)' }}>
              {t('chapter.thesis.targetWithheld')}
            </span>
          )}
          {thesis.price_target_basis && (
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              · {thesis.price_target_basis}
            </span>
          )}
        </div>
      )}

      {narrative && (
        <p
          style={{
            fontSize: 13.5,
            lineHeight: 1.75,
            color: 'var(--text-secondary)',
            marginBottom: 14,
          }}
        >
          {narrative}
        </p>
      )}

      {takeaways.length > 0 && (
        <>
          <h4
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 12.5,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: 'var(--text-primary)',
              margin: '18px 0 10px',
            }}
          >
            {t('chapter.thesis.keyTakeaways')}
          </h4>
          <ul
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              padding: 0,
              margin: 0,
              listStyle: 'none',
            }}
          >
            {takeaways.map((t, i) => (
              <li
                key={`takeaway-${i}-${t.slice(0, 24)}`}
                style={{
                  position: 'relative',
                  paddingLeft: 28,
                  fontSize: 13.5,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.65,
                }}
              >
                <span
                  style={{
                    position: 'absolute',
                    left: 6,
                    top: 6,
                    width: 0,
                    height: 0,
                    color: 'var(--secondary)',
                    fontSize: 9,
                    textShadow: '0 0 6px var(--secondary)',
                  }}
                >
                  ◆
                </span>
                {t}
              </li>
            ))}
          </ul>
        </>
      )}
    </Chapter>
  )
}
