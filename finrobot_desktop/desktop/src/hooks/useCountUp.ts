import { useEffect, useRef, useState } from 'react'

/**
 * Animates a number from its previous value to the new target.
 * Uses easeOutCubic for a satisfying deceleration curve.
 *
 * @param target  - The final number to animate toward
 * @param duration - Animation duration in ms (default 700)
 * @param decimals - Decimal places to preserve during animation (default 2)
 */
export function useCountUp(target: number, duration = 700, decimals = 2): number {
  const [display, setDisplay] = useState(0)
  const prevTarget = useRef(0)
  const rafId = useRef(0)

  useEffect(() => {
    const from = prevTarget.current
    prevTarget.current = target

    // Skip if unchanged
    if (from === target) {
      setDisplay(target)
      return
    }

    const startTime = performance.now()
    const multiplier = Math.pow(10, decimals)

    function tick(now: number) {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      // easeOutCubic: fast start, gentle stop
      const eased = 1 - Math.pow(1 - progress, 3)
      const current = from + (target - from) * eased
      setDisplay(Math.round(current * multiplier) / multiplier)

      if (progress < 1) {
        rafId.current = requestAnimationFrame(tick)
      }
    }

    rafId.current = requestAnimationFrame(tick)

    return () => cancelAnimationFrame(rafId.current)
  }, [target, duration, decimals])

  return display
}
