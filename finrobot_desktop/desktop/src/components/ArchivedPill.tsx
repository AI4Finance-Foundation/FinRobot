// Marks a report version that the backend 30-day stale-archive task has
// flagged `archived=true` (timeline endpoint returns these with
// include_archived=True). Without a visible marker, archived ("retired")
// versions look identical to actively-tracked ones in the version switcher,
// right-rail timeline, History tab, and diff base picker — analysts can't tell
// "still tracking" from "system judged stale" (BUG-055).
//
// markArtifactViewed un-archives on open and the report page invalidates the
// timeline query, so this pill self-clears once the version is reopened.
//
// Style skeleton mirrors SignalBadge; dim/muted tone (not a status color) so it
// reads as "retired", not as a verdict.

import { useI18n } from '../i18n'

/** Inline JSX pill for list/timeline rows. */
export function ArchivedPill(): React.ReactElement {
  const { t } = useI18n()
  return (
    <span
      style={{
        marginLeft: 8,
        fontSize: 9.5,
        padding: '1px 5px',
        borderRadius: 3,
        background: 'transparent',
        color: 'var(--text-dim)',
        border: '1px solid var(--text-dim)',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
      }}
    >
      {t('report.timeline.archived')}
    </span>
  )
}
