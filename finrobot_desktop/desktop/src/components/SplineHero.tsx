// SplineHero — 3D AI Analyst figure for the ticker workspace hero.
//
// Loads @splinetool/viewer via its UMD bundle (the React wrapper hauls in
// extra dependencies we don't need for one scene). Failure paths:
//   - script fails to load → render the fake-robot double-ring fallback
//   - scene fails to load   → ditto via timeout (LOAD_TIMEOUT_MS)
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

import { useCallback, useEffect, useRef, useState } from 'react'
// Vendored viewer: importing the package self-registers the <spline-viewer>
// custom element (customElements.define) at module load. Replaces the old
// unpkg remote <script> injection — no third-party CODE is fetched into the app
// context at runtime, which was the sharpest supply-chain risk under csp:null.
// The scene + its runtime WASM stay remote DATA (Spline can't be fully
// self-hosted: the viewer hardcodes the unpkg WASM URL); the tightened CSP in
// tauri.conf.json constrains those to the specific spline.design / unpkg hosts.
//
// CSP requires 'unsafe-eval' in script-src: the runtime's ndarray/cwise layer
// compiles kernels via `new Function` at scene load (5 call sites in the
// vendored bundle). Without it the scene downloads fine but load-complete never
// fires — WebKit rejects the eval, the LOAD_TIMEOUT_MS budget expires, and every
// packaged install degrades to the rings while dev (devCsp: null) looks healthy.
// Script SOURCES stay locked to 'self', so eval is only reachable from our own
// bundled code, not injected scripts.
//
// The import is DYNAMIC (see the effect in the component), NOT a top-level
// `import '@splinetool/viewer'`: the viewer drags in ~1.9MB of three.js +
// physics/navmesh runtime. A static import welds that whole graph onto the eager
// landing chunk even when the robot never renders — which this component already
// refuses to do off-screen. So we register the element on demand, the first time
// the hero is actually allowed to mount, keeping the runtime off cold start.

const SCENE_SRC = 'https://prod.spline.design/kZDDjO5HuC9GJUM2/scene.splinecode'
// Scene-load budget. The scene is 1.35 MB served with max-age=1y, so only the
// FIRST load ever pays the network: measured 6.4-8.1 s on a slow/proxied
// route, which a 8 s budget lost to (robot permanently degraded to rings on
// fresh installs). The rings fallback already covers the wait, so a generous
// budget costs nothing visually — after one success the HTTP cache makes
// every later launch instant.
const LOAD_TIMEOUT_MS = 30_000

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
  // Set true once the dynamic `import('@splinetool/viewer')` has resolved and
  // registered the custom element. Until then we can't render <spline-viewer>
  // (it wouldn't be defined), so the static rings stand in.
  const [viewerModuleReady, setViewerModuleReady] = useState(false)
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

  // The custom element is registered by the lazy import below (not a static
  // import), so once it's defined there is no per-element script to load —
  // readiness is the SCENE loading. Drive it off the viewer's own lifecycle
  // events, with the 8s timeout as the fallback to the static rings if
  // load-complete never arrives (offline / corrupt asset).
  const bindViewer = useCallback((el: HTMLElement | null) => {
    if (!el) return
    // { once } so re-renders don't stack listeners; attached at mount (before
    // the element's async scene load resolves) so we never miss load-complete.
    el.addEventListener('load-complete', () => setStatus('ready'), { once: true })
    el.addEventListener('error', () => setStatus('failed'), { once: true })
  }, [])

  // Lazy-load the vendored viewer the first time the hero is allowed to render.
  // import() is idempotent — the module executes and self-registers the custom
  // element once; later calls resolve the cached module — so re-entering
  // `allowed` is free. On failure we drop to the static rings instead of
  // rendering an undefined element.
  useEffect(() => {
    if (!allowed || viewerModuleReady) return
    let cancelled = false
    import('@splinetool/viewer')
      .then(() => {
        if (!cancelled) setViewerModuleReady(true)
      })
      .catch(() => {
        if (!cancelled) setStatus('failed')
      })
    return () => {
      cancelled = true
    }
  }, [allowed, viewerModuleReady])

  // Scene-load budget — armed only once the element is registered AND
  // mounting, so the timeout covers SCENE load (its original intent), not the
  // one-time module download which has no fixed budget on a cold network.
  useEffect(() => {
    if (!allowed || !viewerModuleReady) return
    const timeoutId = setTimeout(() => {
      setStatus((cur) => (cur === 'loading' ? 'failed' : cur))
    }, LOAD_TIMEOUT_MS)
    return () => clearTimeout(timeoutId)
  }, [allowed, viewerModuleReady])

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
          : 'radial-gradient(ellipse at center, color-mix(in srgb, var(--primary) 12%, transparent) 0%, transparent 70%)',
        // Cosmetic mask covering the lower-right corner where the Spline
        // branding sits before our shadow-DOM CSS injection lands.
        pointerEvents: isBackdrop ? 'none' : undefined,
      }}
    >
      {allowed && viewerModuleReady && status !== 'failed' && (
        <spline-viewer
          ref={bindViewer}
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
            background: 'color-mix(in srgb, var(--bg-card) 55%, transparent)',
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
            'conic-gradient(from 0deg, color-mix(in srgb, var(--primary) 45%, transparent), color-mix(in srgb, var(--secondary) 45%, transparent), color-mix(in srgb, var(--accent-cyan) 35%, transparent), color-mix(in srgb, var(--primary) 45%, transparent))',
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
              'radial-gradient(circle at 30% 30%, color-mix(in srgb, var(--accent-cyan) 60%, transparent), color-mix(in srgb, var(--bg-card) 95%, transparent) 70%)',
            boxShadow:
              'inset 0 0 40px color-mix(in srgb, var(--primary) 30%, transparent), 0 0 60px color-mix(in srgb, var(--secondary) 25%, transparent)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            inset: 60,
            borderRadius: '50%',
            background:
              'radial-gradient(circle at 50% 50%, color-mix(in srgb, var(--text-primary) 10%, transparent), transparent)',
          }}
        />
      </div>
    </div>
  )
}
