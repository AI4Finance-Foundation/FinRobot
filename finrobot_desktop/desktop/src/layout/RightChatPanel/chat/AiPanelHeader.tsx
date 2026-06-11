// ──────────────────────────────────────────────────────────────
// AiPanelHeader — .ai-header
// ──────────────────────────────────────────────────────────────

import { useI18n } from '../../../i18n'
import { IconClock, IconPlus, IconClose } from '../../../lib/icons'

// Model badge — the chat runs on the SINGLE model configured in Settings
// (settings.model_name, e.g. "anthropic:claude-sonnet-4-6"). The badge is
// read-only and MUST reflect that real value. The label is derived from the
// provider registry returned by /api/settings (single source of truth — no
// hardcoded map that drifts), as "<provider label> · <model id>". An unknown
// provider falls back to the bare model id so the badge stays honest.
export function modelLabel(
  modelName: string | undefined,
  providers: { id: string; label: string }[] | undefined,
): string {
  if (!modelName) return '…'
  const [providerId, ...rest] = modelName.split(':')
  const modelId = rest.join(':')
  const provider = providers?.find((p) => p.id === providerId)
  if (provider) return modelId ? `${provider.label} · ${modelId}` : provider.label
  return modelId || modelName
}

interface AiPanelHeaderProps {
  modelLabel: string
  onToggle: () => void
  onNewSession: () => void
  onOpenHistory: () => void
  ticker: string | undefined
  /** Streaming — gives the presence orb its (spec-legal, ≤1.6s) live pulse. */
  thinking: boolean
}

export function AiPanelHeader({
  modelLabel,
  onToggle,
  onNewSession,
  onOpenHistory,
  ticker,
  thinking,
}: AiPanelHeaderProps): React.ReactElement {
  const { t, locale } = useI18n()

  return (
    <div className="ai-header" data-testid="panel-header">
      {/* Presence orb — living AI brand mark (static glow; pulses only while
          streaming). Replaces the old flat "F" tile. */}
      <div className={`ai-presence${thinking ? ' thinking' : ''}`} aria-hidden="true">
        <span className="halo" />
        <span className="core" />
      </div>
      <div className="ai-title">
        Fin<b>Robot</b>
      </div>

      {/* Ticker / Explore context tag — text kept verbatim (asserted by tests). */}
      <span className="ai-ctx-tag">
        <span
          className="dot"
          style={{
            background: ticker ? 'var(--aip-accent)' : 'var(--text-dim)',
            boxShadow: ticker ? '0 0 7px var(--aip-accent)' : 'none',
          }}
        />
        {ticker ?? t('chat.title.explore')}
      </span>

      {/* Model badge (read-only — model configured in Settings) */}
      <span
        data-testid="model-selector"
        className="ai-model"
        title={t('chatpanel.model.configuredInSettings')}
      >
        {modelLabel}
      </span>

      {/* Sessions — list / switch / delete past conversations */}
      <button
        data-testid="history-btn"
        onClick={onOpenHistory}
        title={locale === 'zh' ? '会话' : 'Sessions'}
        className="ai-icon-btn"
        type="button"
      >
        <IconClock size={15} />
      </button>

      {/* New session */}
      <button
        data-testid="new-session-btn"
        onClick={onNewSession}
        title={t('chat.newSession')}
        className="ai-icon-btn"
        type="button"
      >
        <IconPlus size={15} />
      </button>

      {/* Close / collapse */}
      <button
        data-testid="collapse-btn"
        onClick={onToggle}
        title={t('chat.collapse')}
        className="ai-icon-btn"
        type="button"
      >
        <IconClose size={15} />
      </button>
    </div>
  )
}
