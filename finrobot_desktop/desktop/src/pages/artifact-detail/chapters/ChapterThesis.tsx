// Chapter 01 — Investment Thesis. The ARGUMENT: narrative + key_takeaways.
// The rating / target / conviction / method-blend provenance live ONCE on the
// cover (ChapterCover) — repeating that whole hero block here was pure
// duplication (the same $X gauge + method-weighted-blend line rendered twice
// within one screen), so this section leads straight with the thesis prose.

import { Chapter, Narrative } from './ChapterBase'
import type { ThesisShape } from './types'
import { useI18n } from '../../../i18n'

interface ChapterThesisProps {
  thesis: ThesisShape | null
}

export function ChapterThesis({ thesis }: ChapterThesisProps): React.ReactElement {
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

  const takeaways = thesis.key_takeaways ?? []
  const narrative = thesis.narrative ?? ''

  return (
    <Chapter id="thesis">
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
