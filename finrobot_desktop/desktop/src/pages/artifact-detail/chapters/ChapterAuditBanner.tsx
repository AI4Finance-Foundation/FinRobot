// Data-caveat banner — surfaces analyst-facing data-quality caveats at the top of
// the report body. CONTENT-GATED: it appears only when there is something to show
// (a flagged finding, a surfaced output-contract row, or a withheld valuation),
// never as an empty alarm box.
//
// TWO KINDS of "the number isn't clean" exist and MUST look different — conflating
// them was the JPM regression (a bank's EV rendered as a red BLOCKED alarm with a
// raw 12-digit float, so a routine sector fact read like broken software):
//
//   • DEFECT / DATA-QUALITY (cross-currency EV, TTM overlap, unverified bridge,
//     a contract withhold) → a real warning. Prominent amber/red rows, the raw
//     evidence string (it carries the diagnostic numbers the analyst must see),
//     a humanised field label instead of the snake_case key.
//
//   • STRUCTURAL / EXPECTED-BY-ECONOMICS (EV is a category error for a bank;
//     P/E is NM for a loss-maker) → NOT a defect, it's how the sector works. These
//     are demoted to a calm "Valuation Notes" line: one humanised sentence per
//     rule (grouped — Enterprise Value + EV/EBITDA collapse into ONE note), no raw
//     value (the number is audit-trail detail, surfaced inline at the figure +
//     in outputs.warnings, not dumped here). When a report has ONLY these, the
//     whole banner drops the warning treatment.
//
// The structural set is keyed by `check` (NOT severity — currency/ttm/ev_bridge
// also emit `review` but ARE genuine data-quality advisories). It mirrors the two
// "applicability" verifiers in engine/.../audit/sector_sign.py; if that grows,
// promote this to a backend `Finding` flag rather than extending the list blindly.

import { useI18n } from '../../../i18n'
import type { NumericAuditFinding, NumericAuditSeverity, NumericAuditShape } from './types'

/** Audit checks that flag an EXPECTED structural fact (a metric that doesn't apply
 * to this sector by economics), not a data defect. Mirrors sector_sign.py. */
const STRUCTURAL_CHECKS = new Set([
  'financial_sector_ev_meaningless',
  'non_positive_earnings_pe_nm',
])

/** Static label registry: raw field_key → analyst-facing metric name. Finance
 * abbreviations stay English (i18n exemption list: EV/EBITDA, P/E, …). Falls back
 * to a humanised Title-Case of the key for anything unmapped. */
const FIELD_LABELS: Record<string, string> = {
  enterprise_value: 'Enterprise Value',
  ev_ebitda: 'EV/EBITDA',
  ev_revenue: 'EV/Revenue',
  pe_ratio: 'P/E',
  market_cap: 'Market Cap',
}

