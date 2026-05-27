// Chapter 05 — Recent News & Events. Surfaces the LLM-synthesised
// news_summary narrative for the 30-day window when the artifact was
// produced. Frozen — analysts compare snapshots across artifact versions
// rather than expecting this to live-update.

import { Chapter, Narrative } from './ChapterBase'
import type { ThesisShape } from './types'

export function ChapterNews({ thesis }: { thesis: ThesisShape | null }): React.ReactElement {
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
            background: 'rgba(15, 15, 34, 0.5)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            lineHeight: 1.7,
          }}
        >
          该研报未生成新闻情绪段 — 重新生成研报即在此章产出近 30 天关键事件的整体情绪与论点支撑 /
          挑战分析。
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
        Snapshot frozen at artifact creation · live news feed available on the workspace dashboard.
      </p>
    </Chapter>
  )
}
