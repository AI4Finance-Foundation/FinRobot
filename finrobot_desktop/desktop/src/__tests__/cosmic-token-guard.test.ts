/**
 * Cosmic-token guard (BUG-20260602-022).
 *
 * These five UI surfaces were reworked from a mix of hardcoded hex / rgba
 * colors to cosmic `var(--*)` tokens. This test loads their *source* (via
 * Vite's `?raw` import) and fails if a raw color literal sneaks back in, so
 * the theming contract stays closed. Scoped to these files only — it does
 * NOT police the whole repo.
 *
 * What counts as a violation:
 *   - hex color literals:            #fff, #1a1207, #05050d, …
 *   - rgb()/rgba() function calls:   rgba(255,255,255,0.04), rgb(…)
 *   - legacy color aliases:          var(--red|green|blue|purple) — cosmic
 *     spec wants semantic tokens (--danger / --success / --primary /
 *     --secondary) instead of these raw color names.
 *
 * Allowed (NOT violations):
 *   - color-mix(in srgb, var(--token) N%, transparent) — the project's
 *     established pattern for token-derived translucency.
 *   - any other var(--*) token.
 *
 * If a future change genuinely needs a raw literal (e.g. an inline SVG that
 * truly cannot take a token), exclude that exact line with a trailing
 * `// token-guard-allow` comment and explain why.
 */
import { describe, it, expect } from 'vitest'

// Raw source of each guarded file. `?raw` gives us the verbatim text without
// executing the module (and without needing Node's fs types in the web build).
import titleBarSrc from '../layout/TitleBar.tsx?raw'
import settingsViewSrc from '../views/SettingsView.tsx?raw'
import settingsControlsSrc from '../views/settings/controls.tsx?raw'
import settingsProviderDropdownSrc from '../views/settings/ProviderDropdown.tsx?raw'
import settingsAiModelPanelSrc from '../views/settings/AiModelPanel.tsx?raw'
import settingsDataSourcesPanelSrc from '../views/settings/DataSourcesPanel.tsx?raw'
import settingsSecHoldingsSrc from '../views/settings/SecHoldingsSection.tsx?raw'
import settingsUpdatesSrc from '../views/settings/UpdatesSection.tsx?raw'
import settingsClearKeyModalSrc from '../views/settings/ClearKeyConfirmModal.tsx?raw'
import versionDiffBannerSrc from '../components/VersionDiffBanner.tsx?raw'
import aiChatTabSrc from '../layout/RightChatPanel/AiChatTab.tsx?raw'
import chatHeaderSrc from '../layout/RightChatPanel/chat/AiPanelHeader.tsx?raw'
import chatMessageListSrc from '../layout/RightChatPanel/chat/MessageList.tsx?raw'
import chatMessageBubbleSrc from '../layout/RightChatPanel/chat/MessageBubble.tsx?raw'
import chatStatusIndicatorSrc from '../layout/RightChatPanel/chat/StatusIndicator.tsx?raw'
import chatInputAreaSrc from '../layout/RightChatPanel/chat/AiInputArea.tsx?raw'
import chatIconColumnSrc from '../layout/RightChatPanel/chat/IconColumn.tsx?raw'
import splineHeroSrc from '../components/SplineHero.tsx?raw'

const GUARDED: Array<[string, string]> = [
  // TitleBar absorbed the retired Sidebar's nav; keep it token-pure here.
  ['layout/TitleBar.tsx', titleBarSrc],
  // SettingsView was split into views/settings/* (2026-06-11) — every shard
  // that renders styles stays under the guard so the contract survives moves.
  ['views/SettingsView.tsx', settingsViewSrc],
  ['views/settings/controls.tsx', settingsControlsSrc],
  ['views/settings/ProviderDropdown.tsx', settingsProviderDropdownSrc],
  ['views/settings/AiModelPanel.tsx', settingsAiModelPanelSrc],
  ['views/settings/DataSourcesPanel.tsx', settingsDataSourcesPanelSrc],
  ['views/settings/SecHoldingsSection.tsx', settingsSecHoldingsSrc],
  ['views/settings/UpdatesSection.tsx', settingsUpdatesSrc],
  ['views/settings/ClearKeyConfirmModal.tsx', settingsClearKeyModalSrc],
  ['components/VersionDiffBanner.tsx', versionDiffBannerSrc],
  // AiChatTab was split into chat/* (2026-06-11) — same guard, every shard.
  ['layout/RightChatPanel/AiChatTab.tsx', aiChatTabSrc],
  ['layout/RightChatPanel/chat/AiPanelHeader.tsx', chatHeaderSrc],
  ['layout/RightChatPanel/chat/MessageList.tsx', chatMessageListSrc],
  ['layout/RightChatPanel/chat/MessageBubble.tsx', chatMessageBubbleSrc],
  ['layout/RightChatPanel/chat/StatusIndicator.tsx', chatStatusIndicatorSrc],
  ['layout/RightChatPanel/chat/AiInputArea.tsx', chatInputAreaSrc],
  ['layout/RightChatPanel/chat/IconColumn.tsx', chatIconColumnSrc],
  // Hero/fallback gradients were de-hardcoded 2026-06-10 (P2 audit).
  ['components/SplineHero.tsx', splineHeroSrc],
]

// 3-, 4-, 6- and 8-digit hex color literals (`#fff`, `#1a1207`, `#0a0a18ff`).
// Anchored to a `#` followed by exactly 3/4/6/8 hex digits at a word boundary,
// which avoids matching e.g. anchors (`#valuation`) or longer ids.
const HEX_RE = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b/
// rgb()/rgba() function calls.
const RGB_RE = /\brgba?\s*\(/
// Legacy raw-color aliases — use semantic tokens instead.
const LEGACY_ALIAS_RE = /var\(\s*--(?:red|green|blue|purple)\s*\)/

const ALLOW_MARKER = 'token-guard-allow'

describe('cosmic token guard — BUG-20260602-022', () => {
  it.each(GUARDED)('%s has no hardcoded color literals', (rel, source) => {
    const offenders: string[] = []

    source.split('\n').forEach((line, i) => {
      if (line.includes(ALLOW_MARKER)) return
      if (HEX_RE.test(line) || RGB_RE.test(line) || LEGACY_ALIAS_RE.test(line)) {
        offenders.push(`  ${rel}:${i + 1}  ${line.trim()}`)
      }
    })

    expect(
      offenders,
      `Hardcoded color literal(s) found — use cosmic var(--*) tokens ` +
        `(or color-mix(in srgb, var(--token) N%, transparent)):\n${offenders.join('\n')}`,
    ).toEqual([])
  })
})
