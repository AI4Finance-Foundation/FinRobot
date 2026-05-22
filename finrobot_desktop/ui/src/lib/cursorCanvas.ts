// Custom cursor trail — Bezier-spring 12-line "comet" rig.
//
// Cosmic spec §5.3 calls this "桌面 App 的灵魂". Implementation is a port
// of the v1 demo's <script> block, refactored into a controllable handle
// so the React layer can stop/restart it when the Settings toggle flips.
//
// Performance: 12 Bezier lines + 1 dot @ requestAnimationFrame. Each line
// is a spring with monotonically increasing `tau` (relaxation constant)
// so trailing strokes feel heavier than leading ones. HSL lightness gets
// a slow phase walk so the trail hue-shifts subtly without a rainbow
// vibe.

export interface CursorTrailHandle {
  /** Stops the rAF loop and removes the canvas + cursor:none style. */
  stop: () => void
}

interface SpringPoint {
  x: number
  y: number
  tau: number
}

/**
 * Mount the trail on document.body. Idempotent: calling twice is safe but
 * only the first call's handle is live; the second is a no-op returning a
 * handle whose stop() is also a no-op.
 *
 * Returns a handle whose `stop()` removes the canvas, the cursor-trail-on
 * body class, and cancels the rAF loop. Re-mounting after stop() is fine.
 */
export function mountCursorTrail(): CursorTrailHandle {
  if (typeof window === 'undefined') return { stop: () => {} }
  // Guard against double mount — Settings page hot-reload can fire mount twice.
  if (document.body.dataset.cursorTrailMounted === '1') return { stop: () => {} }
  document.body.dataset.cursorTrailMounted = '1'

  const canvas = document.createElement('canvas')
  canvas.setAttribute('aria-hidden', 'true')
  canvas.dataset.cosmicCursor = '1'
  canvas.style.cssText =
    'position:fixed;inset:0;pointer-events:none;z-index:9999;'
  document.body.appendChild(canvas)
  document.body.classList.add('cursor-trail-on')

  const dpr = window.devicePixelRatio || 1
  const ctx = canvas.getContext('2d')
  let width = window.innerWidth
  let height = window.innerHeight

  function resize(): void {
    width = window.innerWidth
    height = window.innerHeight
    canvas.width = width * dpr
    canvas.height = height * dpr
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`
    if (ctx) ctx.scale(dpr, dpr)
  }
  resize()

  // Springs — tau ladder makes trailing segments lag further behind.
  const N = 12
  const springs: SpringPoint[] = []
  for (let i = 0; i < N; i += 1) {
    springs.push({ x: width / 2, y: height / 2, tau: 0.18 + i * 0.022 })
  }

  let target = { x: width / 2, y: height / 2 }
  let head = { x: width / 2, y: height / 2 }
  let alive = true
  let rafId = 0
  let phase = 0  // slow hue walk

  function onMove(e: MouseEvent): void {
    target = { x: e.clientX, y: e.clientY }
  }

  function onResize(): void {
    resize()
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('resize', onResize)

  function frame(): void {
    if (!alive || !ctx) return
    phase += 0.01

    // Lead point — light spring follow.
    head.x += (target.x - head.x) * 0.32
    head.y += (target.y - head.y) * 0.32

    // Cascade springs.
    let prev = head
    for (const s of springs) {
      s.x += (prev.x - s.x) * s.tau
      s.y += (prev.y - s.y) * s.tau
      prev = s
    }

    ctx.clearRect(0, 0, width, height)

    // Trail: piecewise quadratic curves.
    ctx.lineCap = 'round'
    for (let i = 0; i < springs.length - 1; i += 1) {
      const a = i === 0 ? head : springs[i - 1]
      const b = springs[i]
      const c = springs[i + 1]
      const xc = (b.x + c.x) / 2
      const yc = (b.y + c.y) / 2
      const t = i / springs.length
      const alpha = 0.85 * (1 - t)
      const light = 60 + 14 * Math.sin(phase + i * 0.6)
      ctx.strokeStyle = `hsla(225, 95%, ${light}%, ${alpha})`
      ctx.lineWidth = 6 - i * 0.4
      ctx.beginPath()
      ctx.moveTo(a.x, a.y)
      ctx.quadraticCurveTo(b.x, b.y, xc, yc)
      ctx.stroke()
    }

    // Lead dot — bright neon point.
    const grd = ctx.createRadialGradient(head.x, head.y, 0, head.x, head.y, 18)
    grd.addColorStop(0, 'rgba(59,130,246,0.95)')
    grd.addColorStop(0.4, 'rgba(34,211,238,0.45)')
    grd.addColorStop(1, 'rgba(59,130,246,0)')
    ctx.fillStyle = grd
    ctx.beginPath()
    ctx.arc(head.x, head.y, 18, 0, Math.PI * 2)
    ctx.fill()

    ctx.fillStyle = '#fff'
    ctx.beginPath()
    ctx.arc(head.x, head.y, 3, 0, Math.PI * 2)
    ctx.fill()

    rafId = requestAnimationFrame(frame)
  }
  rafId = requestAnimationFrame(frame)

  return {
    stop: () => {
      alive = false
      cancelAnimationFrame(rafId)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('resize', onResize)
      canvas.remove()
      document.body.classList.remove('cursor-trail-on')
      delete document.body.dataset.cursorTrailMounted
    },
  }
}
