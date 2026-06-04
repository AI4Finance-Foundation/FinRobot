// VerdictCard — sticky top card showing the IC committee verdict.
//
// call badge: BUY green / SELL red / HOLD amber / REVIEW gray
// conviction: mono tabular-nums, null → "—"
// swing_factor + change_my_mind: LLM narrative (judgment, not numbers — no SourcedNumber)
//
// Three states:
//   1. idle (no debate started) — hidden; caller handles the start button
//   2. running + no verdict yet — skeleton/"辩论进行中…" state
//   3. has verdict (running or completed) — full render
//
// reliable=false → orange warning banner above the call badge (data quality caveat).

import type { DebateVerdict, DebateStatus } from '../../stores/debateStore'
import { useI18n } from '../../i18n'

interface VerdictCardProps {
  verdict: DebateVerdict | null
  status: DebateStatus
  reliable: boolean
  current_price: number | null
  // UX-004: when the debate is finished the verdict is the analyst's takeaway —
  // give an immediate way back to the originating report right at the card.
  // Optional so the card stays self-contained when no exit is wired.
  onBackToReport?: () => void
}

// ── Call badge configs ────────────────────────────────────────────────────────

type CallKey = 'BUY' | 'HOLD' | 'SELL' | 'REVIEW'

const CALL_CONFIG: Record<CallKey, { bg: string; glow: string; border: string; text: string }> = {
  BUY: {
    bg: 'color-mix(in srgb, var(--success) 16%, transparent)',
    glow: '0 0 32px var(--success-glow)',
    border: 'color-mix(in srgb, var(--success) 45%, transparent)',
    text: 'var(--success)',
  },
  SELL: {
    bg: 'color-mix(in srgb, var(--danger) 16%, transparent)',
    glow: '0 0 32px var(--danger-glow)',
    border: 'color-mix(in srgb, var(--danger) 45%, transparent)',
    text: 'var(--danger)',
  },
  HOLD: {
    bg: 'color-mix(in srgb, var(--warning) 16%, transparent)',
    glow: '0 0 24px color-mix(in srgb, var(--warning) 50%, transparent)',
    border: 'color-mix(in srgb, var(--warning) 45%, transparent)',
    text: 'var(--warning)',
  },
  REVIEW: {
    bg: 'color-mix(in srgb, var(--text-muted) 12%, transparent)',
    glow: 'none',
    border: 'var(--border-soft)',
    text: 'var(--text-muted)',
  },
}

// ── Component ─────────────────────────────────────────────────────────────────

export function VerdictCard({
  verdict,
  status,
  reliable,
  current_price,
  onBackToReport,
}: VerdictCardProps) {
  const { t } = useI18n()
  const isRunning = status === 'running'
  const isCompleted = status === 'completed'
  const hasVerdict = verdict !== null

  // Don't render card at all in idle state — caller shows start button instead.
  if (status === 'idle') return null

  const callCfg = hasVerdict ? CALL_CONFIG[verdict.call] : null

  return (
    <div
      data-testid="verdict-card"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 20,
        background: 'color-mix(in srgb, var(--bg-card) 90%, transparent)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: `1px solid ${hasVerdict ? (callCfg?.border ?? 'var(--border-soft)') : 'var(--border-soft)'}`,
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
        marginBottom: 24,
        transition: 'border-color 0.25s, box-shadow 0.25s',
        boxShadow: hasVerdict && callCfg ? callCfg.glow : undefined,
      }}
    >
      {/* Data reliability warning banner */}
      {!reliable && (
        <div
          role="alert"
          style={{
            padding: '8px 20px',
            background: 'color-mix(in srgb, var(--warning) 12%, transparent)',
            borderBottom: '1px solid color-mix(in srgb, var(--warning) 32%, transparent)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--warning)',
            letterSpacing: '0.06em',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span aria-hidden>⚠</span>
          {t('ic.verdict.reliabilityWarning')}
        </div>
      )}

      <div style={{ padding: '20px 24px' }}>
        {/* UX-004: a quick exit back to the report, anchored at the verdict the
            analyst just read. Only once the debate has settled. */}
        {isCompleted && onBackToReport && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <button
              type="button"
              onClick={onBackToReport}
              style={{
                background: 'transparent',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                letterSpacing: '0.06em',
                color: 'var(--primary)',
                transition: 'opacity 0.18s',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.7')}
              onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
            >
              ← {t('ic.action.backToReport')}
            </button>
          </div>
        )}
        {isRunning && !hasVerdict ? (
          // Streaming skeleton: debate in progress, verdict not yet arrived
          <RunningState />
        ) : hasVerdict && verdict ? (
          // Full verdict render
          <FullVerdict
            verdict={verdict}
            callCfg={callCfg ?? CALL_CONFIG.REVIEW}
            current_price={current_price}
            t={t}
          />
        ) : (
          // Failed state or edge case — show minimal error hint
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              letterSpacing: '0.06em',
            }}
          >
            {t('ic.verdict.unavailable')}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function RunningState() {
  const { t } = useI18n()
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        color: 'var(--text-muted)',
        letterSpacing: '0.08em',
      }}
    >
      <span
        style={{
          display: 'inline-block',
          width: 10,
          height: 10,
          borderRadius: '50%',
          background: 'var(--primary)',
          boxShadow: 'var(--glow-blue)',
          animation: 'pulse-dot 1.6s ease-in-out infinite',
        }}
        aria-hidden
      />
      {t('ic.verdict.running')}
      <span
        style={{
          marginLeft: 'auto',
          fontSize: 10,
          color: 'var(--text-dim)',
        }}
      >
        {t('ic.verdict.runningHint')}
      </span>
    </div>
  )
}

