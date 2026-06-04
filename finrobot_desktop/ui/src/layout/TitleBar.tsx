// TitleBar — cosmic redesign (spec §5.1).
//
// Reserves 72px on the left for Tauri's native macOS traffic lights
// (overlay titleBarStyle). Centre: FINROBOT brandmark with blue brand-dot
// and gradient logo word. Right: halo-input cmdK trigger + AI sparkle btn.

import { useUiStore } from '../stores/uiStore'
import { IconSparkle, IconCommand } from '../lib/icons'
import { useI18n } from '../i18n'
import { startWindowDrag } from '../lib/tauri'

export function TitleBar(): React.ReactElement {
  const aiPanelOpen = useUiStore((s) => s.aiPanelOpen)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)
  const setCmdPaletteOpen = useUiStore((s) => s.setCmdPaletteOpen)
  const { t, locale } = useI18n()

  // No existing .po key fits "open command palette"; use the inline
  // locale literal pattern (precedent: VersionDiffBanner / StatusBar) to
  // avoid .po coordination in this fix.
  const cmdPaletteLabel = locale === 'zh' ? '打开命令面板' : 'Open command palette'

  // Whole-bar window drag. Tauri v2's data-tauri-drag-region only works with
  // decorations:false; we keep native traffic lights (decorations:true +
  // titleBarStyle Overlay), so drag goes through startDragging() on mousedown.
  // Interactive controls (buttons) are skipped so clicks still register.
  const onTitleBarMouseDown = (e: React.MouseEvent<HTMLDivElement>): void => {
    if (e.button !== 0) return
    if ((e.target as HTMLElement).closest('button, a, input, [role="button"]')) return
    startWindowDrag(e.detail === 2)
  }

  return (
    <div
      className="titlebar"
      onMouseDown={onTitleBarMouseDown}
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
        aria-label={cmdPaletteLabel}
        title={`${cmdPaletteLabel} · ⌘K`}
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
          FINROBOT
        </span>
      </button>

      <div style={{ flex: 1 }} />

      {/* Command-palette trigger — compact pill, distinct from the Coverage
          ticker search; opens the existing CmdK overlay (artifacts/commands/nav). */}
      <button
        className="tb-btn"
        type="button"
        aria-label={cmdPaletteLabel}
        title={cmdPaletteLabel}
        onClick={() => setCmdPaletteOpen(true)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          height: 28,
          padding: '0 8px',
          border: '1px solid var(--border-soft)',
          borderRadius: 8,
          background: 'var(--bg-elevated)',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          transition: 'all 0.2s',
        }}
      >
        <IconCommand size={13} />
        <span style={{ letterSpacing: '0.5px' }}>⌘K</span>
      </button>

      {/* AI panel toggle */}
      <button
        className={`tb-btn${aiPanelOpen ? ' active' : ''}`}
        type="button"
        aria-label={t('shell.titlebar.aiAssistant')}
        title={t('shell.titlebar.aiAssistant')}
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
