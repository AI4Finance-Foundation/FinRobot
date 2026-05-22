// Chapter 02 — Company Overview. Consumes the company_overview narrative
// field (FinRobot's 8th agent parity, populated by synthesis_agent as of
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
    <Chapter id="overview" num="02" title="Company Overview" sub="Business · Segments · Geography · Moat">
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
          该 artifact 跑于 <code style={{ color: 'var(--accent-cyan)' }}>company_overview</code> 字段上线（2026-05-23）之前。
          重跑一次 <code style={{ color: 'var(--accent-cyan)' }}>research</code> pipeline 即可在本章生成 200-300 字投行口吻公司概述（业务/分部/地域/护城河）。
        </div>
      )}
    </Chapter>
  )
}
