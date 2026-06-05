// SplineHero — 3D AI Analyst figure for the ticker workspace hero.
//
// Loads @splinetool/viewer via its UMD bundle (the React wrapper hauls in
// extra dependencies we don't need for one scene). Failure paths:
//   - script fails to load → render the fake-robot double-ring fallback
//   - scene fails to load   → ditto via timeout (8s)
//
// Sizing: caller sets the bounding box (typically 40% width inside the
// hero grid); SplineHero fills it.
//
// CPU/heat-saving (2026-05-22):
//   - the robot is always on (no user toggle); heat is bounded purely by the
//     automatic guards below — when they fail/idle we render the static
//     FakeRobotRings fallback (CSS-only, almost free)
//   - unmount the viewer when document.hidden / window blurred so the
//     WebGL context stops burning GPU in the background
//   - IntersectionObserver: don't even mount the viewer if the container
//     is currently off-screen (landing backdrop variant scrolls off as
//     the user inspects the tables below — no point rendering 3D under
//     the fold)

import { useEffect, useRef, useState } from 'react'

const SCRIPT_SRC = 'https://unpkg.com/@splinetool/viewer@1.9.54/build/spline-viewer.js'
const SCENE_SRC = 'https://prod.spline.design/kZDDjO5HuC9GJUM2/scene.splinecode'
const LOAD_TIMEOUT_MS = 8000

interface Props {
  /** Per spec §5.4 mode + landing addition:
   *  - 'hero'     = 480px tall main piece (ticker workspace right column)
   *  - 'floating' = 120px ball (RHS status nub)
   *  - 'backdrop' = full container, lower opacity, no badge / no chrome
   *                 (landing page atmosphere — never blocks the title) */
  variant?: 'hero' | 'floating' | 'backdrop'
  /** Show the cyan "AI Analyst" chip in the corner. Defaults true on hero, false elsewhere. */
  showStatusChip?: boolean
}

declare module 'react' {
  // React 19: JSX intrinsics live under React.JSX rather than the global
  // JSX namespace. Augment that interface so `<spline-viewer />` typechecks.
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      'spline-viewer': React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement> & {
          url?: string
          'events-target'?: string
        },
        HTMLElement
      >
    }
  }
}

