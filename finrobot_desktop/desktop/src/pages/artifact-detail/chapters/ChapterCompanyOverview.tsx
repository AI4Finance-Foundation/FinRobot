// Chapter 02 — Company Overview. Consumes the company_overview narrative
// field (the 8th synthesis slot, populated by synthesis_agent as of
// 2026-05-23). When absent, prompts the user to re-run research with the
// updated prompt — no fake placeholder copy.

import { Chapter, Narrative } from './ChapterBase'
import type { ThesisShape } from './types'
import { useI18n } from '../../../i18n'

export function ChapterCompanyOverview({
  thesis,
}: {
  thesis: ThesisShape | null
}): React.ReactElement {
  const { t } = useI18n()
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
            background: 'var(--bg-card-50)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            padding: '18px 22px',
            fontSize: 12.5,
            color: 'var(--text-muted)',
            lineHeight: 1.7,
          }}
        >
          {t('chapter.companyOverview.empty')}
        </div>
      )}
    </Chapter>
  )
}
