// Inline caveat marker for a single flagged number. Sits next to a field label
// (e.g. the EV KvGrid cell) when the numeric-audit gate flagged that field_key.
// Hovering surfaces the finding's evidence so the analyst sees WHY the number is
// suspect right where it's rendered — complementing the top audit banner.

import type { NumericAuditFinding, NumericAuditShape } from './types'

/** Collect the findings whose field_key is in `fieldKeys`. Empty when the audit
 * is clean / absent or none of the requested fields were flagged. */
export function findingsFor(
  audit: NumericAuditShape | null | undefined,
  fieldKeys: readonly string[],
): NumericAuditFinding[] {
  if (!audit?.findings?.length) return []
  const wanted = new Set(fieldKeys)
  return audit.findings.filter((f) => wanted.has(f.field_key))
}

export function FieldCaveat({
  findings,
}: {
  findings: NumericAuditFinding[]
}): React.ReactElement | null {
  if (findings.length === 0) return null
  // Worst severity drives the colour: a blocked_field is a hard red flag,
  // review is advisory amber.
  const blocked = findings.some((f) => f.severity === 'blocked_field')
  const color = blocked ? 'var(--danger)' : 'var(--warning)'
  const title = findings.map((f) => f.evidence).join('\n\n')

  return (
    <span
      data-testid="field-caveat"
      title={title}
      aria-label={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        marginLeft: 5,
        cursor: 'help',
        verticalAlign: 'middle',
      }}
    >
      <svg
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke={color}
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
        style={{ filter: `drop-shadow(0 0 4px color-mix(in srgb, ${color} 60%, transparent))` }}
      >
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    </span>
  )
}
