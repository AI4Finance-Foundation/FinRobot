// Boot splash — rendered by AppShell INSTEAD of the routed page while the
// Python sidecar is still booting (useHealth level === 'starting'). Pages
// therefore never mount against a dead backend, so the user never sees a wall
// of red query errors on a cold launch; once /health answers, the gate drops
// and every page mounts fresh with clean queries.
//
// Copy is inline-bilingual per the AIZone preflight precedent (short, stable
// system strings). Visuals follow the cosmic spec: var(--*) tokens only, the
// shimmer is loading feedback (§1.3), not decoration.

import { useI18n } from '../i18n'

export function BootSplash(): React.ReactElement {
  const { locale } = useI18n()
  const zh = locale === 'zh'

  return (
    <div
      data-testid="boot-splash"
      role="status"
      aria-live="polite"
      style={{
        height: '100%',
        display: 'grid',
        placeItems: 'center',
      }}
    >
      <style>{`
        @keyframes boot-splash-shimmer {
          from { transform: translateX(-100%); }
          to   { transform: translateX(250%); }
        }
      `}</style>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 18,
          padding: '40px 48px',
        }}
      >
        <div
          style={{
            fontSize: 26,
            fontWeight: 700,
            letterSpacing: '0.04em',
            color: 'var(--text-primary)',
            textShadow: 'var(--glow-blue)',
          }}
        >
          FinRobot
        </div>
        <div
          style={{
            width: 220,
            height: 3,
            borderRadius: 2,
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-faint)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: '40%',
              height: '100%',
              borderRadius: 2,
              background: 'linear-gradient(90deg, transparent, var(--primary), var(--accent-cyan))',
              boxShadow: 'var(--glow-cyan)',
              animation: 'boot-splash-shimmer 1s ease-in-out infinite',
            }}
          />
        </div>
        <div
          style={{
            fontSize: 13,
            color: 'var(--text-secondary)',
            letterSpacing: '0.02em',
          }}
        >
          {zh ? '正在启动分析引擎…' : 'Starting the analysis engine…'}
        </div>
        <div
          style={{
            fontSize: 11.5,
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
          }}
        >
          {zh ? '通常只需几秒' : 'usually just a few seconds'}
        </div>
      </div>
    </div>
  )
}
