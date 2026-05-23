// TitleBar — cosmic redesign (spec §5.1).
//
// Reserves 72px on the left for Tauri's native macOS traffic lights
// (overlay titleBarStyle). Centre: FINAGENT brandmark with blue brand-dot
// and gradient logo word. Right: halo-input cmdK trigger + AI sparkle btn.

import { useAppStore } from '../stores/appStore'
import { useUiStore } from '../stores/uiStore'
import { IconSparkle } from '../lib/icons'

export function TitleBar(): React.ReactElement {
  const aiPanelOpen = useUiStore((s) => s.aiPanelOpen)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)
  const setCmdPaletteOpen = useAppStore((s) => s.setCmdPaletteOpen)

  return (
    <div
      className="titlebar"
      data-tauri-drag-region
      data-testid="titlebar"
      style={{
        position: 'relative',
        height: 44,
        padding: '0 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        background: 'var(--bg-sticky-78)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderBottom: '1px solid var(--border-faint)',
        zIndex: 80,
      }}
    >
      {/* macOS traffic lights overlay reservation */}
      <div style={{ width: 72, flexShrink: 0 }} />

      {/* Brandmark */}
      <button
        type="button"
        onClick={() => setCmdPaletteOpen(true)}
        title="⌘K"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: 'transparent',
          border: 'none',
          color: 'var(--text-primary)',
          cursor: 'pointer',
          fontFamily: 'var(--font-display)',
          fontSize: 14,
          letterSpacing: '4px',
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: 'var(--primary)',
            boxShadow: 'var(--glow-blue)',
          }}
        />
        <span
          style={{
            background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            color: 'transparent',
          }}
        >
          FINAGENT
        </span>
      </button>

      <div style={{ flex: 1 }} data-tauri-drag-region />

      {/* AI panel toggle */}
      <button
        className={`tb-btn${aiPanelOpen ? ' active' : ''}`}
        title="AI 助手 (⌘L)"
        onClick={toggleAiPanel}
        style={{
          width: 32,
          height: 32,
          display: 'grid',
          placeItems: 'center',
          border: `1px solid ${aiPanelOpen ? 'var(--border-glow)' : 'var(--border-soft)'}`,
          borderRadius: 8,
          background: aiPanelOpen ? 'var(--primary-soft)' : 'transparent',
          color: aiPanelOpen ? 'var(--primary)' : 'var(--text-secondary)',
          cursor: 'pointer',
          transition: 'all 0.2s',
          boxShadow: aiPanelOpen ? 'var(--glow-blue)' : 'none',
        }}
      >
        <IconSparkle size={14} />
      </button>
    </div>
  )
}
