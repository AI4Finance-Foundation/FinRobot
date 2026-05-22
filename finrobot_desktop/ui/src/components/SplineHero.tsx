// SplineHero — 3D AI Analyst figure for the ticker workspace hero.
//
// Loads @splinetool/viewer via its UMD bundle (the React wrapper hauls in
// extra dependencies we don't need for one scene). Failure paths:
//   - script fails to load → render the fake-robot double-ring fallback
//   - scene fails to load   → ditto via timeout (8s)
//
// Sizing: caller sets the bounding box (typically 40% width inside the
// hero grid); SplineHero fills it.

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

export function SplineHero({
  variant = 'hero',
  showStatusChip,
}: Props): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')
  const showChip = showStatusChip ?? variant === 'hero'

  useEffect(() => {
    let cancelled = false

    // Inject the viewer module once. Re-renders attach to the existing tag.
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-spline-viewer="1"]'
    )

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
  }, [])

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
      {status !== 'failed' && (
        <spline-viewer
          url={SCENE_SRC}
          events-target="global"
          style={{
            width: '100%',
            height: '100%',
            opacity: status === 'ready' ? (isBackdrop ? 0.85 : 1) : 0,
            transition: 'opacity 0.6s ease',
          } as React.CSSProperties}
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
            background:
              'linear-gradient(135deg, transparent 0%, var(--bg-void) 55%)',
            pointerEvents: 'none',
            zIndex: 3,
          }}
        />
      )}
      {status !== 'ready' && !isBackdrop && <FakeRobotRings />}
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
          <span className="cosmic-pulse-dot" style={{ background: 'var(--accent-cyan)', boxShadow: 'var(--glow-cyan)' }} />
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
            background: 'radial-gradient(circle at 30% 30%, rgba(34,211,238,0.6), rgba(15,15,34,0.95) 70%)',
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
