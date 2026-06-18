// Data-caveat banner — surfaces analyst-facing data-quality caveats at the top of
// the report body. CONTENT-GATED: it appears only when there is something to show
// (a flagged finding, a surfaced output-contract row, or a withheld valuation),
// never as an empty alarm box. The label is analyst-facing ("Data Caveats" /
// "Core Data Unresolved"), not the internal gate status — the analyst reads the
// caveats, not our QA machinery.
//
// It lists every finding by its flagged field_key + the evidence string (the
// actual numbers the backend computed). When a specific field's number was
// withheld, the copy says so for that field — the directional rating still stands
// (artifact/builders.py preserves it). Only `unpublishable` (core data
// unresolvable) goes red and always surfaces, since the whole report is suspect.

import { useI18n } from '../../../i18n'
import type { NumericAuditFinding, NumericAuditSeverity, NumericAuditShape } from './types'

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
  const findings: NumericAuditFinding[] = [
    ...(audit?.findings ?? []),
    ...contractFindings.map((c) => ({
      field_key: `OUTPUT-CONTRACT/${c.clause}`,
      check: 'output_contract',
      severity: 'blocked_field' as const,
      evidence: c.evidence,
    })),
  ]

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
  const hasContent = findings.length > 0 || audit?.withhold_valuation === true
  if (!isUnpublishable && !hasContent) return null
  const accent = statusAccent(status)

  const statusLabel =
    status === 'unpublishable'
      ? t('report.audit.status.unpublishable')
      : t('report.audit.status.caveated')

  return (
    <section
      id="report-audit-banner"
      data-testid="report-audit-banner"
      role="alert"
      style={{
        margin: '12px 0 24px',
        scrollMarginTop: 84,
        padding: '18px 20px',
        background: `linear-gradient(160deg, color-mix(in srgb, ${accent} 10%, transparent), color-mix(in srgb, ${accent} 3%, transparent))`,
        border: `1px solid color-mix(in srgb, ${accent} 45%, transparent)`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: 'var(--radius-md)',
        boxShadow: `0 0 24px color-mix(in srgb, ${accent} 14%, transparent)`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
        <WarnIcon color={accent} />
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 15,
            letterSpacing: '1.5px',
            color: accent,
          }}
        >
          {statusLabel}
        </span>
      </div>

      {audit?.withhold_valuation && (
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
      {isUnpublishable && findings.length === 0 && !audit?.withhold_valuation && (
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

      {findings.length > 0 && (
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
          {findings.map((f, i) => (
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
                <code
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11.5,
                    color: 'var(--text-primary)',
                    background: 'var(--bg-elevated)',
                    border: '1px solid var(--border-soft)',
                    borderRadius: 4,
                    padding: '1px 7px',
                  }}
                >
                  {f.field_key}
                </code>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 9.5,
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
