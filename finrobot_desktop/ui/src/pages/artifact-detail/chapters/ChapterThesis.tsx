// Chapter 01 — Investment Thesis. Surfaces recommendation + price target
// rationale + key_takeaways. Maps FinRobot's investment_overview_agent +
// major_takeaways_agent output.

import { Chapter, Narrative } from './ChapterBase'
import type { ThesisShape } from './types'

export function ChapterThesis({ thesis }: { thesis: ThesisShape | null }): React.ReactElement {
  if (!thesis) {
    return (
      <Chapter id="thesis">
        <Narrative>
          <p>该研报缺少投资论点字段，请重新生成完整研报。</p>
        </Narrative>
      </Chapter>
    )
  }

  const verdict = (thesis.recommendation ?? '').toUpperCase()
  const target = thesis.price_target ?? null
  const takeaways = thesis.key_takeaways ?? []
  const narrative = thesis.narrative ?? ''

  return (
    <Chapter id="thesis">
      {(verdict || target !== null) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 16,
            flexWrap: 'wrap',
            marginBottom: 16,
            fontFamily: 'var(--font-mono)',
          }}
        >
          {verdict && (
            <span
              data-testid="thesis-verdict"
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 18,
                letterSpacing: '3px',
                padding: '4px 14px',
                borderRadius: 6,
                background: 'var(--secondary-soft)',
                color: 'var(--secondary)',
                border: '1px solid var(--secondary)',
              }}
            >
              {verdict}
            </span>
          )}
          {target !== null && (
            <span
              style={{
                fontSize: 22,
                color: 'var(--text-primary)',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              目标 ${target.toFixed(2)}
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
            Key Takeaways
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
                key={i}
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
