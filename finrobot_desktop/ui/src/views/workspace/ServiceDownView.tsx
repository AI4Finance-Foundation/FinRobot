// 502 / 503 / non-HTTP error gate view. Exponential backoff auto-retry
// (30s → 60s → 120s → 240s → 300s capped). Manual retry resets attempts.
//
// Single mount-once useEffect owns the timer lifecycle. The timer callback
// re-registers itself synchronously (not via a useEffect dependency re-run),
// so vi.advanceTimersByTime(N) in tests fires the full chain without needing
// React to flush effects between ticks. Mutable state lives in refs; React
// state drives rendering only. onRetry fires atomically inside the callback
// when countdown hits 0, then backoff advances — no double-fire.

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import { WorkspaceBreadcrumb } from './WorkspaceBreadcrumb'

const BACKOFF_INITIAL_SECONDS = 30
const BACKOFF_MAX_SECONDS = 300 // 5min cap

function backoffDelay(attemptCount: number): number {
  return Math.min(BACKOFF_INITIAL_SECONDS * 2 ** attemptCount, BACKOFF_MAX_SECONDS)
}

interface Props {
  ticker: string
  onRetry: () => void
}

export function ServiceDownView({ ticker, onRetry }: Props): React.ReactElement {
  const { t } = useI18n()

  // Render state (drives visible countdown label and attempt number)
  const [attempts, setAttempts] = useState(0)
  const [countdown, setCountdown] = useState(BACKOFF_INITIAL_SECONDS)

  // Mutable refs — updated synchronously inside the timer callback so the next
  // re-registration always sees the latest values without needing a re-render.
  const attemptsRef = useRef(0)
  const countdownRef = useRef(BACKOFF_INITIAL_SECONDS)
  const onRetryRef = useRef(onRetry)
  const timerId = useRef<ReturnType<typeof setTimeout> | null>(null)
  // tickRef holds the stable tick closure so handleManualRetry can restart it
  const tickRef = useRef<() => void>(() => {})

  // Keep onRetryRef current when the prop changes (e.g. parent re-renders)
  useEffect(() => {
    onRetryRef.current = onRetry
  }, [onRetry])

  // Single mount-once effect: builds the tick closure and starts the loop.
  // tick re-registers itself synchronously at the end of each invocation so
  // vi.advanceTimersByTime(N) chains all N/1000 callbacks in one call.
  useEffect(() => {
    const tick = () => {
      countdownRef.current -= 1
      if (countdownRef.current <= 0) {
        // Countdown expired: fire retry and advance backoff atomically.
        onRetryRef.current()
        attemptsRef.current += 1
        countdownRef.current = backoffDelay(attemptsRef.current)
        setAttempts(attemptsRef.current)
        setCountdown(countdownRef.current)
      } else {
        setCountdown(countdownRef.current)
      }
      // Re-register synchronously (before React flushes effects)
      timerId.current = setTimeout(tick, 1000)
    }
    tickRef.current = tick

    timerId.current = setTimeout(tick, 1000)
    return () => {
      if (timerId.current !== null) clearTimeout(timerId.current)
    }
  }, []) // mount-once — refs hold mutable latest values

  const handleManualRetry = useCallback(() => {
    // Clear running timer to avoid race with the automatic tick
    if (timerId.current !== null) clearTimeout(timerId.current)
    // Fire callback and reset state atomically
    onRetryRef.current()
    attemptsRef.current = 0
    countdownRef.current = BACKOFF_INITIAL_SECONDS
    setAttempts(0)
    setCountdown(BACKOFF_INITIAL_SECONDS)
    // Restart the tick loop using the stable closure from mount
    timerId.current = setTimeout(tickRef.current, 1000)
  }, [])

  return (
    <div
      data-testid="service-down"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '48px 32px',
      }}
    >
      <div style={{ width: '100%', maxWidth: 1280 }}>
        <WorkspaceBreadcrumb ticker={ticker} />
      </div>

      <div
        style={{
          marginTop: 80,
          textAlign: 'center',
          maxWidth: 520,
        }}
      >
        {/* Title — Audiowide 48px, letter-spacing 4px per §3 */}
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 48,
            letterSpacing: '4px',
            color: 'var(--text-primary)',
            marginBottom: 16,
          }}
        >
          {t('service.down.title')}
        </div>

        {/* Description — Inter 14px body copy per §3 */}
        <p
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 14,
            color: 'var(--text-secondary)',
            marginBottom: 28,
          }}
        >
          {t('service.down.description', { ticker })}
        </p>

        {/* Countdown — JetBrains Mono 13px, --accent-amber (defined in App.css) */}
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            color: 'var(--accent-amber)',
            marginBottom: 22,
            letterSpacing: '0.04em',
          }}
        >
          {t('service.down.countdown', { n: countdown, attempt: attempts + 1 })}
        </div>

        {/* CTA — .btn-shimmer (§6.3 shimmer button), Audiowide 13px + letter-spacing 2px */}
        <button
          type="button"
          onClick={handleManualRetry}
          className="btn-shimmer"
          style={{
            padding: '10px 28px',
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            letterSpacing: '2px',
            cursor: 'pointer',
            borderRadius: 'var(--radius-md)',
            border: 'none',
            color: 'var(--text-primary)',
          }}
        >
          {t('service.down.retryNow')}
        </button>
      </div>
    </div>
  )
}
