// Chapter 05 — Recent News & Events. Surfaces the LLM-synthesised
// news_summary narrative for the 30-day window when the artifact was
// produced. Frozen — analysts compare snapshots across artifact versions
// rather than expecting this to live-update.

import { Chapter, Narrative } from './ChapterBase'
import type { ThesisShape } from './types'
import { useI18n } from '../../../i18n'

export function ChapterNews({ thesis }: { thesis: ThesisShape | null }): React.ReactElement {
  const { t } = useI18n()
  const summary = thesis?.news_summary ?? null

  return (
    <Chapter id="news">
      {summary ? (
        <Narrative>
          <p>{summary}</p>
        </Narrative>
      ) : (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-muted)',
            padding: '14px 18px',
            background: 'var(--bg-card-50)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            lineHeight: 1.7,
          }}
        >
          {t('chapter.news.empty')}
        </p>
      )}
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
