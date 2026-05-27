// Chapter 02 — Company Overview. Consumes the company_overview narrative
// field (the 8th synthesis slot, populated by synthesis_agent as of
// 2026-05-23). When absent, prompts the user to re-run research with the
// updated prompt — no fake placeholder copy.

import { Chapter, Narrative } from './ChapterBase'
import type { ThesisShape } from './types'

export function ChapterCompanyOverview({
  thesis,
}: {
  thesis: ThesisShape | null
}): React.ReactElement {
  const overview = thesis?.company_overview ?? null

  return (
    <Chapter id="overview">
      {overview ? (
        <Narrative>
          <p>{overview}</p>
        </Narrative>
      ) : (
        <div
          style={{
            background: 'rgba(15, 15, 34, 0.5)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            padding: '18px 22px',
            fontSize: 12.5,
            color: 'var(--text-muted)',
            lineHeight: 1.7,
          }}
        >
          该研报未包含公司概览字段，请重新生成完整研报即可在本章看到投行口吻的业务、分部、地区与护城河描述。
        </div>
      )}
    </Chapter>
  )
}