function fieldLabel(key: string): string {
  // Contract clause refs (OUTPUT-CONTRACT/C1) are already meaningful — pass through.
  if (key.startsWith('OUTPUT-CONTRACT/')) return key
  const mapped = FIELD_LABELS[key]
  if (mapped) return mapped
  return key.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Accent token per report status. caveated = warning (muted amber);
 * unpublishable = danger (red). Both neutral-of-涨跌 — these are data-health
 * signals, not a directional call, so they never borrow the success/danger
 * price semantics. */
function statusAccent(status: string): string {
  // caveated (and any unknown non-publishable status) → muted warning amber.
  return status === 'unpublishable' ? 'var(--danger)' : 'var(--warning)'
}

/** Per-finding chip tone. blocked_field is the hard signal (danger); review is
 * advisory (warning); info is muted. */
function severityTone(severity: NumericAuditSeverity): string {
  if (severity === 'blocked_field') return 'var(--danger)'
  if (severity === 'review') return 'var(--warning)'
  return 'var(--text-muted)'
}

export function ChapterAuditBanner({
  audit,
  contractFindings = [],
}: {
  audit: NumericAuditShape | null
  /** Output-contract evidence parsed from outputs.warnings (`[CONTRACT/Cn] …`).
   * The contract can withhold on a CLEAN snapshot (MU $2172 — zero numeric
   * findings), so these surface the reason the numeric audit never saw. */
  contractFindings?: { clause: string; evidence: string }[]
}): React.ReactElement | null {
  const { t } = useI18n()
  const status = audit?.artifact_status ?? 'publishable'

  // Output-contract findings render as first-class rows beside the numeric-audit
  // ones — same Finding shape, distinguished by the OUTPUT-CONTRACT/ field-key.
  const allFindings: NumericAuditFinding[] = [
    ...(audit?.findings ?? []),
    ...contractFindings.map((c) => ({
      field_key: `OUTPUT-CONTRACT/${c.clause}`,
      check: 'output_contract',
      severity: 'blocked_field' as const,
      evidence: c.evidence,
    })),
  ]

  // Split DEFECTS (prominent warning rows) from STRUCTURAL notes (demoted, humanised).
  const issues = allFindings.filter((f) => !STRUCTURAL_CHECKS.has(f.check))
  const structural = allFindings.filter((f) => STRUCTURAL_CHECKS.has(f.check))

  // CONTENT-GATE, not status-enum gate. Render only when there is something
  // actionable to show — a finding, a surfaced contract row, or a withheld
  // valuation. An empty banner is pure noise: it raises alarm with zero info, and
  // any withheld target is already explained on the cover (four cards + the
  // priced-for-growth note). Gating on CONTENT (not on which status string is set)
  // is robust to legacy / unknown statuses: a pre-2026-06-15 `review_only` artifact
  // with no findings used to slip past the old `caveated`-only guard and render an
  // empty "Data Caveat" box (the TSLA/MU regression). The only status-driven
  // exception is `unpublishable` — core data is unresolvable, so the whole report
  // is suspect and the analyst must be told even with no itemised row.
  const isUnpublishable = status === 'unpublishable'
  const withheld = audit?.withhold_valuation === true
  // HARD content = a real warning. Structural notes alone are NOT hard content —
  // they get the calm treatment, never the alarm box.
  const hasHardContent = issues.length > 0 || withheld || isUnpublishable
  if (!hasHardContent && structural.length === 0) return null

  // Accent + header: alarm (amber/red) when there's a real warning; calm neutral
  // when the only content is expected structural notes.
  const accent = hasHardContent ? statusAccent(status) : 'var(--text-muted)'
  const headerLabel = isUnpublishable
    ? t('report.audit.status.unpublishable')
    : hasHardContent
      ? t('report.audit.status.caveated')
      : t('report.audit.notesTitle')

  // Group structural findings by check → one note per rule, listing the affected
  // field labels (Enterprise Value + EV/EBITDA → one line, not two near-identical ones).
  const structuralByCheck = new Map<string, string[]>()
  for (const f of structural) {
    const labels = structuralByCheck.get(f.check) ?? []
    const label = fieldLabel(f.field_key)
    if (!labels.includes(label)) labels.push(label)
    structuralByCheck.set(f.check, labels)
  }
  const structuralNotes = [...structuralByCheck.entries()].map(([check, labels]) => {
    if (check === 'financial_sector_ev_meaningless')
      return t('report.audit.note.financialSectorEv', { fields: labels.join(', ') })
    if (check === 'non_positive_earnings_pe_nm') return t('report.audit.note.lossMakerPe')
    return labels.join(', ')
  })

  return (
    <section
      id="report-audit-banner"
      data-testid="report-audit-banner"
      role={hasHardContent ? 'alert' : 'note'}
      style={{
        margin: '12px 0 24px',
        scrollMarginTop: 84,
        padding: '18px 20px',
        background: `linear-gradient(160deg, color-mix(in srgb, ${accent} 10%, transparent), color-mix(in srgb, ${accent} 3%, transparent))`,
        border: `1px solid color-mix(in srgb, ${accent} 45%, transparent)`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: 'var(--radius-md)',
        // Glow only for real warnings — a calm methodology note shouldn't pulse.
        boxShadow: hasHardContent
          ? `0 0 24px color-mix(in srgb, ${accent} 14%, transparent)`
          : 'none',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
        {hasHardContent ? <WarnIcon color={accent} /> : <NoteIcon color={accent} />}
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 15,
            letterSpacing: '1.5px',
            color: accent,
          }}
        >
          {headerLabel}
        </span>
      </div>

      {withheld && (
        <p
          style={{
            margin: '6px 0 0',
            fontFamily: 'var(--font-body)',
            fontSize: 13,
            lineHeight: 1.6,
            color: 'var(--text-secondary)',
          }}
        >
          {t('report.audit.withheldNote')}
        </p>
      )}

      {/* Unpublishable with no itemised row: the status itself is the message, so
          give the analyst a plain-language reason rather than an empty red box. */}
      {isUnpublishable && issues.length === 0 && !withheld && (
        <p
          style={{
            margin: '6px 0 0',
            fontFamily: 'var(--font-body)',
            fontSize: 13,
            lineHeight: 1.6,
            color: 'var(--text-secondary)',
          }}
        >
          {t('report.audit.unpublishableNote')}
        </p>
      )}

      {/* DEFECT rows — prominent. Humanised field label + the raw evidence string
          (it carries the diagnostic numbers the analyst needs to reconcile). */}
      {issues.length > 0 && (
        <ul
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
            margin: '14px 0 0',
            padding: 0,
            listStyle: 'none',
          }}
        >
          {issues.map((f, i) => (
            <li
              key={`${f.field_key}-${f.check}-${i}`}
              data-testid="report-audit-finding"
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 5,
                padding: '12px 14px',
                background: 'var(--bg-card-50)',
                border: '1px solid var(--border-soft)',
                borderRadius: 'var(--radius-sm)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontSize: 12.5,
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    letterSpacing: '0.02em',
                  }}
                >
                  {fieldLabel(f.field_key)}
                </span>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10.5,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    color: severityTone(f.severity),
                    background: `color-mix(in srgb, ${severityTone(f.severity)} 14%, transparent)`,
                    border: `1px solid color-mix(in srgb, ${severityTone(f.severity)} 40%, transparent)`,
                    borderRadius: 999,
                    padding: '1px 8px',
                  }}
                >
                  {t(
                    f.severity === 'blocked_field'
                      ? 'report.audit.severity.blocked'
                      : f.severity === 'review'
                        ? 'report.audit.severity.review'
                        : 'report.audit.severity.info',
                  )}
                </span>
              </div>
              <p
                style={{
                  margin: 0,
                  fontFamily: 'var(--font-body)',
                  fontSize: 12.5,
                  lineHeight: 1.6,
                  color: 'var(--text-secondary)',
                }}
              >
                {f.evidence}
              </p>
            </li>
          ))}
        </ul>
      )}

      {/* STRUCTURAL notes — demoted, humanised, one line per rule. Quiet muted text,
          no severity chip, no raw number: this is methodology transparency, not an alarm. */}
      {structuralNotes.length > 0 && (
        <ul
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 7,
            margin: hasHardContent ? '14px 0 0' : '8px 0 0',
            padding: 0,
            listStyle: 'none',
          }}
        >
          {structuralNotes.map((note, i) => (
            <li
              key={i}
              data-testid="report-audit-note"
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 9,
                fontFamily: 'var(--font-body)',
                fontSize: 12.5,
                lineHeight: 1.6,
                color: 'var(--text-muted)',
              }}
            >
              <span
                aria-hidden
                style={{
                  flexShrink: 0,
                  width: 4,
                  height: 4,
                  marginTop: 7,
                  borderRadius: 999,
                  background: 'var(--text-dim)',
                }}
              />
              <span>{note}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function WarnIcon({ color }: { color: string }): React.ReactElement {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      style={{
        flexShrink: 0,
        filter: `drop-shadow(0 0 6px color-mix(in srgb, ${color} 60%, transparent))`,
      }}
    >
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

/** Calm marker for the methodology-notes (non-warning) header: a plain info circle,
 * no drop-shadow glow — it must not read as an alarm. */
function NoteIcon({ color }: { color: string }): React.ReactElement {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      style={{ flexShrink: 0 }}
    >
      <circle cx="12" cy="12" r="9" />
      <line x1="12" y1="11" x2="12" y2="16" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  )
}
