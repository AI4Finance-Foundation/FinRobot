// DebateColumn — renders one side (bull or bear) of the IC debate.
//
// Each "point" from the debate.point SSE event is shown as a card with:
//   - claim text (LLM narrative)
//   - evidence chips (sourced numbers)
//   - verified badge (green ✓ / red indicator with reason tooltip)
//
// bull side uses --success system; bear side uses --danger system.
// Both follow cosmic card spec: backdrop-blur, border-soft, hover border-glow.

import { EvidenceChip } from './EvidenceChip'
import type { DebatePoint, DebateEvidenceItem } from '../../stores/debateStore'
import { useI18n } from '../../i18n'

interface DebateColumnProps {
  side: 'bull' | 'bear'
  points: DebatePoint[]
  evidence: Record<string, DebateEvidenceItem>
  artifactId: string | null
  /** True while the debate is still running (streaming state). */
  isRunning: boolean
}

const SIDE_CONFIG = {
  bull: {
    label: 'BULL CASE',
    accentVar: 'var(--success)',
    glowVar: 'var(--success-glow)',
    softBg: 'color-mix(in srgb, var(--success) 6%, transparent)',
    borderSoft: 'color-mix(in srgb, var(--success) 20%, transparent)',
    borderGlow: 'color-mix(in srgb, var(--success) 45%, transparent)',
    dotColor: 'var(--success)',
    emptyLabelKey: 'ic.column.bull.empty',
  },
  bear: {
    label: 'BEAR CASE',
    accentVar: 'var(--danger)',
    glowVar: 'var(--danger-glow)',
    softBg: 'color-mix(in srgb, var(--danger) 6%, transparent)',
    borderSoft: 'color-mix(in srgb, var(--danger) 20%, transparent)',
    borderGlow: 'color-mix(in srgb, var(--danger) 45%, transparent)',
    dotColor: 'var(--danger)',
    emptyLabelKey: 'ic.column.bear.empty',
  },
} as const

export function DebateColumn({ side, points, evidence, artifactId, isRunning }: DebateColumnProps) {
  const { t } = useI18n()
  const cfg = SIDE_CONFIG[side]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* Column header */}
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 13,
          letterSpacing: '0.18em',
          color: cfg.accentVar,
          paddingBottom: 12,
          borderBottom: `1px solid ${cfg.borderSoft}`,
          marginBottom: 16,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: cfg.dotColor,
            boxShadow: `0 0 8px ${cfg.glowVar}`,
            flexShrink: 0,
          }}
          aria-hidden
        />
        {cfg.label}
        {points.length > 0 && (
          <span
            style={{
              marginLeft: 'auto',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-muted)',
              letterSpacing: '0.04em',
            }}
          >
            {t('ic.column.pointCount', { count: points.length })}
          </span>
        )}
      </div>

      {/* Points list */}
      {points.length === 0 ? (
        <EmptyState label={t(cfg.emptyLabelKey)} isRunning={isRunning} accentVar={cfg.accentVar} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {points.map((pt, idx) => (
            <PointCard key={idx} point={pt} evidence={evidence} artifactId={artifactId} cfg={cfg} />
          ))}
        </div>
      )}
    </div>
  )
}

interface PointCardProps {
  point: DebatePoint
  evidence: Record<string, DebateEvidenceItem>
  artifactId: string | null
  cfg: (typeof SIDE_CONFIG)[keyof typeof SIDE_CONFIG]
}

function PointCard({ point, evidence, artifactId, cfg }: PointCardProps) {
  return (
    <div
      style={{
        background: cfg.softBg,
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: `1px solid ${cfg.borderSoft}`,
        borderRadius: 'var(--radius-md)',
        padding: '14px 16px',
        transition: 'border-color 0.18s, box-shadow 0.18s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = cfg.borderGlow
        e.currentTarget.style.boxShadow = `0 4px 20px color-mix(in srgb, ${cfg.accentVar} 10%, transparent)`
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = cfg.borderSoft
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      {/* Claim text + verified badge in header row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 8,
          marginBottom: point.evidence_ids.length > 0 ? 10 : 0,
        }}
      >
        <p
          style={{
            flex: 1,
            margin: 0,
            fontFamily: 'var(--font-body)',
            fontSize: 13,
            lineHeight: 1.6,
            color: 'var(--text-secondary)',
            fontWeight: 400,
          }}
        >
          {point.claim}
        </p>
        <VerifiedBadge verified={point.verified} reason={point.reason} />
      </div>

      {/* Evidence chips */}
      {point.evidence_ids.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {point.evidence_ids.map((eid) => (
            <EvidenceChip
              key={eid}
              evidenceId={eid}
              item={evidence[eid] ?? null}
              artifactId={artifactId}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function VerifiedBadge({ verified, reason }: { verified: boolean; reason: string }) {
  const { t } = useI18n()
  return (
    <span
      title={reason || (verified ? t('ic.column.verified') : t('ic.column.unverified'))}
      aria-label={verified ? t('ic.column.verified') : t('ic.column.unverifiedReason', { reason })}
      style={{
        flexShrink: 0,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 18,
        height: 18,
        borderRadius: '50%',
        background: verified
          ? 'color-mix(in srgb, var(--success) 16%, transparent)'
          : 'color-mix(in srgb, var(--danger) 16%, transparent)',
        border: `1px solid ${
          verified
            ? 'color-mix(in srgb, var(--success) 40%, transparent)'
            : 'color-mix(in srgb, var(--danger) 40%, transparent)'
        }`,
        fontSize: 10,
        color: verified ? 'var(--success)' : 'var(--danger)',
        cursor: reason ? 'help' : 'default',
        marginTop: 2,
      }}
    >
      {verified ? '✓' : '✕'}
    </span>
  )
}

function EmptyState({
  label,
  isRunning,
  accentVar,
}: {
  label: string
  isRunning: boolean
  accentVar: string
}) {
  return (
    <div
      style={{
        padding: '24px 16px',
        textAlign: 'center',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-dim)',
        letterSpacing: '0.06em',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
      }}
    >
      {isRunning && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: accentVar,
            animation: 'pulse-dot 1.6s ease-in-out infinite',
          }}
          aria-hidden
        />
      )}
      {label}
    </div>
  )
}