export function SplineHero({ variant = 'hero', showStatusChip }: Props): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [visible, setVisible] = useState(true)
  const [hasLayout, setHasLayout] = useState(false)
  const [pageActive, setPageActive] = useState(
    typeof document === 'undefined' ? true : !document.hidden,
  )
  const showChip = showStatusChip ?? variant === 'hero'
  // The actual render condition: tab visible + scrolled into view. When either
  // flips false we render the static FakeRobotRings fallback (or nothing for
  // the backdrop variant) instead of the WebGL viewer — that's the heat saver.
  // There is no user opt-out: the robot is always on by design.
  const allowed = pageActive && visible && hasLayout

  // Unmount the WebGL viewer only when the tab is actually HIDDEN
  // (visibilitychange) — that's the real heat-saver. We deliberately do NOT
  // unmount on mere window blur: every blur→focus cycle reloaded the scene and
  // replayed its zoom-in intro, so the robot "slowly zoomed" each time the user
  // clicked away and back. A still-visible-but-unfocused window keeps the
  // robot mounted (and CSS animations are already paused via body.app-bg).
  useEffect(() => {
    function onVis() {
      setPageActive(!document.hidden)
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  // IntersectionObserver — only mount the viewer when the container is in
  // the viewport. Landing-page backdrop scrolls off when the user inspects
  // the studied-tickers table; no need to keep rendering 3D below the fold.
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return
    const el = containerRef.current
    if (!el) return
    const io = new IntersectionObserver(
      ([entry]) => setVisible(entry?.isIntersecting ?? true),
      { rootMargin: '120px' }, // start rendering slightly before it enters
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  // Spline's WebGL viewer allocates framebuffers at mount. In WebKit/Tauri a
  // just-created custom element can see a zero-sized canvas for one frame, which
  // produces INVALID_FRAMEBUFFER_OPERATION noise. Mount it only after layout
  // reports positive dimensions.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const mark = () => {
      const rect = el.getBoundingClientRect()
      setHasLayout(rect.width > 0 && rect.height > 0)
    }

    mark()
    if (typeof ResizeObserver === 'undefined') {
      const raf = window.requestAnimationFrame(mark)
      return () => window.cancelAnimationFrame(raf)
    }

    const ro = new ResizeObserver(mark)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (!allowed) return
    let cancelled = false

    // Inject the viewer module once. Re-renders attach to the existing tag.
    const existing = document.querySelector<HTMLScriptElement>('script[data-spline-viewer="1"]')

    let timeoutId: ReturnType<typeof setTimeout> | null = null
    function armTimeout() {
      timeoutId = setTimeout(() => {
        if (cancelled) return
        // If still loading after 8s, fall back to the double ring.
        setStatus((cur) => (cur === 'loading' ? 'failed' : cur))
      }, LOAD_TIMEOUT_MS)
    }

    function onReady() {
      if (cancelled) return
      if (timeoutId) clearTimeout(timeoutId)
      setStatus('ready')
    }

    function onError() {
      if (cancelled) return
      if (timeoutId) clearTimeout(timeoutId)
      setStatus('failed')
    }

    if (!existing) {
      const s = document.createElement('script')
      s.type = 'module'
      s.src = SCRIPT_SRC
      s.dataset.splineViewer = '1'
      s.onload = onReady
      s.onerror = onError
      document.head.appendChild(s)
      armTimeout()
    } else {
      // Already injected — viewer custom element should already be defined.
      onReady()
    }

    return () => {
      cancelled = true
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [allowed])

  // "Built with Spline" branding lives inside spline-viewer's shadow DOM
  // (the free Spline tier renders it on every scene). Inject a style tag
  // into the shadow root once the viewer is ready to nuke it. Retries for
  // 5 seconds because the shadow DOM finishes attaching after the script
  // load event in some browsers.
  useEffect(() => {
    if (status !== 'ready') return
    let tries = 0
    const handle = setInterval(() => {
      tries += 1
      const viewers = containerRef.current?.querySelectorAll('spline-viewer')
      if (!viewers || viewers.length === 0) {
        if (tries > 20) clearInterval(handle)
        return
      }
      let hit = false
      viewers.forEach((v) => {
        const root = (v as HTMLElement & { shadowRoot?: ShadowRoot | null }).shadowRoot
        if (!root) return
        if (root.querySelector('[data-cosmic-killed-logo]')) {
          hit = true
          return
        }
        const style = document.createElement('style')
        style.dataset.cosmicKilledLogo = '1'
        style.textContent = `
          #logo, .logo, a[href*="spline.design"], [class*="logo" i], [id*="logo" i] {
            display: none !important;
            opacity: 0 !important;
            pointer-events: none !important;
          }
        `
        root.appendChild(style)
        hit = true
      })
      if (hit || tries > 20) clearInterval(handle)
    }, 250)
    return () => clearInterval(handle)
  }, [status])

  const isHero = variant === 'hero'
  const isBackdrop = variant === 'backdrop'

  return (
    <div
      ref={containerRef}
      aria-hidden={isBackdrop}
      style={{
        position: 'relative',
        width: '100%',
        height: isHero || isBackdrop ? '100%' : 120,
        minHeight: isHero ? 380 : isBackdrop ? 320 : 120,
        borderRadius: isBackdrop ? 0 : 'var(--radius-xl)',
        overflow: 'hidden',
        // Backdrop variant should melt into the surrounding starfield, so
        // skip the lens-flare gradient that frames the hero piece.
        background: isBackdrop
          ? 'transparent'
          : 'radial-gradient(ellipse at center, rgba(59,130,246,0.12) 0%, transparent 70%)',
        // Cosmetic mask covering the lower-right corner where the Spline
        // branding sits before our shadow-DOM CSS injection lands.
        pointerEvents: isBackdrop ? 'none' : undefined,
      }}
    >
      {allowed && status !== 'failed' && (
        <spline-viewer
          url={SCENE_SRC}
          events-target="global"
          style={
            {
              width: '100%',
              height: '100%',
              opacity: status === 'ready' ? (isBackdrop ? 0.85 : 1) : 0,
              transition: 'opacity 0.6s ease',
            } as React.CSSProperties
          }
        />
      )}
      {/* Belt-and-suspenders mask over the bottom-right Spline badge — the
          shadow-DOM CSS killer also fires, but if the viewer loads faster
          than our useEffect this overlay keeps the badge invisible. */}
      {status === 'ready' && (
        <div
          aria-hidden
          style={{
            position: 'absolute',
            bottom: 0,
            right: 0,
            width: 168,
            height: 44,
            background: 'linear-gradient(135deg, transparent 0%, var(--bg-void) 55%)',
            pointerEvents: 'none',
            zIndex: 3,
          }}
        />
      )}
      {/* Render the static double-ring fallback whenever the live viewer
          isn't showing — Spline failed / not ready yet, or it's disabled /
          paused. Applies to the backdrop variant too: on the Coverage hero
          there's no full-page starfield to fall back to, and the robot is the
          whole point, so the CSS rings stand in when the CDN can't be reached
          (offline / blocked). */}
      {(!allowed || status !== 'ready') && <FakeRobotRings />}
      {status === 'ready' && showChip && (
        <div
          aria-hidden
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 10px',
            background: 'rgba(15, 15, 34, 0.55)',
            border: '1px solid var(--border-soft)',
            borderRadius: 999,
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '0.08em',
            color: 'var(--accent-cyan)',
            textTransform: 'uppercase',
          }}
        >
          <span
            className="cosmic-pulse-dot"
            style={{ background: 'var(--accent-cyan)', boxShadow: 'var(--glow-cyan)' }}
          />
          AI Analyst
        </div>
      )}
    </div>
  )
}

function FakeRobotRings(): React.ReactElement {
  return (
    <div
      aria-hidden
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          width: 220,
          height: 220,
          borderRadius: '50%',
          background:
            'conic-gradient(from 0deg, rgba(59,130,246,0.45), rgba(139,92,246,0.45), rgba(34,211,238,0.35), rgba(59,130,246,0.45))',
          animation: 'cosmic-halo 12s linear infinite',
          opacity: 0.7,
          position: 'relative',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 18,
            borderRadius: '50%',
            background:
              'radial-gradient(circle at 30% 30%, rgba(34,211,238,0.6), rgba(15,15,34,0.95) 70%)',
            boxShadow: 'inset 0 0 40px rgba(59,130,246,0.3), 0 0 60px rgba(139,92,246,0.25)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            inset: 60,
            borderRadius: '50%',
            background: 'radial-gradient(circle at 50% 50%, rgba(255,255,255,0.1), transparent)',
          }}
        />
      </div>
    </div>
  )
}