interface FullVerdictProps {
  verdict: DebateVerdict
  callCfg: (typeof CALL_CONFIG)[CallKey]
  current_price: number | null
  t: (key: string, params?: Record<string, string | number>) => string
}

function FullVerdict({ verdict, callCfg, current_price, t }: FullVerdictProps) {
  // conviction is a 0–1 float (Verdict model: ge=0, le=1); the "/100" suffix means
  // we render it as a 0–100 score, so scale up. Without ×100 every value rounded
  // to 0 or 1 (0.75 → "1/100").
  const convictionDisplay =
    verdict.conviction !== null ? `${(verdict.conviction * 100).toFixed(0)}` : '—'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Top row: call badge + conviction + price */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
        {/* Call badge */}
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 26,
            letterSpacing: '0.18em',
            color: callCfg.text,
            background: callCfg.bg,
            border: `1px solid ${callCfg.border}`,
            borderRadius: 'var(--radius-md)',
            padding: '6px 18px',
            boxShadow: callCfg.glow,
            lineHeight: 1,
          }}
          aria-label={t('ic.verdict.callAria', { call: verdict.call })}
        >
          {verdict.call}
        </span>

        {/* Conviction score */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-muted)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
            }}
          >
            Conviction
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 20,
              fontVariantNumeric: 'tabular-nums',
              color: callCfg.text,
              lineHeight: 1,
            }}
            aria-label={t('ic.verdict.convictionAria', { value: convictionDisplay })}
          >
            {convictionDisplay}
            {verdict.conviction !== null && (
              <span
                style={{
                  fontSize: 12,
                  color: 'var(--text-muted)',
                  marginLeft: 2,
                }}
              >
                /100
              </span>
            )}
          </span>
        </div>

        {/* Current price at debate time */}
        {current_price !== null && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-muted)',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}
            >
              Price@Debate
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 16,
                fontVariantNumeric: 'tabular-nums',
                color: 'var(--accent-cyan)',
                lineHeight: 1,
              }}
            >
              ${current_price.toFixed(2)}
            </span>
          </div>
        )}
      </div>

      {/* Swing factor */}
      {verdict.swing_factor && (
        <div
          style={{
            padding: '12px 16px',
            background: 'color-mix(in srgb, var(--primary) 6%, transparent)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            borderLeft: `3px solid var(--primary)`,
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-muted)',
              letterSpacing: '0.10em',
              marginBottom: 6,
              textTransform: 'uppercase',
            }}
          >
            Swing Factor
          </div>
          <p
            style={{
              margin: 0,
              fontFamily: 'var(--font-body)',
              fontSize: 13,
              lineHeight: 1.65,
              color: 'var(--text-secondary)',
            }}
          >
            {verdict.swing_factor}
          </p>
        </div>
      )}

      {/* Change my mind */}
      {verdict.change_my_mind && (
        <div
          style={{
            padding: '12px 16px',
            background: 'color-mix(in srgb, var(--secondary) 5%, transparent)',
            border: '1px solid var(--border-faint)',
            borderRadius: 'var(--radius-sm)',
            borderLeft: `3px solid var(--secondary)`,
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-muted)',
              letterSpacing: '0.10em',
              marginBottom: 6,
              textTransform: 'uppercase',
            }}
          >
            Change My Mind
            <span
              style={{
                marginLeft: 8,
                fontFamily: 'var(--font-body)',
                textTransform: 'none',
                letterSpacing: 0,
              }}
              title={t('ic.verdict.changeMyMindTitle')}
            >
              {t('ic.verdict.changeMyMindLabel')}
            </span>
          </div>
          <p
            style={{
              margin: 0,
              fontFamily: 'var(--font-body)',
              fontSize: 13,
              lineHeight: 1.65,
              color: 'var(--text-secondary)',
            }}
          >
            {verdict.change_my_mind}
          </p>
        </div>
      )}
    </div>
  )
}
