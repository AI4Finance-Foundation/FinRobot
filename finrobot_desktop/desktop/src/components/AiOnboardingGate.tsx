// First-run AI onboarding overlay — shown once when a fresh install has no LLM
// model configured yet. Unlike MandatoryUpdateGate this is DISMISSIBLE on
// purpose: the whole pitch is "the deterministic data layer works with no key",
// so the user must be free to browse prices/financials/valuations without a
// model. The overlay just makes the unlock obvious; the per-ticker report CTA
// (AIZone preflight) is the always-on backstop if they dismiss and try AI later.
//
// Trigger: backend reachable + model NOT configured + not dismissed THIS session
// + not already sitting on the Settings page (which has its own notice).
//
// Dismissal is SESSION-ONLY (in-memory), deliberately NOT persisted: as long as
// no model is configured the whole AI surface is locked, so every fresh launch
// re-prompts (the component remounts → `dismissed` resets to false). Within one
// session, closing it keeps it closed across route changes (this lives in
// AppShell, outside the router Outlet, so its state survives navigation). Once a
// model is configured `modelConfigured` is true and it never returns.

import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useHealth } from '../hooks/useHealth'
import { useI18n } from '../i18n'
import { AI_CHAT_ENABLED } from '../config/features'
import { SETTINGS_ALLOWED } from '../config/deployment'

export function AiOnboardingGate(): React.ReactElement | null {
  const { locale } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const { data: health, isPlaceholderData } = useHealth()
  const [dismissed, setDismissed] = useState(false)

  const zh = locale === 'zh'
  // Never gate on the seeded placeholder (modelConfigured defaults true there
  // anyway) — only a RESOLVED "no model" health shows the overlay.
  const resolved = isPlaceholderData ? null : health
  const onSettings = location.pathname.startsWith('/settings')

  if (
    dismissed ||
    onSettings ||
    resolved == null ||
    !resolved.backendReachable ||
    resolved.modelConfigured ||
    // Hosted: the deployment's model is configured centrally and this viewer
    // has no Settings door, so the overlay's whole call to action — "pick an
    // AI model" — is something they cannot do. It would open on first visit,
    // in front of the data they came for, offering a button that navigates
    // nowhere. The administrator still sees it, on a build where it works.
    !SETTINGS_ALLOWED
  ) {
    return null
  }

  function remember(): void {
    setDismissed(true)
  }

  function goConfigure(): void {
    remember()
    navigate('/settings')
  }

  const worksNow = zh
    ? ['实时价格与行情', '财务报表与历史', 'DCF / LBO / 可比公司估值']
    : ['Live prices & quotes', 'Financial statements & history', 'DCF / LBO / comps valuation']
  // AI chat is release-gated (VITE_ENABLE_AI_CHAT) — only advertise it as an
  // unlockable feature when it actually ships, else we'd promise a hidden panel.
  const needsModel = zh
    ? ['AI 研报(13 章)', ...(AI_CHAT_ENABLED ? ['AI 对话分析'] : [])]
    : ['AI research reports (13 ch.)', ...(AI_CHAT_ENABLED ? ['AI chat analysis'] : [])]

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={zh ? 'AI 模型配置引导' : 'AI model setup'}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'var(--scrim)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        display: 'grid',
        placeItems: 'center',
        zIndex: 9998, // just below MandatoryUpdateGate (9999)
      }}
    >
      <div
        style={{
          width: 520,
          maxWidth: '92vw',
          padding: '30px 32px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
            <circle cx="12" cy="12" r="9.2" stroke="var(--primary)" strokeWidth="1.6" />
            <path
              d="M9 12.5l2 2 4-4.5"
              stroke="var(--primary)"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--text-primary)' }}>
            {zh ? '欢迎 — 先认识一下底座' : 'Welcome — meet the data engine'}
          </div>
        </div>

        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {zh
            ? 'FinRobot 的数字由确定性引擎算出、可逐项溯源——无需任何 API key 就能用。上层的 AI 分析只是渲染口,需要你选一个模型并填好 key。'
            : 'FinRobot’s numbers come from a deterministic, fully-traceable engine — usable with no API key at all. The AI analysis layered on top is just a rendering layer; it needs a model you pick and key.'}
        </div>

        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <Column
            title={zh ? '现在就能用(免配置)' : 'Works now (no key)'}
            items={worksNow}
            tone="ok"
            zh={zh}
          />
          <Column
            title={zh ? '配模型后解锁' : 'Unlocked with a model'}
            items={needsModel}
            tone="locked"
            zh={zh}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 4 }}>
          <button
            type="button"
            className="btn"
            onClick={remember}
            style={{ background: 'transparent', color: 'var(--text-muted)' }}
          >
            {zh ? '先逛逛数据' : 'Explore data first'}
          </button>
          <button
            type="button"
            className="btn"
            onClick={goConfigure}
            style={{
              background: 'var(--primary)',
              borderColor: 'var(--primary)',
              color: 'var(--text-on-primary)',
              fontWeight: 600,
            }}
          >
            {zh ? '选择 AI 模型' : 'Pick an AI model'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Column({
  title,
  items,
  tone,
  zh,
}: {
  title: string
  items: string[]
  tone: 'ok' | 'locked'
  zh: boolean
}): React.ReactElement {
  const accent = tone === 'ok' ? 'var(--positive)' : 'var(--text-muted)'
  return (
    <div
      style={{
        flex: '1 1 200px',
        minWidth: 200,
        padding: '14px 16px',
        background: 'var(--bg-card)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md, 8px)',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          color: accent,
        }}
      >
        {title}
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
        {items.map((it) => (
          <li
            key={it}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 12.5,
              color: 'var(--text-secondary)',
            }}
          >
            <Glyph tone={tone} />
            {it}
          </li>
        ))}
      </ul>
      {tone === 'locked' && (
        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 'auto' }}>
          {zh
            ? '判断由你选的模型给,数字始终由引擎算'
            : 'Judgment by your model — numbers always by the engine'}
        </div>
      )}
    </div>
  )
}

function Glyph({ tone }: { tone: 'ok' | 'locked' }): React.ReactElement {
  if (tone === 'ok') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path
          d="M5 12.5l4 4 10-10"
          stroke="var(--positive)"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect
        x="5"
        y="10.5"
        width="14"
        height="9"
        rx="1.6"
        stroke="var(--text-muted)"
        strokeWidth="1.7"
      />
      <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" stroke="var(--text-muted)" strokeWidth="1.7" />
    </svg>
  )
}
